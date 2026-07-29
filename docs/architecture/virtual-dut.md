# VirtualDut：module 边界、局部状态与协议接入

`VirtualDut` 是一个具体、具名、可连接的虚拟 module。本文沿以下主线定义它的 canonical 方法：

```text
module boundary
    → protocol-neutral operation
    → backend / unique state owner
    → attachment + port binding
    → opaque or constructed realization
    → SystemProtocol handoff
```

## 1. Module boundary

一个 `VirtualDut` 由稳定的外部身份与实现 binding 组成：

```text
VirtualDut
  name / identity
  typed InterfacePort / TransportPort
  boundary capability and contract
  backend binding
  optional typed projection
  optional nested SystemProtocol
```

端口声明 module 能接收和发出什么；backend 决定 module 收到输入后的状态变化与输出；typed projection 将
system closure 所需的稳定配置暴露到边界。

同一 boundary 支持三种 realization：

| Realization | 功能状态 owner | 边界可见深度 |
|---|---|---|
| external/RTL/RPC/trace | 外部 simulator、真实 DUT、oracle 或记录 | ports、capability、event、typed projection |
| constructed | 本项目装配的 backend state 与行为组件 | 可展开 attachment、FIFO/FSM、route、translation |
| composite | 内部 `SystemProtocol` | 对外 boundary ports；内部 topology 作为 subsystem |

external backend 通过 boundary contract 获得完整 `VirtualDut` 身份。状态枚举、checkpoint、snapshot 和 replay
由该 backend 的可选执行合同提供；普通在线验证可以直接使用 opaque state。

## 2. Protocol-neutral operation

module 行为先表达为协议中立的 operation 与局部转移：

```text
(local state, accepted operations, available resources)
    → (new state, emitted operations, resource changes)
```

一次转移说明：

- 原子消费和产生的 operation/token；
- transition guard 与接纳条件；
- resource acquire/release；
- request、completion、notification 的因果关系；
- reset、cancel、error 对未完成 lifecycle 的处理。

operation 的因果角色如下：

| 角色 | lifecycle 含义 |
|---|---|
| request/initiation | 建立 obligation |
| completion/response | 依赖并解除 obligation |
| notification | 将内部变化投影为新的外部可见事实 |
| acknowledgement | 接纳或关闭 notification |

`AddressAccess`、burst、stream transfer 和 notification 等 typed operation 让多个协议 attachment 复用同一
backend 语义。状态机是转移的执行模型；行为算子与 typed transition 是主要组合界面。

## 3. Backend 与唯一状态权威

backend 是 module 功能行为和动态状态的运行权威：

```text
opaque or typed state + accepted input
    → immediate / blocked / deferred transition result
```

一个 executable `VirtualDut` 向 runtime 提供一份组合后的动态 state。attachment state fragment、FIFO、
address space、route table、owner table、participant storage core 和 scheduler state 都在这份 state graph 中
各出现一次；projection、monitor ledger 和 visualization 使用只读视图或派生证据。

### 3.1 相邻对象的 owner

| 事实或职责 | owner |
|---|---|
| 完整逻辑接口的 role、event/channel schema、参数和合法性 | `InterfaceProtocol` |
| 每个 interface connection 的 correlation、ordering、outstanding | `InterfaceSession` |
| module 的 port、capability、domain 和公开 binding | `VirtualDut` boundary |
| event 与 protocol-neutral operation 的单端口转换 | `InterfaceAttachment` |
| attachment 实例到具体 port 的静态关联 | `InterfaceAttachmentBinding` |
| attachment 动态片段、功能状态、跨端口 correlation、route、service scheduling | `VirtualDut` backend state |
| canonical connections、system boundary、address/home/identity authority | `SystemProtocol` |
| resolved plan、system trace、跨节点 reference ledger 与 verdict | resolution、runtime、system monitor |
| stimulus choice、RNG、生成策略和 harness history | scenario controller |

SystemProtocol 只消费 `VirtualDut` 的公开端口、capability、event 和 typed projection。backend 私有状态保持
opaque，并由 backend 自身执行。

跨端口关系归 module backend。例如 AXI AW→W owner、bridge ID remap、crossbar response return、Home
directory 与 DMA requester/completer correlation 都随一份 module state 推进。跨多个具名 module 的
address reachability、end-to-end return、wait-for 和 coherence verdict 由 SystemProtocol 闭合。

### 3.2 Backend 形态

| Backend | 状态位置 | 典型用途 |
|---|---|---|
| external/RTL proxy | 外部 simulator 或真实 DUT | 被观察对象 |
| RPC/Python oracle | 外部程序或 reference model | 权威功能行为 |
| trace replay | 记录与 replay cursor | 可重复场景 |
| nondeterministic environment | runtime choice state | open-system 探索 |
| constructed backend | typed state 与行为组件 | traffic、memory、bridge、crossbar fixture |
| composite backend | 内部 `SystemProtocol` | 层次化封装 |

