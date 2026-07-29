# 容量、接纳与背压

[返回架构索引](README.md) · [术语表](terminology.md) · [VirtualDut](virtual-dut.md) ·
[SystemProtocol](system-protocol.md) · [当前实现状态](implementation-status.md)

有限 FIFO、outstanding table、owner table 和 completion slot 共同形成一条运行链：

```text
capacity declaration
        │
        ▼
admission decision ──► accepted transition / BLOCK / ERROR_COMPLETION / FAULT
        │                                      │
        │                                      ▼
        │                              typed ResourceDemand
        │                                      │
        ▼                                      ▼
resource ownership and release ──► retry / wakeup / recovery
                                               │
                                               ▼
                                held/wait/release progress projection
```

这条链把“动作是否合法”和“module 此刻能否取得资源”分开，同时为 event generation、参考执行和
wait-for/deadlock 分析保留同一种证据。

## 1. 核心事实与 owner

| 事实 | 含义 | 声明 owner | 运行状态与更新 owner |
|---|---|---|---|
| capacity declaration | 某类资源可同时持有多少条目 | profile、backend contract 或 boundary contract | immutable configuration |
| occupancy / available | 已占用量与当前可分配量 | capacity lifecycle | 持有 acquire/release 生命周期的 backend/controller |
| protocol credit/window/READY | 对端可观察的接纳许可 | InterfaceProtocol 或 transport contract | 对应 protocol/transport session |
| capacity lease | 某个 token 对本地 slot 的占用 | resource contract | capacity pool；completion/cancel/reset 时释放 |
| obligation / outstanding | 已接纳、仍待完成的语义工作 | protocol/translation lifecycle | monitor、executor 或 owner ledger |
| backpressure / `BLOCK` | 当前边界暂缓接纳动作 | exhaustion policy | admission owner 产生 `ResourceDemand` |
| error completion | 已接纳工作以普通协议错误结束 | protocol + backend policy | completion queue、correlation 和 ordering owner |
| fault | 构造、调用或模型不变量被违反 | component contract | `SemanticFault` 与 owning component 的 fault atomicity |
| progress projection | held、wait、release 与可恢复条件 | boundary/system contract | runtime projection + SystemProtocol analysis |

capacity 和 available 描述数量；条目的 key、acquire、release、reset 与 ordering 决定生命周期。同一个
数字深度可以支持 backpressure、错误完成或丢弃等不同公开行为，因此容量与耗尽策略需要一起声明。

## 2. Capacity declaration

### 2.1 一份完整容量声明

每项有限资源至少说明：

| 字段 | 回答的问题 |
|---|---|
| name、scope、location | 哪个 module/port/controller 拥有资源 |
| unit 与 capacity | 条目计数的对象和上限 |
| key / owner | 哪个 token、ID、port 或 transaction 占用条目 |
| acquire condition | 动作在哪个接纳点取得资源 |
| release condition | 哪个 completion、cancel、drain 或 reset 释放资源 |
| ordering / release mode | FIFO、keyed、乱序或批量释放规则 |
| exhaustion policy | `BLOCK`、`ERROR_COMPLETION`、`FAULT` 或 backend-local drop policy |
| boundary projection | 对系统公开的 capacity、usage、held 和 demand |

`ResourceDecl` 是声明投影，真实 occupancy 继续由生命周期 controller 持有。以 bridge 为例，以下资源分别
计数：

| 资源 | 典型 key | acquire | release |
|---|---|---|---|
| input assembly | port + descriptor/ID | 接纳 partial request/data | decode/join complete、cancel、reset |
| parent queue | parent token | operation 被 bridge 接纳 | parent completion/cancel |
| downstream outstanding | egress + child token/ID | child issue | child completion/cancel |
| completion storage | ingress + response class/ID | result 准备返回 | 上游接纳 completion |
| return-owner table | egress/ID/child | identity remap 或 route commit | 最后一笔相关 completion |

这些资源可以互相依赖，同时保持独立的容量、owner 和释放条件。

### 2.2 耗尽政策

| 结果或政策 | 动作是否接纳 | 状态与 side effect | 对外结果 | 典型合同 |
|---|---:|---|---|---|
| `BLOCK` | 否 | admission scope 保持原状态，emissions 为空 | typed `ResourceDemand` | 支持 flow control 的接收端 |
| `ERROR_COMPLETION` | 是 | 取得请求所有权并更新 ordering/correlation | 普通协议错误完成，可立即或延后发送 | 明确承诺容量错误响应的设备 |
| `FAULT` | —（模型/使用合同路径） | 遵循 owning component 的 fault atomicity | `SemanticFault` | 配置、调用范围或模型不变量被违反 |
| `DROP_NEWEST` | 采样机会已发生 | 保留旧数据，更新 service/overrun 状态 | backend-local overrun evidence | 固定速率、不可回压的数据源 |

`DROP_NEWEST` 是具体 backend 的生产策略。其他 overwrite、coalesce 或 sample-and-hold 行为也需要各自的
设备合同和可观察状态。

## 3. Admission decision

### 3.1 接纳与所有权转移

