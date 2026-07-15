# AXI4 LinkProtocol 当前实现范围

当前实现覆盖 AXI4 canonical-event 层的五个 channel。AR/R 使用 keyed cardinality；AW/W/B 使用
burst assembler、FIFO join 和 completion ledger。五个 ready-valid lane 已能从同一个 `AtomicFrame`
进入 link session；raw RTL 字段采集和具体组网仍是后续边界，也不表示 AXI4 的全部可选信号与
系统规则已经建模。

代码位于 `protocol_model/link/amba/axi/axi4/`：AXI4 是 `LinkProtocol` 库成员；`protocol_model/link/` 根部
保留 LinkProtocol 抽象和 session。

## 当前层次

```text
BitVectorDomain / EnumDomain.sample
                 ↓
EventSchema.generate(EventOffer)
                 ↓
CardinalityMonitor.event_offers(state)
                 ↓
LinkSession.event_offers / generate_event
                 ↓
Axi4ReadGenerator / Axi4WriteGenerator
                 ↓
five-channel canonical LinkTrace
```

观察路径与生成路径共用同一套 event schema 和 transaction monitor：

```text
AtomicFrame(AW, W, B, AR, R, reset)
                 ↓
ReadyValidObserver × 5 + ResetEpochObserver × 5
                 ↓
Axi4ObservationSession lowering phases
                 ↓
LinkSession.step_batch (all-or-nothing commit)
```

`EventOffer` 是部分赋值，不是已经发生的协议事件。例如 pending read token 会给出：

```text
kind=R, key=<ARID>, payload.last=<由 remaining 推导>
```

`EventSchema` 再从值域生成 data/resp 等未固定字段，并执行 schema constraints。生成出的事件仍通过
同一个 `LinkSession.step()` 验证，没有单独维护一份“生成规则”。

## 已建模内容

- manager/subordinate roles；
- AR 与 R channel direction；
- address、ID、data、response 等字段值域；
- FIXED/INCR/WRAP length、WRAP alignment、4KB boundary 和地址空间上界；
- full-width、narrow 与 unaligned transfer 的逐拍地址、byte-lane 范围和 WSTRB 合法掩码；
- `ARLEN + 1` 个 R beat obligation；
- RLAST final marker；
- 同 ID 使用最老 pending token，不同 ID 可以由生成器交织选择；
- 显式 read interleave 调度可以生成 `R1, R2, R1-last, R2-last`，同 ID 仍按请求顺序完成；
- AW 与 ID-less W burst 按各自 acceptance order 做 FIFO join；
- W 可以先于 AW 被观察并等待 join；
- W beat count、WLAST 和 WSTRB byte lanes；
- join 完成后建立 B completion token，BID 消耗同 ID 最老 token；
- exclusive burst 的长度、总字节数和对齐限制；
- exclusive read response consistency、read-before-write、属性匹配，以及 `EXOKAY` success eligibility；
- 五通道 stall stability 和共享 normalized reset epoch；
- 同帧 link event 统一提交或回滚；响应先读取帧前状态，避免 R/B 消费本帧刚创建的义务；
- 可限制生成时最大 burst beats 的 policy，该 policy 只收窄生成空间，不改变协议可接受空间；
- `LinkProtocol.forbid_events()` 可构造保留五通道形状的 read-only 等 link profile；
- `Axi4ObservationPolicy.tied_inactive_channels` 可进一步要求对应 pin observation 的 VALID 保持低电平。

## 写路径组合

```text
BurstAssembler(W/WLAST)
          │ complete burst
          ▼
FifoJoin(AW descriptor, W burst)
          │ joined token
          ▼
CompletionLedger(BID)
```

这些组件位于通用 pattern 层；`Axi4WriteMonitor` 添加 AWLEN、WSTRB 和 AXI channel kind。

## 方法放置边界

| 方法形状 | 当前位置 | 判断 |
|---|---|---|
| exact-count keyed obligation | `patterns.CardinalityMonitor` | 不依赖 AXI 字段名，可直接复用 |
| beat assembly、FIFO descriptor/data join、completion resource | `patterns.correlation` | 是通用事务机制，由 AXI monitor 配置并组合 |
| 原子 batch commit/rollback | `link.LinkSession` | 对多 channel LinkProtocol 有用，不携带 AXI 顺序 |
| ready-valid stall、reset epoch | `observation` | 属于可复用 observation policy |
| AW/W/B 组合顺序、AR/R 与字段映射 | `link.axi4` | 是 AXI channel 关系，保留为本地组合策略 |
| FIXED/INCR/WRAP、4KB、WSTRB lane | `link.axi4.burst` | 当前是 AXI 规则；等第二种协议出现同形需求后再判断是否提取 |

