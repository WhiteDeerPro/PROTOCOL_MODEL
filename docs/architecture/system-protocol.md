# InterfaceProtocol、VirtualDut 与 SystemProtocol

本文定义单接口合同、具名 module 和系统通信作用域的稳定边界。构造依赖、判定作用域与表示/运输的完整关系见
[通信建模的三张视图](communication-scope-and-transport.md)。

## 1. 三个核心组合对象

| 对象 | 定位 | 持有的事实 | 典型运行对象 |
|---|---|---|---|
| `InterfaceProtocol` | 一次完整逻辑接口上的静态合同 | role、channel/event schema、参数和接口局部约束 | 每个 connection 独立的 `InterfaceSession` |
| `VirtualDut` | 一个具体、具名的 DUT/module 边界 | typed ports、boundary capability、backend binding 和 module 局部行为 | backend state |
| `SystemProtocol` | 选定验证作用域内的通信模型聚合根 | VirtualDuts、canonical connections、system boundary、authority 和跨连接合同 | elaborated plan、system session、monitor |

`VirtualDut` 的实现可以来自 Python backend、外部代理、参考模型或嵌套的 `SystemProtocol`。协议参与者则描述
role/profile、身份和 progress coupling；一个 module 可包含多个参与者，一个参与者也可跨越多个内部 module。
拓扑节点需要独立构造和观测时，参与者才展开为具名 `VirtualDut`。

### 1.1 接口连接与 transport hop

| 名称 | 表达的关系 | 状态或解释者 |
|---|---|---|
| `InterfaceConnection` | 把一份完整 `InterfaceProtocol` 的 roles 绑定到具体 `InterfacePort` | `InterfaceSession` 执行接口局部合同 |
| `DirectedTransportConnection` | 在 canonical topology 中声明 transmitter→receiver hop | elaboration 产生只读 hop plan |
| `TransportLink` | 具体协议族的一条单向 flow-control connection | family transport session 持有 activation、credit 和 hop resource |

`SystemProtocol.connections` 是 `InterfaceConnection` 与 `DirectedTransportConnection` 的唯一 topology 权威。
`ResolvedTransportPlan` 从该注册表派生，并为 family runtime 提供只读查询。

## 2. SystemProtocol 的组合与判定范围

`InterfaceProtocol` 的 trace alphabet 覆盖一份完整逻辑接口；`SystemProtocol` 的 alphabet 进一步包含具名
connection、module boundary、system authority 和跨连接关系。

一个系统声明可写为：

```text
SystemProtocol S
  = (VirtualDuts,
     InterfaceConnections ∪ DirectedTransportConnections,
     Boundary,
     SystemContracts,
     SystemSemantics)
```

其可观察行为由各局部合同、module 行为和系统关系共同约束：

```text
Traces(S)
  = Compose(interface contracts,
            transport contracts,
            VirtualDut semantics,
            canonical topology,
            system constraints)
```

对任一 interface connection `C`，系统 trace 的局部投影满足对应接口合同：

```text
Project[C](Traces(S)) ⊆ Traces(InterfaceProtocol[C])
```

`Traces`、`Compose` 和 `Project` 在这里是架构数学记法。当前 Python 对应物由 `InterfaceSession`、
`SystemSession`、family transport session、elaboration namespace 和 resolved plan 分别承担；完整的
hide/project refinement checker 按 Roadmap 演进。

SystemProtocol 承接跨 connection 才能闭合的关系：

- address/home/identity authority、目标唯一性和 path capability；
- request origin、跨节点 owner、ID mapping 与 completion return；
- buffer、credit、outstanding、wait-for 和跨节点 progress；
- broadcast/fork/join、coherence permission 与 ordering；
- clock/reset/security/coherence membership；
- 隐藏内部 connections/hops 后的 boundary refinement。

Boundary refinement 将内部 module 与 connection 投影掉，再检查外部 trace 是否满足已声明的 boundary
protocol 和 system guarantee。两个 `VirtualDut` 加一条 connection 的 point-to-point 系统是同一组合模型的
最小实例。

## 3. 事实与状态所有权

项目遵循“一项可变事实对应一个运行权威”。声明、projection 和 reference ledger 通过具名类型共享所需信息。