接纳表示 module 已取得动作所有权。接纳流程先检查完成该边界原子转移所需的资源，再提交状态：

```text
action + current state
        │
        ├─ resources reserved
        │      └─ accepted state + obligations + possible emissions
        │
        ├─ retryable shortage
        │      └─ original state + ResourceDemand
        │
        ├─ accepted error policy
        │      └─ ordered completion lifecycle
        │
        └─ contract violation
               └─ SemanticFault
```

`BLOCK` 的可重试语义要求该 admission scope 保持 state-neutral 和 emission-free。已经向外部产生 side
effect 的动作继续按 accepted lifecycle 处理；它可以等待 completion、进入 partial-failure policy，或拆成
具有独立接纳点的子动作。

一次动作跨越多个 egress 时，可以通过全量预留、分阶段 admission、独立 emission commit 或 deferred
scheduling 定义原子边界。实现选择必须让调用方看到的 `BLOCK` 与实际 side effect 一致。当前 runtime
采用的回滚粒度与多出口限制集中记录在[实现状态](implementation-status.md)。

### 3.2 `ERROR_COMPLETION` 也需要资源

`ERROR_COMPLETION` 同时表达“请求已接纳”和“工作以协议错误结束”。错误结果进入正常 correlation、
ordering 和 response handshake 生命周期：

| 阶段 | 所需资源 |
|---|---|
| 接纳请求 | request/parent slot 或等价 ownership record |
| 形成错误结果 | completion origin、response code 和 reply context |
| 保持顺序 | marker、ID/port ordering queue 或 owner table |
| 发出响应 | response FIFO、arbiter、return path credit/READY |
| 退休 | 上游接纳 completion 后释放相关 lease/obligation |

构造者在接纳前为错误 completion 预留资源，或声明有界 deferred marker 机制。返回路径拥塞时，该
completion 仍可能等待 response FIFO、arbiter、credit、owner table 或上游 READY。

### 3.3 Event admission 与 pin-level backpressure

| 边界 | 输入与输出 | Owner |
|---|---|---|
| event admission | action → accepted transition 或 `ResourceDemand` | VirtualDut/backend |
| offer ownership | selected event 在 handshake 前保持稳定 | scheduler/driver state |
| AXI/AHB/APB pin lowering | `READY`、`HREADY`、`PREADY` 与 phase/reset 规则 | protocol-specific driver |
| pin observation | 核对 VALID/payload stability、transfer phase 和 reset | protocol-specific observer |

event-level `BLOCK` 为 driver 提供背压依据。周期级 lowering 继续处理通道独立性、payload 稳定、phase 和
reset；一次 service/advance 与一个 clock cycle 的对应关系由 scenario/driver profile 明确声明。

### 3.4 不可回压来源

固定采样率 ADC 等物理源会消费每次采样机会。FIFO 满时，`DROP_NEWEST` 保留已有样本、推进
`service_index`、增加 `overrun_count`；软件或 notification attachment 可以观察 overrun。

能够门控或暂停的 producer 可以采用 `BLOCK`，此时被拒绝的 service action 保持采样序列位置。profile
需要说明这种暂停来自真实流控、时钟门控，还是验证环境的理想化控制。`ERROR_COMPLETION` 可以报告一次
已接纳访问的失败，已经错过的物理样本则由 overrun/drop 语义记录。

## 4. Blocked reason 与 ResourceDemand

### 4.1 Typed demand

`ResourceDemand` 记录一次 retryable shortage：

| 当前字段 | 证据内容 |
|---|---|
| resource / scope | 等待的资源及其最小判定范围 |
| required / available / capacity | 当前缺口与配置上限 |
| location | module、port、queue 或 controller |
| reason | backend 给出的 typed explanation |

surrounding action/session 提供 requester identity，boundary progress projection 再关联 holder、unblock
condition 和 provenance。这样，typed demand 可以从“当前未接纳”继续连接到“谁在等什么、由谁释放、
何时值得重试”。

### 4.2 Recovery path

```text
BLOCK + ResourceDemand
          │
          ▼
held resource changes / completion retires / environment progresses
          │
          ▼
unblock condition becomes true
          │
          ▼
scheduler or scenario retries the original action
          │
          ├─ accepted
          └─ new typed demand
```

boundary projection 可以报告 wakeup candidate；scheduler、driver 或 scenario 决定重试时机。wakeup evidence
说明某项已知 blocker 发生变化，新的 admission decision 再确定动作是否接纳。

## 5. Recovery 与 progress projection

### 5.1 从局部 demand 到 wait-for

SystemProtocol 的 progress projection 需要以下事实：

| 投影 | 作用 |
|---|---|
| held resource / lease | 谁占有当前有限资源 |
| waiting `ResourceDemand` | 谁等待哪个资源或外部条件 |
| outstanding obligation | 哪项已接纳工作仍待完成 |
| release transition | 哪个 completion/cancel/drain 可以释放资源 |
| return/completion storage | 进度路径本身还需要哪些资源 |
| route/topology ownership | demand 与 holder 通过哪些 module/connection 关联 |
| environment/fairness assumptions | arbiter、producer、consumer 提供何种进度 |

