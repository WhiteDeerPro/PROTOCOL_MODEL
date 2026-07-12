# AXI4 Derivation Plan

本文不是重新编写一个专用 AXI checker，而是用 AXI4 检验当前元组件体系能否逐层长成一个真实协议模型。

规范基线使用 Arm IHI 0022H 的 AXI4/AXI5 公共章节。AXI4 有 AW、W、B、AR、R 五个 channel；每个 channel 有自己的 VALID/READY，burst 不得跨 4KB，AXI4 INCR 支持最多 256 transfer，同 ID response 保序而不同 read ID 可以交织。[Arm AMBA AXI/ACE Specification](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf)

## 1. 从 Chisel 借鉴什么

Chisel 不是传统“把 C 算法调度成 RTL”的 HLS，而是参数化硬件构造语言。我们借鉴的是 generator/elaboration/IR 方法：

1. Scala/Python 对象负责参数化构造；
2. elaboration 产生稳定、可验证的中间表示；
3. compiler pass 逐级 lowering；
4. 每一级有明确 type/operation 语义；
5. 保留源对象到低层结果的可调试映射。

Chisel 用 `Bundle` 复用接口，用 `Decoupled` 表达 ready/valid 形状。`Decoupled` 不保证 stall 时 bits 稳定；`Irrevocable` 才约定 valid 和 bits 的保持，而且文档明确这种约定不会被接口类型自动强制。[Chisel Interfaces and Connections](https://www.chisel-lang.org/docs/explanations/interfaces-and-connections)

对应到本项目：

```text
ChannelSpec     ≈ interface shape
EventSpace      ≈ typed payload domain
ProtocolRule    ≈ behavioral convention/assertion
Monitor lowering ≈ 把 convention 编译为状态机检查
```

因此不能因为 AXI channel 被声明成 ready-valid，就认为 VALID stability 已经实现。schema 与 temporal rule 必须分开。

FIRRTL/CIRCT 还说明一个实用原则：不要让一个高层 IR 同时承担所有低层细节。FIRRTL 通过 pass lowering 到更低类型和硬件 dialect，同时努力保存名字和调试对应关系。[CIRCT FIRRTL Rationale](https://circt.llvm.org/docs/Dialects/FIRRTL/RationaleFIRRTL/)

我们的 counterpart 是：

```text
Axi4Config
    ↓ elaborate
ProtocolSpec IR
    ↓ lower handshakes
ChannelTransfer IR
    ↓ assemble beats/joins
Transaction IR
    ↓ bind ports and DUTs
Network IR
    ↓ attach observations
Evidence-backed ExecutionTrace
```

每一级都应有 verifier，lowering 应保留 provenance，不能让 `AW_TRANSFER` 与原始 waveform cycle 失去对应。

## 2. 从 HLS/dataflow 借鉴什么

CIRCT HLS 使用 pass pipeline，把不同层的 MLIR/CIRCT dialect 串联起来，而不是用一个巨型模型一步完成转换。[CIRCT HLS](https://circt.llvm.org/docs/HLS/)

Handshake dialect 将 dataflow 表示为独立、未同步的 process，通过 FIFO channel 传递数据，并显式提供 buffer、fork、merge、control-merge 和 sync/join operation。[CIRCT Handshake Dialect](https://circt.llvm.org/docs/Dialects/Handshake/)

这对 AXI 很重要：

- AW、W、B、AR、R 应建成相对独立的 channel process；
- AW 和完成的 W burst 通过 join 产生 B obligation；
- AR token 展开成一定 cardinality 的 R beat token；
- buffer/FIFO 深度影响 backpressure 和 deadlock，但不改变接口 schema；
- arbitration/merge 是明确 operation，不能由 Python 事件遍历顺序暗中决定。

Vitis HLS 的 dataflow 文档指出 FIFO 深度选择不当可能造成 deadlock，而 PIPO 代价更大但不会产生同类 FIFO deadlock。这支持我们把 capacity/resource 升级为可分析的 place/marking，而不只是一个计数器。[AMD Vitis HLS Dataflow Memory Channels](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Configuring-Dataflow-Memory-Channels)

HLS interface synthesis 还把函数参数/数据结构与实际 AXI、FIFO、wire protocol mapping 分开。[AMD Vitis HLS Interface Synthesis](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Defining-Interfaces) 对本项目的启示是：VirtualDut 的功能 action 与它绑定的 AXI Port 必须是两层对象。

## 3. AXI4 的 IR 层次

### L0：参数与能力

当前已实现 `Axi4Config`：

```python
Axi4Config(
    address_width=32,
    data_width=64,
    id_width=4,
)
```

它负责 elaboration-time 合法性，不保存 runtime outstanding。

未来能力参数包括：

- read-only/write-only；
- user signal widths；
- optional region/qos；
- maximum outstanding；
- supported burst types；
- narrow/unaligned capability。

这些有些属于 interface parameter，有些属于特定 DUT capability，不能全部写进 AXI 协议全局规则。

### L1：Channel schema IR

当前已实现五个 `ChannelSpec`，每个包含：

```text
name
source role
destination role
transfer EventSpace
```

规范事件是成功 handshake 后的 transfer：

```text
AW_TRANSFER(id, addr, len, size, burst, ...)
W_TRANSFER(None, data, strb, last)
B_TRANSFER(id, resp)
AR_TRANSFER(id, addr, len, size, burst, ...)
R_TRANSFER(id, data, resp, last)
```

W 的 key 明确为 `None`，因为 AXI4 W channel 没有 WID。后续 AW/W 关联必须使用接受顺序和 burst 边界，不能制造一个 waveform 中不存在的 ID。

### L2：Clocked signal IR

已实现第一版。它接收每个 rising edge 的：

```text
reset
valid
ready
payload
```

并由通用 `ClockedReadyValid` monitor automaton 产生 transfer event：

```text
fire := valid && ready

valid && !ready
    => next(valid)
    && next(payload) == payload
```

AXI 规定 source 不能等待 READY 后才断言 VALID；VALID 断言后必须保持到 handshake，payload 也必须稳定。[Arm AXI handshake rules](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf)

但“source 是否因为 READY 才决定断言 VALID”涉及策略依赖，仅凭一次有限 waveform 不总能推断意图。应区分：

- 可观测 safety：VALID 已高且未 handshake 时不得撤销/修改；
- strategy/structural property：VALID 产生逻辑不能依赖 READY；
- RTL structural property：接口 input/output 间无组合路径。

最后一项通常需要 netlist/formal/结构证据，不能假装从采样 trace 中完整证明。

### L3：Transaction/resource IR

这是 AXI 对当前理论体系的主要压力。

#### Write

```text
AW accepted ───────────┐
                      ├─ join → pending B obligation(id)
W beats ... WLAST ────┘

B(id) consumes the oldest pending B obligation for that ID
```

需要：

- `ColoredPlace[AwToken]`；
- `ColoredPlace[WBurstToken]`；
- `OrderedMatcher`：将无 ID 的 W burst 与 AW 顺序关联；
- `JoinTransition`：消费一个 AW 和一个完整 W burst；
- `CardinalityObligation`：beat 数与 AWLEN+1 一致；
- per-ID FIFO marking。

AXI4 write response 必须等待 AW handshake 和最后一个 W transfer 完成，且 BVALID 不能等待 BREADY。[Arm AXI channel dependencies](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf)

#### Read

```text
AR(id, len=N)
    → produce RBeatObligation(id, remaining=N+1)

R(id, last=0)
    → consume one non-final beat

R(id, last=1)
    → only legal when remaining == 1
```

这是带颜色和 cardinality 的 Petri place，比当前“一请求一响应”的 `Obligation` 更强。

### L4：Ordering 与 true concurrency

AXI 保证同 master、同 ID 的 read response 和 write response保序；不同 read ID 可以 interleave。[Arm AXI ordering model](https://developer.arm.com/-/media/Arm%20Developer%20Community/PDF/IHI0022H_amba_axi_protocol_spec.pdf)

需要：

```text
ordering domain = (direction, master identity, AXI ID)
```

以及显式 `IndependenceRelation`：

- 不同 ID 不自动独立，还要考虑地址 overlap、barrier、exclusive 等；
- AW 与 W 接受通常没有直接因果先后，但都可能是 B 的前驱；
- R beat 跨 ID 可以不可比较，同一 burst 内 beat 必须有顺序。

因此仅有 keyed FIFO token 不足，需要 pomset/event-structure 层表达 causality、conflict 和 independence。

### L5：DUT 与网络行为

以下内容不是 AXI ProtocolSpec：

- RAM 返回什么数据；
- peripheral 支持哪些地址/size/burst；
- bridge 如何 decode 和转换；
- interconnect 如何仲裁；
- slave 选择多少周期后 READY/VALID。

它们属于 VirtualDut capability/behavior、Bridge translation 或 scheduler policy。ProtocolSession 只检查这些选择是否保持 AXI 合法。

## 4. 当前已经实现的 AXI4 部分

代码：[`protocol_model/protocols/axi4/spec.py`](../protocol_model/protocols/axi4/spec.py)

| 项目 | 状态 |
|---|---|
| 参数化 address/data/ID width | 已实现 |
| 五 channel 角色与方向 | 已实现 |
| 大 bit-vector domain sampling/membership | 已实现 |
| AW/AR payload schema | 已实现基础字段 |
| W/B/R payload schema | 已实现基础字段 |
| AxLEN/AxSIZE/AxBURST domain | 已实现 |
| WRAP 长度与起始对齐 | 已实现 |
| 4KB boundary predicate | 已实现 |
| clocked VALID/READY monitor | 已实现，五通道均实例化 |
| stall 时 VALID/payload 稳定 | 已实现 |
| reset epoch | 已实现，reset 清除 channel stall 与 transaction token |
| BVALID/RVALID assertion dependency | 已实现于 whole-interface signal session |
| FIXED burst 最大 16 拍 | 已实现 |
| 每拍 FIXED/INCR/WRAP 派生地址 | 已实现 |
| narrow/unaligned WSTRB byte-lane mask | 已实现 |
| AW/W FIFO correlation 与 join | 已实现 |
| WLAST/AWLEN 跨流 cardinality | 已实现 |
| joined write→B obligation | 已实现 |
| AR→R multibeat cardinality/RLAST | 已实现 |
| read/B completion 的 per-ID FIFO | 已实现为 keyed FIFO token |
| 同周期跨 channel 动态 independence | 已实现 finite commutation/diamond check |
| 五通道 constructive random scheduler | 已实现 |
| waveform→transfer→session replay | 已实现 |
| WaveDrom/Graphviz evidence | 已实现 |

`ProtocolSpec.requirements` 把每条规则需要的 foundation 和实现状态保存在 IR 内，避免文档与代码成熟度再次分离。

## 5. 理论/基础元素缺口

| AXI 需求 | 应汲取的理论/基础 |
|---|---|
| input/output ownership | I/O automata/interface automata |
| ready-valid stall | clocked monitor automaton、finite temporal safety |
| reset | epoch/state-machine semantics |
| AW/W join | colored Petri transition / dataflow sync |
| exact beat count | multiset + cardinality arc |
| ID-less W association | ordered matching relation |
| per-ID ordering | colored FIFO place |
| cross-ID interleave | independence relation、pomset |
| burst path expression | pure arithmetic predicate |
| no combinational path | structural evidence/formal property，不是普通 trace rule |
| eventual progress | fairness/environment assumption；AXI 不应被随意加上 liveness |

## 6. 下一步实现顺序

1. `ProtocolSpec` / `ProtocolSession` 分离；
2. ~~`ClockedReadyValid`：先在一个 channel 上生成和检查 cycle trace；~~
3. ~~`ResetEpoch`；~~
4. ~~keyed cardinality token；~~
5. ~~AR→R cardinality，先完成 read-only AXI transaction validation；~~
6. ~~per-ID FIFO completion token；~~
7. ~~AW/W join 和 ID-less W matcher；~~
8. ~~五通道统一 scheduler 与 causal graph；~~
9. ~~dumb responder 终止 read transaction；~~
10. ~~两个 AXI session + read bridge 组成首个 Project；~~
11. 给 Project 增加 latency/backpressure 与自动 port routing；
12. 再扩展 write bridge、memory VirtualDut 和多 case plan。

完成每一级时必须同时具备：

```text
elaboration validation
legal sampling/generation
observed membership/checking
negative mutation test
causal edge/provenance
```

如果某一层只能通过新增 `AxiSpecialCaseChecker` 完成，应停止实现并回到元组件设计。
