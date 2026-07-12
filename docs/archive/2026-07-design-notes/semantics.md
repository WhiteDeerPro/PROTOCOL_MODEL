# 形式语义草案

> 代码对应关系：事件与状态机抽象位于 `core/`，运行时组合位于 `engine/`，资源与义务位于 `semantics/`，具体握手机制位于 `patterns/`，公共有限偏序位于 `relations.py`。完整映射见 [代码地图](code_map.md)。

本文档定义 Protocol Model 的**目标语义边界**，不表示列出的结构都已实现。当前实现状态和理论缺口见 [理论审计](theory_audit.md)。目标不是建立覆盖所有协议的最终理论，而是提供一套足够小、可实现、可测试的公共模型。

## 1. 事件

事件是一次不可再分的协议观察：

\[
e=(id, kind, key, payload, source, clock, timestamp, sequence)
\]

字段含义：

| 字段 | 含义 |
|---|---|
| `id` | 事件实例的全局唯一标识 |
| `kind` | 事件类型，如 `REQ`、`ACK`、`AW`、`TRANSFER` |
| `key` | 用于事务匹配的复合键，如 `(channel, transaction_id)` |
| `payload` | 数据、地址、状态码及其他属性 |
| `source` | 生成该事件的 monitor 或接口 |
| `clock` | 所属时钟域或逻辑时钟域 |
| `timestamp` | 本地物理时间、周期号或逻辑时间 |
| `sequence` | 同一 source 内严格递增的观察序号 |

同一种 `kind` 可以产生多个事件实例。约束默认作用于事件实例，而不是抽象标签本身。

## 2. 执行模型

一次有限协议执行表示为：

