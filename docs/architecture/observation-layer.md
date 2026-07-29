# Observation 层与采样边界

Observation 层把外部 pin/cycle trace 解释为 canonical interface event，同时保存解释所需的时间结构：

```text
clocked pins ──► AtomicFrame(clock, tick) ──► ready-valid/APB/AXI observer ──┐
                                                                           ├─► CanonicalEvent(s) ──► InterfaceSession
async pins ───► AsynchronousSample(order) ──► four-phase observer ──────────┘
```

这些 Python 对象实现工程中的采样边界。`AtomicFrame` 拥有一个 clock edge 上的同时性；
`AsynchronousSample` 拥有 edge-complete observation order，适用于 REQ 与 ACK 分属不同采样 clock 的来源。
保留这些结构后，后续模型可以区分文件记录顺序、协议因果顺序、同周期事件和跨域来源。

## 1. 采样对象与事实 owner

### 1.1 `AtomicFrame`

`AtomicFrame` 保存一个 clock、一个 tick，以及该采样点上的具名 observations。它拥有“同时被观察到”
这一结构事实。

当前结构约束包括：

- tick 是非负整数；
- clock 和 observation 名称有效；
- observations 在 frame 建立后不可变。

具体 observer 继续判定 tick 连续性、lane 类型和信号协议。

### 1.2 `ReadyValidObserver`

`ReadyValidObserver` 拥有 ready-valid 编码到 canonical event 的解释。当前 observer：

- 检查 frame clock、tick 顺序和 lane 类型；
- 在 `VALID=1` 时要求存在满足 `EventSchema` 的 canonical event；
- 在 stalled offer 期间检查 VALID 和 payload 稳定；
- 在 `VALID && READY` 时发出带 clock/timestamp/source 的 `CanonicalEvent`。

它同时提供 `SemanticFragment` 形式的约束声明，便于报告和后续组合；observer 状态机负责执行判定。

### 1.3 `AsynchronousSample` 与 `FourPhaseObserver`

`AsynchronousSample` 使用严格递增的 sequence 作为观察顺序，并可携带 trace source 提供的 timestamp；
它采用 clock-free sample 形式。`FourPhaseObserver` 在这条序列上检查 active-high REQ/ACK 的
`00 → 10 → 11 → 01 → 00` 次序，并在 ACK 上升时发出一次 accepted event。输入来源需要保证所有相关
transition 都可见。同步器结构、亚稳态和 bundled-data 物理裕量由 CDC/STA 工具或更具体的 physical
profile 处理。完整边界见[异步 REQ/ACK 握手](asynchronous-handshake.md)。

### 1.4 `ResetEpochObserver`

reset 是 observation component 的组合器。它读取 frame 内已经归一化的 bool reset lane：reset asserted
时检查可选 inactive policy、清空 inner observer state，并递增 epoch；deasserted 时继续执行 inner
observer。它当前负责 interface-local reset observation；system elaboration 负责 DUT reset、多个
clock/reset domain 和跨 connection reset 传播。

外部 observation 路径当前在 InterfaceSession 完成接口局部判定。构造系统路径则由 `SystemAction` 进入
SystemSession，再使用每条 connection 的 InterfaceSession。两条路径共享 canonical event 语义；统一
boundary runtime 的自动串接属于后续实现。

## 2. 批处理与原子性范围

`AtomicFrame` 保存同周期信息，具体 observer 与 monitor 定义同周期事务语义。多个 observer 可以从一个
frame 发出多个 canonical events；`InterfaceSession.step_batch()` 会先在候选状态上执行整批事件，全部
接受后才提交。AXI observer 当前采用 `B, R, W, AW, AR` 的协议本地 lowering 顺序，因此 AW/W 同周期
行为由该顺序和 monitor 共同解释。其他 channel 的交换性由各自协议明确声明。

这一批处理原子性覆盖一条 interface connection 上的一批 canonical events。`SystemSession` 处理一次
action 引发的多连接立即 emission；当前跨连接 cascade 采用逐跳提交，后续 hop 失败会保留此前已经接受的
提交。跨 connection 的全局事务原子性需要由明确的 SystemProtocol 语义定义。

`AtomicFrame` 因而是 observation 层的输入边界，负责保存时间结构。ReadyValidObserver、
InterfaceProtocol monitor 和 SystemProtocol 分别在各自作用域内提供协议约束。