backend contract 同时区分 deterministic、seeded choice、replay 和 external oracle，并区分设备结果、资源阻塞、
协议 fault 与模型基础设施 fault。

## 4. Attachment 与 port binding

attachment 将 protocol-neutral operation 接到一份完整逻辑接口：

```text
backend operation / emission
        ↕ InterfaceAttachment
CanonicalEvent
        ↕ InterfaceProtocol
InterfacePort ── InterfaceConnection
```

| 对象 | 静态内容 | 动态内容 |
|---|---|---|
| `InterfacePort` | protocol、role、capability、clock/reset domain | 由 connection/session 持有 |
| `InterfaceAttachment` | operation family、event codec、初态与静止条件 | 绑定后嵌入 backend state |
| `InterfaceAttachmentBinding` | attachment instance 与 port 的关联 | 静态 immutable value |

`VirtualDutBuilder.bind_port()` 或 `.bind()` 完成 module 内部绑定；`InterfaceConnection` 随后把已声明端口连接成
一份具体 interface instance。attachment-aware backend 投影自己实际使用的 binding，`VirtualDut` construction
核对 projection 与公开 binding 的对象身份，从而让声明与执行共享同一配置。

具体协议转换位于 `protocol_model/integrations/`。例如 APB attachment 在 APB event 与 `AddressAccess` 之间
转换；APB `InterfaceProtocol` 继续只声明接口语言。attachment 依据稳定的 protocol family、role 和 interface
shape 选择匹配规则。

attachment 负责以下边界事实：

- event direction 与 channel/phase correlation；
- typed capability/profile；
- backend operation 与协议 transaction 的映射；
- AXI ID/burst/AW-W join、AHB phase context 等端口局部状态；

协议 observation/driver 负责 pin、cycle、UVM transaction 与 `CanonicalEvent` 之间的 lowering。
attachment 从已经形成的 canonical event 开始，执行 event↔operation 映射。

decode miss、只读写入等正常设备结果由 attachment 映射为协议响应，例如 AXI `DECERR/SLVERR`、AHB
`ERROR` 或 APB error。`SemanticFault` 用于接口合同、backend invariant 或模型基础设施的实际故障。

空 fixture 也使用同一边界：idle source 的端口事件来自 caller-owned stimulus；blackhole sink 接纳请求并让
obligation 保持未完成，可用于挂起和 deadlock 场景。正常 responder 则产生匹配的 completion。

## 5. Constructed realization

constructed realization 将 attachment、backend 与端口装配为最终 module：

```text
InterfacePort ↔ attachment codec ↔ backend
                                  ├─ FIFO / table / pool
                                  ├─ AddressSpace / handler
                                  ├─ route / arbiter / owner
                                  ├─ translation plan
                                  └─ requester / service controller
```

### 5.1 可复用行为构造

| 构造 | 关注内容 | 典型用途 |
|---|---|---|
| `Source/Choice` | 创建 token、脚本、随机或环境选择 | manager、traffic source |
| `Sink/Observe` | 消费、记录、断言或丢弃 token | monitor、scoreboard endpoint |
| `Transform` | map、filter、rewrite、split、merge | field/width behavior |
| `Store/Resource` | FIFO、table、pool、counter、register、reorder buffer | capacity、乱序、反馈环 |
| `Correlate/Join` | 按 FIFO、key 或 descriptor 归并 token | AW/W、request/response |
| `Route/Fork` | decode、owner return、multicast、分支 | decoder、crossbar、router |
| `Select/Arbitrate` | 从 enabled candidates 中选择 | fixed、round-robin、weighted |
| `Compose/Hide` | 连接组件、反馈、封装内部 token | bridge、DMA、复合 module |

表中的 `Transform` 是通用行为分解词汇。跨协议 bridge 使用 typed `TranslationStage/Plan` 声明 source/target
operation form、1→N cardinality、属性 policy 和 completion fold；executor 持有 scheduling、capacity lease
与 correlation。完整定义见[Bridge 与类型化事务转译](typed-transaction-translation.md)。

crossbar 的局部构造可以写成：

```text
request ports
    → Route(address)
    → per-target Store(FIFO)
    → Select(arbiter)
    → destination ports

response ports
    → Correlate(owner table)
    → Route(source port)
```

反馈环以显式 `Store`、token capacity 或时间延迟建立推进边界。每个 resource 都声明 acquire、release、
blocked reason 与 reset lifecycle。

### 5.2 构造顺序与深度

1. 选择验证目标和外部 ports。
2. 选择 external/oracle、constructed 或 composite backend。
3. 将本地行为分解为 typed operations、transitions 和 reusable components。
4. 为 Store、table、pool、owner 和 scheduler 建立唯一 state 与 lifecycle。
5. 用 Correlate、Route、Arbitrate 表达多 channel 和跨端口关系。
6. 用 attachment 将 operations 绑定到 ports。
7. 声明 boundary assumption、guarantee、capacity 和 typed projection。
8. 将最终 `VirtualDut` 交给 SystemProtocol construction。