\[
T=(E, \prec, \lambda, I, \#, \rho)
\]

其中：

- `E` 是有限事件实例集合；
- `≺` 是严格偏序，表示 happens-before；
- `λ: E → Kind` 为事件赋予类型；
- `I ⊆ E × E` 是独立关系；
- `# ⊆ E × E` 是冲突关系；
- `ρ` 是数据、基数、时间和状态约束的集合。

严格偏序满足：

1. 反自反：不存在 `e ≺ e`；
2. 传递：若 `e1 ≺ e2` 且 `e2 ≺ e3`，则 `e1 ≺ e3`；
3. 因而不存在因果环。

两个事件在某次执行中不可比较，当且仅当：

\[
e_1 \nprec e_2 \land e_2 \nprec e_1
\]

不可比较表示当前执行没有建立二者的先后关系，但不自动证明二者独立。

## 3. 顺序、独立、并发与冲突

这四个概念必须分开：

### 3.1 必要顺序

`e1 ≺ e2` 表示任何合法线性化中 `e1` 都必须出现在 `e2` 前面。

### 3.2 独立

`e1 I e2` 表示二者交换顺序不会改变可观察协议语义。`I` 至少满足：

- 对称：`e1 I e2` 当且仅当 `e2 I e1`；
- 反自反：事件不与自身独立；
- 独立事件之间不存在必要因果边。

实际协议中的独立关系经常依赖实例数据：

```text
independent(e1, e2) :=
    disjoint(e1.resources, e2.resources)
    and not same_ordering_domain(e1, e2)
```

因此 DSL 既要支持静态的 kind-level 规则，也要为动态谓词保留接口。

### 3.3 并发

并发是一次执行中的结构性质，即两个事件在偏序中不可比较。它不等价于物理时间上同时发生。

### 3.4 冲突

`e1 # e2` 表示二者不能共同出现在同一个合法执行中，例如同一次请求的成功响应与错误响应。冲突关系是对称且反自反的。

## 4. 线性观察与迹

monitor 通常产生一个线性日志：

\[
w=e_1e_2\ldots e_n
\]

它只是底层偏序执行的一种线性化。若两个相邻事件独立，则允许交换：

\[
x e_1 e_2 y \equiv_I x e_2 e_1 y
\]

反复应用这种交换得到的等价类称为一个 trace。验证结果应针对该等价类保持不变，而不是偶然依赖某一种线程调度顺序。

计划中的核心性质测试为（当前尚未实现 independence relation）：

```text
if independent(e_i, e_(i+1)):
    verdict(trace) == verdict(swap(trace, i, i+1))
```

## 5. 规则类型

### 5.1 前驱规则

```text
precedence(C, B, match_by=key)
```

含义是每个 `B(k)` 必须存在匹配的 `C(k)`，并且 `C(k) ≺ B(k)`。

### 5.2 后继义务

```text
response(C, B, min=1, max=1)
```

`C(k)` 创建一个义务，需要匹配规定数量的 `B(k)`。在有限 trace 中，未完成义务只有在以下条件之一成立时才能判错：

- trace 已明确结束；
- 超过规定 deadline；
- 后续状态使义务不可能完成。

### 5.3 数据关系

```text
payload(B).data == transform(payload(C).data)
```

数据规则应用在已经建立匹配关系的事件对或事件组上。

### 5.4 时间约束

```text
min_delay <= time(B) - time(C) <= max_delay
```

只有当两个时间戳属于同一可比较时间域，或存在可靠的跨域转换时，才能直接相减。异步域应使用逻辑边界、同步事件或区间估计。

### 5.5 状态和守卫

状态规则描述事件是否在当前协议阶段可接受：

```text
state == OPEN and event == CLOSE  -> state' = CLOSED
state == CLOSED and event == DATA -> fail
```

偏序描述事件之间的因果结构，状态机描述历史压缩后的控制状态；二者互补。

### 5.6 容量与资源

token 或计数约束用于描述 outstanding transaction、credit 和 FIFO 容量：

```text
on REQUEST: outstanding += 1
on RESPONSE: outstanding -= 1
invariant: 0 <= outstanding <= capacity
```

这类规则未来可以映射到 Petri 网语义。

### 5.7 时钟信号监控自动机

逐周期信号不是偏序事件本身。对 ready/valid channel，先用确定性 Mealy
转导器把输入样本串映射为规范 transfer 事件串：

\[
M=(S,\Sigma,\Gamma,\delta,\omega,s_0)
\]

- `Σ`：每个上升沿的 `(cycle, VALID, READY, event)`；
- `S`：`Idle` 或 `Stalled(saved_event, since)`；
- `Γ`：零个或一个规范 transfer event；
- `δ`：更新 stall 状态；
- `ω`：当且仅当 `VALID ∧ READY` 时输出 transfer。

安全规则为：

\[
G((VALID \land \neg READY) \rightarrow
X(VALID \land stable(event)))
\]

代码不实现通用无限 LTL 判定，而是将这条有限迹 safety property 编译成
`ClockedReadyValid` monitor automaton。撤销 VALID 或改变 payload 会立即 `FAIL`；
trace 在 stall 中结束时返回 `INCONCLUSIVE`，因为未来仍可能合法完成。

monitor 输出的 transfer 才进入 obligation、Petri token 和偏序层。这样物理采样顺序
与协议事务因果关系不会混为一个对象。

### 5.8 时序约束的分层

字段schema不是时序。通信协议时序从逐时钟观察的monitor automaton开始：

```text
L0 shape/value constraints       非时序
L1 clocked temporal safety       handshake、phase、stall、reset
L2 transaction causality         request→response、join、ordering
L3 concurrent step/pomset        同周期与独立交换
L4 quantitative temporal rule    deadline、timeout、fairness
```

AXI当前实现到L3，但没有协议外强加最大响应周期。APB的SETUP→ACCESS和wait-state属于L1；
PREADY可以添加任意数量等待周期，因此也没有协议固定deadline。

## 6. 三值判定

在线引擎对一条尚未结束的 trace 返回：

| 判定 | 含义 |
|---|---|
| `PASS` | 当前前缀合法；不承诺未来仍合法 |
| `FAIL` | 已存在任何未来事件都无法修复的违规 |
| `INCONCLUSIVE` | 尚有义务或跨源顺序等待确认 |

例如：

- `B(k)` 已确定早于任何可能匹配的 `C(k)`：`FAIL`；
- 已观察 `C(k)`，尚未观察 `B(k)`，也未超时：`INCONCLUSIVE`；
- trace 结束且所有义务完成：`PASS`；
- trace 结束仍存在 pending response：`FAIL`。

## 7. 多观测源

不同 monitor 的 callback 到达 scoreboard 的顺序，不自动构成协议事件的 happens-before。每个 source 必须至少提供单调 `sequence`。

跨 source 判定可以采用：

1. 明确的 send/receive 因果边；
2. watermark：声明某一逻辑时间以前不会再出现新事件；
3. 向量时钟或其他逻辑时钟；
4. 受控的合并采样点；
5. 在无法确认前保持 `INCONCLUSIVE`。

如果没有这些信息，引擎必须承认顺序不可判定，不能用软件线程调度补造因果关系。

## 8. 错误 witness

每次失败至少报告：

```text
rule_id
verdict
primary_event
related_events
missing_or_violated_relation
source_positions
human_readable_reason
```

理想情况下只显示证明该错误所需的最小事件子图。例如 `B(k)` 缺少前驱时，不应输出完整仿真日志。

## 9. 第一版非目标

- 完整支持 AXI、PCIe 或 TCP/IP；
- 自动从自然语言推导正确协议模型；
- 证明无限时间上的无条件 liveness；
- 用一个数学结构替代所有状态机、数据模型和时间模型；
- 直接依赖 UVM callback 顺序恢复异步因果关系。

这些边界用于保持第一版内核可实现、可测试。
