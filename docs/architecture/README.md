# 架构文档索引

架构文档建立一套可独立阅读的概念体系。每个核心概念由一篇 canonical 文档负责完整定义；canonical owner
可以位于本目录根部或 `technical-route/`，以下所有权表给出准确入口。未在表中承担 canonical 职责的技术路线页
提供阅读路径。协议专题说明具体标准如何落入架构，状态页与近期 Roadmap 分别记录实现覆盖和工作顺序。

若当前问题是“这段实现应放在哪个源码包”，先看
[`protocol_model` 源码导航](../../protocol_model/README.md)。本目录聚焦概念、机制、设计理由及职责交接。

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

箭头标注构造或解释依赖。协议栈层级和运行时顺序由各协议及执行路径分别定义。InterfaceProtocol 与
VirtualDut 行为独立构造，在 attachment/binding 处汇合；SystemProtocol 将判定范围扩展到多条连接，
attachment 定义端口侧转换和状态 fragment，backend runtime state 保存并更新绑定后的实例。完整的三视图定义见
[通信建模的三张视图](communication-scope-and-transport.md)。

## 2. Canonical 文档所有权

| 概念 | Canonical owner | 相邻导读或实例 |
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

相邻页面给出当前论述所需的最小解释，并链接 canonical owner。完整定义、实现状态和实施计划分别回到
对应的权威页面维护。

## 3. 页面内部的解释顺序

架构页通常按以下顺序组织：

1. 定位与术语：对象是什么、观察范围在哪里；
2. 构造或运行机制：对象怎样组成、状态怎样流动；
3. 设计理由：协议要求、架构边界、复用收益或复杂度取舍；
4. 职责交接：相邻事实由谁持有，哪些选择需要显式 policy；
5. 示例：用具体协议或场景验证抽象；
6. 当前实现与后续：单独放在末尾或链接状态/roadmap 页面；
7. 误解索引：按需补充，供读者快速定位易混概念。

设计理由同时标注来源和适用范围。例如，APB attachment 归 integration 所有，来源是依赖方向与职责边界；
V1 child 严格串行，来源是当前阶段的复杂度选择；APB 一次只有一个 active transfer，来源是所选
协议/profile。这样的分类让架构约束、阶段选择和协议要求保持各自的证据强度。

## 4. 四种文档角色

| 文档角色 | 主要内容 | 时间敏感度 |
|---|---|---|
| canonical 架构 | 概念、机制、理由、边界和稳定示例 | 较低 |
| 技术路线/教程 | 除表中具名 canonical owner 外的推荐阅读顺序、端到端直觉和摘要 | 中等 |
| 实现状态 | 已实现能力、明确缺口、证据与 profile 边界 | 较高 |
| 近期 Roadmap | 当前工作顺序、依赖与验收条件 | 较高 |

协议专题连接 canonical 架构与状态页：正文解释规范事实如何落入通用层级，profile 标记给出当前覆盖范围。

## 5. 写作约定

页面先建立读者需要保留的正向模型：说明主题、权威事实、输入、输出和相邻交接。源码 README 通常按
“用途与公共入口 → 输入/输出与状态 owner → 构造或执行流 → 相邻包与 canonical 链接 → 必要护栏”组织。

职责表优先使用“owned facts、inputs、outputs、handoff”等列；正文使用有明确主语的动作，例如
“resolution 冻结计划”“runtime 执行已解析 topology”。对比句用于澄清真实歧义，禁止项用于协议要求、
安全条件或可执行架构 invariant，并同时说明适用范围。

实现阶段使用“当前”“本 profile”“尚未实现”等状态语言，并链接
[实现状态](implementation-status.md)；近期顺序和验收条件链接
[Roadmap](technical-route/08-roadmap.md)。一个段落尽量承载一项 claim，平行事实进入表格，历史流水账回到
其权威状态页。
