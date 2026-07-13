# AXI4 读交织约束报告

## 目标与结论

本项目是形式化验证相关的协议模型。本场景位于
`protocol_model/projects/prj_axi4_read_interleave/`，专门验证 AXI4 read data 在不同 ID
之间交织，并用可执行负例确认约束确实生效。运行命令：

```bash
python3 -m protocol_model axi-read-interleave
```

报告输出到 `out/prj_axi4_read_interleave/01/report.html`。同目录还会
生成 `waveform.svg`（AXI 波形）、`network.svg`（两 VirtualDut 网络）和
`causality.svg`（两条 per-ID 因果链）。Project
先提取基础 AXI4 `ProtocolSpec`，再派生一份实验专用 spec；不会把场景约束写回通用协议。
协议层负责 ID 位宽、请求/响应匹配、同 ID 顺序和 burst 拍序；Project profile 负责本次
实验只使用 ID 1/2、无关 sideband 绑零、写通道 quiet。

约束构造统一经过 `protocols.spec.ProtocolDerivation`：它从基础 `ProtocolSpec` 复制 schema/rules，
使用 `replace_ready_valid_channel()` 重绑受限 AR/R event space，使用
`replace_transaction_model()` 重绑 read obligation，并通过 `ConstraintRecord` 保存每条新增
约束的名称、目标、foundation 和 `PROFILE` scope。报告和网络图直接读取这些派生记录。

## 实验拓扑

```text
input VirtualDut (ScriptedSource)
          │ two AR, ID=1/2
          ▼
derived AXI4 ProtocolSession
          │ accepted AR / checked R
          ▼
output VirtualDut (InterleavingReadResponder)
```

输入 VirtualDut 只拥有 AR 输出；输出 VirtualDut 接收两个 AR 后按 ID 2、1、2、1 生成 R beat，
让后发的 ID2 先响应、先完成。两个节点选择行为，协议 session 判定这些行为是否合法。

## 本场景约束

| 约束 | 来源 | 当前实现 |
|---|---|---|
| 全局 ID 值在 `0 .. 2^ID_WIDTH-1` | AXI4 schema | `BitVectorDomain(id_width)` |
| 本场景只允许 `ARID/RID ∈ {1,2}` | PROFILE | AR/R 共用 `EnumDomain((1,2))` |
| R beat 的 RID 必须存在对应的 pending ARID | AXI4 | keyed read obligation；orphan R 被拒绝 |
| 相同 ID 必须消费最老的 pending burst | AXI4 | per-ID FIFO token |
| 同一 burst 为 `ARLEN+1` 拍，仅末拍 `RLAST=1` | AXI4 | cardinality obligation |
| 不同 ID 的 R beat 可以交织 | AXI4 | 每个 ID 独立保存 remaining/previous beat |
| `ARLOCK/ARCACHE/ARPROT/ARQOS/ARREGION = 0` | PROFILE | `ConstantDomain(0)` |
| `AWVALID/WVALID/BVALID = 0` | PROFILE | signal 层检查，并拒绝 canonical AW/W/B transfer |

这里的 quiet 是“绑为常量并检查”，不是忽略观测。`ARCACHE=0` 明确排除 cache 属性变化；
`ARLOCK=0` 禁用 exclusive access。AXI4 没有 AXI5 的 atomic/`AWATOP` 信号，因此本模型不
虚构 atomic 字段；如果接口实际是 AXI5，应建立 AXI5 profile 并单独约束 `AWATOP`。

## 读交织 witness

正例固定为两个 2-beat burst：

```text
AR(id=1, len=1)
AR(id=2, len=1)
R (id=2, last=0)
R (id=1, last=0)
R (id=2, last=1)
R (id=1, last=1)
```

该 trace 为 `PASS`。AR1 先于 AR2，但 R2 先响应且先完成，因此它是跨 ID 乱序完成的构造性
witness；同时 R2/R1 的 beat 交替也展示了 read data interleaving。

| 单点 mutation | 预期 | 实际约束 |
|---|---|---|
| 第二个同 ID 短 burst 越过第一个长 burst | FAIL | `axi4.read_beats.final_marker` |
| `RID` 位宽合法但不属于 active ID 集合 | FAIL | R event-space/profile ID domain |
| `ARCACHE` 从 quiet 值 0 改为 1 | FAIL | AR event-space `ConstantDomain(0)` |
| `AWVALID=1, AWREADY=0` | FAIL | `axi4.signal_session.quiet_channel` |

## ID 约束应该是什么样

AXI4 ID 不应简单约束成“所有请求 ID 固定不变”。合理约束是：

1. `ARID` 和 `RID` 满足接口声明的位宽；具体实验可以再限制 active ID 集合。
2. 每个 R beat 的 `RID` 必须对应一个尚未完成的同 ID 读请求。
3. 同一 manager、同一 direction、同一 ID 的事务必须保持请求顺序；本模型以最老 token
   匹配响应，并保持 burst 内 beat 顺序。
4. 不同 ID 不要求全局排序，允许 beat 交织；是否仲裁、何时响应属于 endpoint/DUT 行为。
5. 同一个 ID 可以有多个 outstanding request，但不能用后发请求的响应越过先发请求。
6. bridge/interconnect 若扩展或重映射 ID，需要把上下游 ID 映射作为独立的功能不变量检查。

## 仍不完善的地方

以下内容不能因为本次 witness 通过就报告为已覆盖：

- 多 manager 场景中的完整 ordering domain 与 interconnect ID 扩展；
- endpoint 的 total/per-ID maximum outstanding capability；
- exclusive access、AXI5 atomic、barrier 及 USER 信号语义；
- 地址重叠导致的功能相关性、memory 返回数据正确性；
- arbitration、公平性、最终响应等 liveness 假设；
- input-to-output 无组合路径等需要 RTL/netlist formal evidence 的结构属性；
- VCD/FSDB/UVM/RTL adapter，因此当前尚未直接证明真实 DUT 波形或所有实现路径。

后续若接真实 DUT，建议先补 observation adapter 和 outstanding capability，再把本报告的
五条 witness 作为 Project 自检基线。

机器可读的完整约束表位于同一 run 目录的 `constraints.json`，人工审阅版为
`constraints.md`；`manifest.json` 记录 verdict、case、协议实例和每个产物的 SHA-256。
