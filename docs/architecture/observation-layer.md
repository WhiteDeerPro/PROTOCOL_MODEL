# Observation 层与 AtomicFrame

Observation 层位于外部 pin/cycle trace 与 canonical link event 之间：

```text
raw pins / sampled interface
            │ normalize
            ▼
AtomicFrame(clock, tick, named observations)
            │ ReadyValidObserver / ResetEpochObserver
            ▼
CanonicalEvent(s)
            │
            ▼
        LinkSession
```

这是一项工程分层选择，不是 ready-valid 或 AXI 规范规定必须存在名为 `AtomicFrame` 的对象。
需要这个边界的原因是：同一个采样沿可能同时观察到多个通道和 reset。如果先把它们任意排列成
单个 event，后续模型可能把记录顺序误认为协议因果顺序。

## 各层负责什么

### `AtomicFrame`

`AtomicFrame` 只表达结构事实：一个 clock、一个 tick，以及该采样点上的具名 observations。
它保留“同时被观察到”这一信息，不判断 ready-valid、reset 或事务行为是否合法。

当前结构约束包括：

- tick 是非负整数；
- clock 和 observation 名称有效；
- observations 在 frame 建立后不可变。

tick 是否连续、lane 类型是否正确、信号是否遵守协议，由具体 observer 判定。

### `ReadyValidObserver`

ready-valid 属于 link 的 observation/encoding 层，而不是 canonical transaction 层。当前 observer：

- 检查 frame clock、tick 顺序和 lane 类型；
- 在 `VALID=1` 时要求存在满足 `EventSchema` 的 canonical event；
- 在 stalled offer 期间检查 VALID 和 payload 稳定；
- 在 `VALID && READY` 时发出带 clock/timestamp/source 的 `CanonicalEvent`。

它同时提供 `SemanticFragment` 形式的约束声明，便于报告和后续组合。执行判定仍由 observer 状态机完成。

### `ResetEpochObserver`

reset 是 observation component 的组合器。它读取 frame 内已经归一化的 bool reset lane：reset asserted
时检查可选 inactive policy、清空 inner observer state，并递增 epoch；deasserted 时继续执行 inner
observer。它当前适合 link-local reset observation。DUT reset、多个 clock/reset domain 和跨 link reset
传播仍需要 system elaboration 层的设计。

外部 observation 路径当前在 LinkSession 完成单 link 判定。构造系统路径则由 `SystemAction` 进入
SystemSession，再使用每条 link 的 LinkSession；两条路径共享 canonical event 语义，但尚未由统一 boundary
runtime 自动串接。

## AtomicFrame 的语义边界

保存同周期信息不等于已经定义同周期事务语义。多个 observer 可以从一个 frame 发出多个 canonical
events；`LinkSession.step_batch()` 会先在候选状态上执行整批事件，全部接受后才提交。AXI observer 当前
采用 `B, R, W, AW, AR` 的协议本地 lowering 顺序，因此 AW/W 同周期行为由该顺序和 monitor 共同解释，
不能把它泛化为所有 channel 可以任意交换。

这个原子边界只覆盖一条 link 上的一批 canonical events。`SystemSession` 处理一次 action 引发的多跳
立即 emission，但后续某一跳失败时，当前不会把整条系统级 cascade 一并回滚；跨 link 的全局事务原子性
仍需由明确的 SystemProtocol 语义定义。

因此 AtomicFrame 是 observation 层的输入边界，不是用来“约束后面所有协议正确行为”的总规则。
它避免过早丢失时间结构，具体协议约束仍属于 ReadyValidObserver、LinkProtocol monitor 或
SystemProtocol 各自的作用域。