| 深度 | 主要关注 | 示例 |
|---|---|---|
| C0 | external boundary | opaque RTL/RPC module |
| C1 | stateless transform | mapper、field converter |
| C2 | local state and capacity | FIFO、register、ID pool |
| C3 | correlation、route、arbitration | bridge、crossbar |
| C4 | autonomous progress、multi-port obligation | DMA、cache controller fixture |
| C5 | deferred emission、time、clock domain | timer、CDC、async FIFO |

深度描述当前验证目标展开到的位置。同一个 DMA 可以用 C0 external boundary 接入，也可以按需构造成 C2–C5
reference fixture。

### 5.3 可视化

opaque view 显示 ports、capability 和 external boundary；constructed view 可展开 binding、attachment、
FIFO/FSM、translation stage、owner table 与 address handler。projector 为已知 backend family 提供显式
adapter，并将其他 backend 保留为 opaque node。

连接与运行视图示例见
[APB4 queued responder](../../showcase/generated/vdut/apb4-queued-responder/README.md)。

## 6. SystemProtocol handoff

最终 `VirtualDut` 作为 canonical topology 中的一个 module 节点交给 `SystemProtocol`：

```text
VirtualDut boundary
  ├─ InterfacePort ───────► InterfaceConnection
  ├─ TransportPort ───────► DirectedTransportConnection
  ├─ capability/projection ─► system contracts / resolution
  └─ emitted events ──────► runtime / monitor / analysis
```

SystemProtocol 承接：

- topology 与 connection ownership；
- address/home/identity/domain authority 和 reachability；
- capability 与 boundary projection closure；
- 跨 connection request owner、ID mapping 与 response return；
- network resource projection、wait-for、deadlock、fairness 与 QoS；
- internal connection/hop hide 与 boundary refinement。

`SystemProtocol.connections` 是 connection topology 的唯一权威。resolved plan、visualization 和 analysis graph
都是它的只读投影。

一个物理 crossbar 通常作为单个 multi-port `VirtualDut`，其 backend 持有 route、FIFO、arbiter 和 owner
state。验证目标需要观察内部 module/connection/hop 时，可将其展开为内部 `SystemProtocol`，再通过
`as_virtual_dut()` 封装回相同 boundary；boundary refinement 比较两种 realization 的外部 trace。

## 7. 源码职责与实现索引

`protocol_model/virtual_dut/` 按 module 内部职责组织：

| 包 | 职责 |
|---|---|
| `boundary/` | module、interface port、transport port 与外部 identity |
| `binding/` | port、attachment 与 module 的静态装配 |
| `attachments/` | protocol-neutral 单端口 operation SPI |
| `backend/` | state transition、显式 advance 与 constructed behavior foundation |
| `address/` | `AddressAccess`/burst、`AddressSpace` 与 reference region |
| `fabric/` | route、arbitrate、owner 与 multi-port backend |
| `translation/` | typed stage/plan、resource ledger 与 bridge backend |
| `recipes/` | protocol-neutral final assembly |

协议专用 attachment 和成品 recipe 位于 `protocol_model/integrations/`：

| 包 | 职责 |
|---|---|
| `attachments/<family>/` | family event ↔ protocol-neutral operation |
| `recipes/catalog/` | factory metadata 与公共 construction lookup |
| `recipes/<family>/endpoints/` | 具名 endpoint products |
| `recipes/<family>/fabrics/` | same-family multi-port products |
| `recipes/<family>/bridges/` | cross-port translation/correlation/completion products |

依赖方向沿叶模块到最终装配展开：attachment 消费单端口 operation SPI；fabric 组合 backend foundation；
recipe 组合 port、attachment 和 backend；SystemProtocol 消费 boundary/transition 与最终 `VirtualDut`。
catalog 保存 factory 描述，具名实例由 system construction、scenario 或调用方 project 创建。

当前 constructed witnesses 包括 Sensor FIFO、descriptor DMA、notification/EOI、AMBA endpoints/fabrics/bridges
和 CHI participant storage。它们分别覆盖数据源、主动搬运、控制通知、地址服务、跨端口 correlation 与
coherence state；具体 profile、限制和测试证据统一见[实现状态](implementation-status.md)。CHI storage core
在 participant state 中嵌入一次，同 module 的多 facet 继续共享一份动态 state。canonical Home composition
选择 participant-owned state graph；额外 executable backend 通过共享 state runtime contract 或显式
topology-visible HN→SN transaction 接入。

相邻文档：

- [VirtualDut 源码导航](../../protocol_model/virtual_dut/README.md)
- [Integration recipes 导航](../../protocol_model/integrations/recipes/README.md)
- [InterfaceProtocol、VirtualDut 与 SystemProtocol](system-protocol.md)
- [容量、接纳与背压](capacity-admission-and-backpressure.md)
- [Bridge 与类型化事务转译](typed-transaction-translation.md)
- [事务转译 V1 实施状态](translation-implementation.md)