| 事实 | 权威 owner | SystemProtocol 的使用方式 |
|---|---|---|
| interface correlation、ordering、outstanding | 对应 `InterfaceSession` | 汇入 connection trace 与 system verdict |
| decode、route、FIFO、arbiter、owner table、真实 directory | 对应 `VirtualDut` backend | 消费公开的 boundary capability、event 和 typed projection |
| interface/transport connection 声明 | `SystemProtocol.connections` | elaboration 校验 ownership 并派生执行计划 |
| address/home/identity/domain authority | `SystemProtocol` 中的 system contract | resolution 产生闭合后的只读 plan |
| backend 稳定配置 | 对应 `VirtualDut` backend | 与 system contract 的 typed boundary projection 闭合 |
| 端到端 owner、coherence、progress 参考状态 | system monitor ledger | 对多个 module 共同形成的可见行为给出 verdict |
| accepted event、causal edge、resource snapshot | system/family session | 提供 monitor、analysis 和 artifact 的输入 |

SystemProtocol 只读取 module 的公开 boundary：具名端口、capability、事件和 typed projection。backend 私有
状态保持 opaque，并由 backend 自身执行。

地址事实采用单一 system authority：

- 生成式 fabric 从 system contract 派生本地 route 配置，并在 construction 时核对 boundary projection；
- 外部 RTL/RPC module 将本地 decode 暴露为 boundary contract/projection，由 system closure 校验；
- resolved address plan 保存 contract、route、connection 与 receiver claim 的来源关系。

## 4. 构建与执行阶段

```text
SemanticConstraint / Resource / Obligation
         ├── Pattern ─────────────► InterfaceProtocol ─┐
         ├── behavior primitives ─► backend ───────────┼─ bind ─► VirtualDut
         └── typed forms ─────────► attachment/stage ──┘

VirtualDuts + Interface/DirectedTransport connections + system contracts
                    │ construct
                    ▼
              SystemProtocol
                    │ elaborate / resolve
                    ▼
       ElaboratedSystemProtocol
          ├─ semantics namespace
          ├─ owner_by_port
          ├─ address_plan
          └─ transport_plan
                    │ execute / monitor / analyze
                    ▼
          trace + verdict + derived evidence
```

构建动词各自表达一种关系：

| 动词 | 语义 |
|---|---|
| `compose` | 合取或并行组合独立 semantic fragment |
| `refine` | 单调收窄一份合同的合法行为 |
| `bind` | 在 `VirtualDut` 内把 attachment 绑定到具体 port |
| `connect` | 绑定完整逻辑接口，或加入具名有向 transport hop |
| `construct` | 展开 recipe/factory，形成显式 module、connection 和 contract |
| `elaborate` | 校验结构与 ownership，组合 namespace，并产生不可变 resolved plan |

construction 通过调用方注入的 factory 接入协议族实现。generic system package 接收构造后的
`VirtualDut`、boundary projection 和显式合同；具体标准继续位于 `protocols/<family>/...` 叶包。

runtime 接收已经固定的 topology 与 resolved plan。根 `SystemSession` 执行 `InterfaceConnection`；
transport family session 执行 `ResolvedTransportPlan` 中的 directed hops。monitor 消费事件并维护 reference
ledger，analysis 读取 topology、plan、trace 或资源快照形成派生证据。

## 5. 递归组合与验证工作流

`SystemProtocol.as_virtual_dut()` 将系统 boundary ports 投影为一个复合 `VirtualDut`，从而复用同一构造规则：

```text
module → subsystem → SoC → chiplet/package → board → fabric

SystemProtocol --as_virtual_dut()--> outer SystemProtocol
```

跨片通信继续组合 interface、representation、transport、clock domain、medium、fault、training 和
latency/resource contract。例如 [UCIe](https://www.uciexpress.org/specifications)、
[PCI Express](https://pcisig.com/specification-overview/pci-express-base) 和
[CXL](https://computeexpresslink.org/about-cxl/) 可在各自标准定义的边界上具体化这些切面。

一次完整验证工作流沿下面的方向展开：

```text
SystemProtocol
  ─► elaborate / resolve
  ─► execute or explore with scenario
  ─► monitor / analyze
  ─► visualization / artifacts
```

未来 `Project` 的预留职责是选择 system、scenario/seed、driver/observer、执行策略、期望 property 和 artifact
policy。递归物理组合继续由 `as_virtual_dut()` 承担。

## 6. 实现与相邻文档

本文维护稳定的对象边界和组合规则。当前声明、elaboration、session、bridge/fabric、递归封装和逐协议覆盖见
[实现状态](implementation-status.md)；近期依赖顺序见
[Roadmap](technical-route/08-roadmap.md)。

- [SystemProtocol 源码导航](../../protocol_model/system/README.md)
- [SystemProtocol 组网架构](network-construction.md)
- [VirtualDut 方法论](virtual-dut.md)
- [Bridge 与类型化事务转译](typed-transaction-translation.md)