这些投影形成资源依赖关系：

```text
transaction/DUT A waits for resource R
resource R is held by transaction/DUT B
DUT B waits for completion/path/resource S
```

### 5.2 证据强度

| 观察 | 可以形成的结论 | 还需补充的证据 |
|---|---|---|
| 一次有限时长 `BLOCK` | 当前存在背压 | release、retry 与后续 trace |
| waiter→resource→holder | 一条 wait-for path | holder 的后续等待或释放 |
| wait-for cycle | 候选循环依赖 | escape transition、cancel/timeout、环境进度 |
| cycle 且无可行 escape | deadlock witness 候选 | 适用的公平性与环境假设 |
| 某请求长期得不到选择 | starvation 候选 | 其他事务进展与 arbiter fairness |
| 状态持续变化而 obligation 反复不完成 | livelock 候选 | 重试 lineage 与无完成证据 |

deadlock verdict 需要 held、wait、release、escape 和 fairness 的闭合证据。`ERROR_COMPLETION` 只能关闭相应
obligation；response FIFO、arbiter、credit、owner table 和上游 READY 仍属于返回路径依赖。

### 5.3 AXI 中的三个判定范围

| 判定范围 | 关键事实 | Owner / 证据 |
|---|---|---|
| 单接口与跨通道 | source 独立于 READY 产生 VALID；receiver 可以根据 VALID 产生 READY；B eligibility 由 AW 与最后一笔 W transfer 打开；BVALID/RVALID 的产生独立于 BREADY/RREADY | pin/cycle observer + InterfaceProtocol lifecycle；[Arm AMBA AXI Protocol Specification, Issue L](https://documentation-service.arm.com/static/68b03beb01ae952d9559f9eb) |
| 单个 bridge/interconnect | AW/W route ownership、ID/order table、response slot、burst child 与 downstream FIFO 的局部依赖 | VirtualDut admission、held resource、completion policy |
| 跨节点网络 | 多 source/target、同 ID ordering、return path 和 arbitration 的组合依赖 | SystemProtocol topology + wait-for analysis；[How Deadlock Occurs](https://docs.amd.com/r/en-US/pg059-axi-interconnect/How-Deadlock-Occurs)、[Single Slave Per ID](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Avoiding-Deadlock-Using-Single-Slave-Per-ID) |

物理 ring/mesh 形状只提供 topology；deadlock 判定使用逻辑资源依赖图。virtual channel、独立
request/response class 和不同物理路径可以提供 escape，endpoint 之间的相互等待仍需系统合同检查。相关
NoC 保证范围见 [NoC Deadlock Avoidance](https://docs.amd.com/r/en-US/pg313-network-on-chip/NoC-Deadlock-Avoidance)。

### 5.4 层级责任交接

| 层级 | 容量与进度职责 |
|---|---|
| 基础语义 | 声明 `ResourceDemand`、`ResourceExhaustionPolicy` 和 blocked transition 不变量 |
| InterfaceProtocol | 定义 response kind、correlation、ordering、outstanding 与 protocol credit |
| VirtualDut/backend | 持有 FIFO/table occupancy，执行 admission、drop、error 或 fault policy |
| attachment/integration | 把 operation result 编码为 AXI/AHB/APB completion |
| System runtime | 传播 accepted event，定位 blocked demand，并执行已声明的 step atomicity |
| System analysis | 消费 blocked、held lease、obligation、release 和 topology，形成 progress verdict |
| observation/driver | 在 event admission 与协议 pin/cycle backpressure 之间 lowering |
| scenario/project | 选择 producer rate、service schedule、retry 和 fairness assumptions |

例如，“AXI requester 支持 16 笔 outstanding”涉及三个 owner：端口 capability/profile 声明合同上限，
backend state 记录实际占用，system/scenario property 判断这些 transaction 是否最终完成。

## 6. 不可回压 Sensor 示例

一个固定速率 sensor、consumer/DMA、interconnect 和 memory 可以同时出现多种容量行为：

| 条件 | 合同结果 | 保留的证据 |
|---|---|---|
| sensor 产生速度高于消费速度 | `DROP_NEWEST` | 旧样本、`service_index`、`overrun_count` |
| consumer 读取空 sensor FIFO | `BLOCK` 或具名 access error policy | demand 或普通错误 completion |
| interconnect/memory ingress 已满 | `BLOCK` | 具体 queue 的 `ResourceDemand` |
| overrun 需要异步通知 | notification/interrupt attachment | notification queue、active slot、completion/EOI obligation |

notification 路径也声明自己的 capacity、owner 和 completion resources。这样，物理 sample loss、软件可见
overrun、总线 backpressure 和 interrupt lifecycle 各自保留 owner。

## 7. 当前覆盖入口

当前覆盖与缺口由[实现状态](implementation-status.md)中的 `bounded capacity`、`blocked rollback
granularity`、`wait-for/deadlock`、`DUT 延后 emission` 和 `sensor/DMA scenario` 条目统一维护；后续
boundary projection、scheduler 与 progress analysis 的工作顺序见
[技术路线](technical-route/08-roadmap.md)。本页维护稳定语义和 owner 分工。
