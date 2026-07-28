# 架构文档索引

架构文档用于建立可独立阅读的概念体系，而不是保存讨论时间线。每个核心概念由一篇 canonical 文档负责
完整定义；技术路线负责导读，协议专题负责具体化，状态页负责说明当前实现。

若当前问题是“这段实现应放在哪个源码包”，先看
[`protocol_model` 源码导航](../../protocol_model/README.md)；本目录继续负责概念、机制与设计理由，不复制文件清单。

## 1. 概念依赖关系

```text
CanonicalEvent / Constraint / Resource / Obligation
      ├── Pattern ───────────────► InterfaceProtocol
      ├── typed forms ───────────► TranslationStage / representation codec
      └── behavior primitives ───► VirtualDut backend

InterfaceProtocol + attachment + backend ──► concrete VirtualDut
VirtualDuts + Interface/DirectedTransport connections + system contracts ──► SystemProtocol
packet/flit forms + resolved hops + family runtime ──────► transport-network execution view

Observation / Session / Trace / Artifact 横向服务上述对象
```

箭头只表示构造或解释依赖，不表示协议栈层级或运行时必经顺序。InterfaceProtocol 与 VirtualDut 行为分别
构造，在 attachment/binding 处汇合；SystemProtocol 扩大判定范围，但不读取 attachment 私有状态。完整的
三视图定义见[通信建模的三张视图](communication-scope-and-transport.md)。

## 2. Canonical 文档所有权

| 概念 | Canonical 文档 | 相邻导读或实例 |
|---|---|---|
| 工程术语、亲缘关系与命名后缀 | [术语体系与词典](terminology.md) | 本索引、各专题首次定义 |
| 基础语义 | [基础语义](technical-route/01-semantic-foundation.md) | [术语表](terminology.md) |
| Pattern、InterfaceProtocol、InterfaceSession | [Pattern 与 InterfaceProtocol](technical-route/02-patterns-and-interface-protocol.md) | 各协议专题 |
| observation、AtomicFrame | [Observation 层](observation-layer.md) | [执行与证据](technical-route/06-observation-execution-evidence.md) |
| asynchronous REQ/ACK encoding | [异步四相握手](asynchronous-handshake.md) | [Observation 层](observation-layer.md)、[组网构造](network-construction.md) |
| VirtualDut、backend、行为构造 | [VirtualDut 方法论](virtual-dut.md) | [VirtualDut 导读](technical-route/03-virtual-dut.md) |
| capacity、admission、backpressure | [容量、接纳与背压](capacity-admission-and-backpressure.md) | [VirtualDut 方法论](virtual-dut.md)、[组网构造](network-construction.md) |
| attachment、binding、integration | [Integration 与 binding](technical-route/04-integration-and-binding.md) | [APB 读取示例](technical-route/07-apb-read-walkthrough.md) |
| bridge、typed Transform | [Bridge 与事务转译](typed-transaction-translation.md) | [跨领域设计启示](bridge-construction-insights.md)、[V1 实施状态](translation-implementation.md) |
| address fabric、crossbar | [AddressFabric](address-fabric.md) | [组网构造](network-construction.md) |
| SystemProtocol、InterfaceConnection、DirectedTransportConnection | [系统语义边界](system-protocol.md) | [SystemProtocol 导读](technical-route/05-system-protocol.md) |
| 构造依赖、判定作用域、表示与 transport | [通信建模的三张视图](communication-scope-and-transport.md) | [ACE/CHI 边界](ace-chi-communication-scopes.md)、[组网构造](network-construction.md) |
| network construction/runtime | [组网构造](network-construction.md) | [执行与证据](technical-route/06-observation-execution-evidence.md) |
| CHI coherence participant/network 组合 | [CHI coherence network session](chi-coherence-network-session.md) | [组网构造](network-construction.md)、[当前实现状态](implementation-status.md) |
| 可视化视图的分类、ViewIR 与 renderer | [可视化视图与 Artifact 管理](visualization-and-artifacts.md) | [运行产物管理](run-output-management.md)、[事务时空图](../visualization/transaction-time-space-view.md) |
| artifact 存储、manifest 与发布 | [运行产物管理](run-output-management.md) | [可视化视图与 Artifact 管理](visualization-and-artifacts.md)、[执行与证据](technical-route/06-observation-execution-evidence.md) |
| transaction time-space view | [事务时空图](../visualization/transaction-time-space-view.md) | [运行产物管理](run-output-management.md) |

若一个相邻页面需要使用这些概念，应给出本页所需的最小解释并链接 canonical 文档，避免复制完整定义、
状态表和实施计划。

## 3. 页面内部的解释顺序

架构页通常按以下顺序组织：

1. 定位与术语：对象是什么、观察范围在哪里；
2. 构造或运行机制：对象怎样组成、状态怎样流动；
3. 设计理由：协议要求、架构边界、复用收益或复杂度取舍；
4. 相邻边界：哪些事实属于其他层，哪些选择需要显式 policy；
5. 示例：用具体协议或场景验证抽象；
6. 当前实现与后续：单独放在末尾或链接状态/roadmap 页面；
7. 常见误解：只作辅助，不作为整篇目录主骨架。

理由需要说明性质。例如“APB attachment 不放进 InterfaceProtocol”是依赖方向和职责边界；“V1 child 严格串行”
是阶段性复杂度选择；“APB 一次只有一个 active transfer”来自所选协议/profile。三者不应写成同一种
“不允许”。

## 4. 三种文档角色

| 文档角色 | 主要内容 | 时间敏感度 |
|---|---|---|
| canonical 架构 | 概念、机制、理由、边界和稳定示例 | 较低 |
| 技术路线/教程 | 推荐阅读顺序和端到端直觉 | 中等，只摘要 canonical 内容 |
| 状态/实施计划 | 已实现、未完成、实施顺序和验收条件 | 较高 |

协议专题位于 canonical 架构与状态之间：它应解释规范事实如何落入通用层级，同时清楚标记当前 profile
覆盖范围。