因此 AXI4 本地方法不等于无法复用：其中多数是“通用机制 + AXI 参数/字段关系”的派生组合。
只有机制本身不依赖 AXI vocabulary、并且存在独立状态契约时才进入 `patterns`。这样 TileLink 等后续
协议可以检验抽象是否成立，不需要为了目录整齐预先制造一个过宽的 pattern。

当前同帧 lowering 使用 `B, R → W → AW, AR`：B/R 只能消费采样边沿之前已存在的义务；W 与 AW
仍可在同帧完成 FIFO correlation。这是 AXI 本地 phase policy，不宣称是任意 LinkProtocol 的默认顺序。
后续可在此基础上补 raw RTL pin adapter、更多 ordering/profile sideband，以及具体 VirtualDut 行为。

“quiet”在当前架构中不是一个同时驱动验证与显示的开关：禁止 canonical event 属于 LinkProtocol
profile；VALID tied-low 或 sideband tied/stable 属于 observation policy；`LaneDisplayPolicy` 只决定投影
中是否隐藏 lane。隐藏 inactive lane 可以改善阅读，但不单独构成 quiet 的验证结论。

## Exclusive 当前边界

`Axi4ExclusiveMonitor` 在一条 link 上记录 read/write context 和完成的 exclusive-read reservation。
当前可执行检查包括：

- normal read/write response 不使用 `EXOKAY`；
- 一个 exclusive read transaction 不混用 `OKAY` 和 `EXOKAY`；
- 同 ID exclusive write 等到 exclusive read 完成；
- read/write 的地址、ID、region、length、size、burst、lock、cache 和 protection 属性匹配；
- 只有匹配 reservation 的 exclusive write 才可能收到 `EXOKAY`；该 write 也可以因外部冲突返回 `OKAY`；
- exclusive read completion 到匹配 AW 之间记录 causal edge。

其他 manager 经由另一条 link 写入同一位置时，reservation 应当失效。单 link trace 没有这部分可见性，
因此它属于 memory/interconnect VirtualDut 或 SystemProtocol 的后续组合语义。局部 monitor 给出
`EXOKAY` 的必要条件，不单独判断全系统条件是否充分。

## Outstanding capacity 的层级

基础 AXI4 LinkProtocol 负责定义资源的生命周期，例如 AR 接受时建立 read token、RLAST 接受时释放，
以及 AW/W join 后建立 B completion。它不为所有 AXI 实例选择一个固定队列深度。

当前 `ResourceDecl` 已显式记录 `acquired_by` 和 `released_by`，并随 protocol record 投影到运行产物。
AXI4 声明了 pending read、partial W assembly、pending AW descriptor、pre-AW complete W burst、
pending B completion 和 exclusive reservation。基础定义中这些 resource 的 `capacity=None`，表示
生命周期可见但没有替具体 DUT 选择容量。

需要有界 link profile 时，可调用 `base.with_resource_capacities(profile_name, capacities)` 收紧一个或
多个已声明资源。该接口只接受有 executable usage provider 的资源；`LinkSession` 在事件提交前检查
候选状态，超限时拒绝该事件并回滚。基础 AXI4 仍保持无界，不替具体端点选择默认深度。

| 内容 | 所属层级 |
|---|---|
| pending read/write/completion/reservation 的建立与释放 | AXI4 LinkProtocol |
| manager 最大发起数、subordinate 接受深度、exclusive monitor slots | VirtualDut port capability |
| bridge 的 AW/W correlation、ID remap 和跨端口 buffer | bridge VirtualDut internal resource |
| 多端口共享 buffer、路由占用和 wait-for cycle | SystemProtocol |
| 为场景主动限制同时请求数 | generation policy |

因此 VirtualDut 的协议入口后续适合使用 AXI 本地 typed port configuration，而不是继续扩展无类型
`capabilities` 字典。manager 至少区分 read/write issue depth；subordinate 至少区分 read acceptance、
write acceptance、write-data buffering 和 exclusive-monitor capacity。bridge 还需要内部 correlation/
translation entries，这些不应压缩成一个笼统的 `queue_depth`。

当前 canonical LinkSession 用 fault 表达容量超限。若某个 VirtualDut 把容量可用性投影为 READY，才会
在 pin observation 上表现为 backpressure。deadlock 判断还需要 SystemProtocol 中的 wait-for edge；
一个资源达到上限本身只说明局部阻塞条件。
