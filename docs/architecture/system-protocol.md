# InterfaceProtocol、VirtualDut 与 SystemProtocol

## 1. 接口、模块与系统三个核心组合对象

新架构不把参与通信的 module 命名为 `Agent`。公共对象使用 `VirtualDut`，强调它是一个具体、
具名的 DUT/module，只是实现来自 Python 模型、外部代理、参考模型或嵌套系统，而不是当前被验
RTL 本体。

接口与系统使用两个作用域名称：

- `InterfaceProtocol`：一个逻辑接口连接上能够判定的局部通信语言；
- `SystemProtocol`：多个 interface/transport connections、VirtualDuts、资源和全局约束构成的用户通信协议。

本页聚焦这三个组合对象，不枚举全部 `ConstraintScope`。单事件检查与单 transport hop 检查分别使用
`EVENT` 和 `TRANSPORT`；完整判定作用域表见下方链接的三张视图文档。

`VirtualDut` 位于二者之间但不是协议层：它是持有模块行为状态并跨端口作出决定的具体 module。`network`
仍是 `SystemProtocol` 的 topology graph，但不作为最高层公共语义对象。这样可以
避免把“拓扑图”误认为“全部协议语义”，也避免 `NetworkProtocol` 与 CHI Network layer 混淆。构造依赖、
判定作用域和表示/运输是三张不同视图，完整定义见
[通信建模的三张视图](communication-scope-and-transport.md)。

## 2. SystemProtocol 的语义作用域

只要一个对象定义了参与方之间哪些可观察通信行为合法，它就在定义协议。`SystemProtocol` 因而是协议，
但不是简单的 `InterfaceProtocol` refinement；二者观察 alphabet 不同：

```text
Traces(SystemProtocol)
  = Compose(interface contracts, transport contracts,
            VirtualDut semantics, topology, system constraints)
```

对其中一条 interface connection `C`，局部正确性要求：

```text
Project[C](Traces(SystemProtocol)) ⊆ Traces(InterfaceProtocol[C])
```

这里的 `Traces/Compose/Project` 是架构目标的数学记法，不是当前同名 Python API。当前可执行对应物是：
InterfaceSession 检查单个完整逻辑接口，根 SystemSession 传播其 canonical events；transport-family session
执行 resolved directed hops，elaboration 组合静态 namespace。完整的 hide/project refinement checker 仍属于后续实现。

在此基础上，SystemProtocol 再增加局部 interface 无法单独判定的约束：

- 地址路由、目标唯一性和 capability 闭合；
- 跨 connection ID 映射、请求所有权和端到端响应归还；其中单个 crossbar 内的 owner/ID table 是该
  VirtualDut 的实现状态，SystemProtocol 检查多个节点组合后的闭合；
- buffer、credit、outstanding 和 wait-for；
- broadcast/fork/join；
- coherence permission、ordering 和系统级 progress；
- hide internal connections/hops 后的外部边界 refinement。

Boundary refinement 指隐藏内部 module/interface 以后，系统对外可见 trace 仍满足其声明的外部协议与保证；它不
要求外层知道内部采用了几个 bridge、FIFO 或 arbitration stage。

因此更准确的说法是“更大作用域、带更多关系的协议”，不是“同一协议对象的更深子类”。

所有 InterfaceProtocol 的具体使用都可以进入 SystemProtocol；需要显式观察 transport hop 时，也可加入
DirectedTransportConnection。只有两个 VirtualDut 和一条 connection 的 point-to-point 场景同样成立。点到点
便捷构造为这一退化形式提供直接入口；额外 system constraint 可以为空。这样验证入口始终统一，同时不强迫
简单总线承担网络复杂度。

## 3. 构建阶段

```text
SemanticConstraint / Resource / Obligation
         ├── Pattern ─────────────► InterfaceProtocol ─┐
         ├── behavior primitives ─► backend ───────────┼─ bind ─► VirtualDut
         └── typed forms ─────────► attachment/stage ──┘

VirtualDuts + Interface/DirectedTransport connections + system contracts
                    │ compose / resolve
                    ▼
              SystemProtocol
                    │ elaborate
                    ▼
       ElaboratedSystemProtocol
                    │ execute（interface 或 family transport session）
                    │ explore（后续调度/搜索）
                    ▼
       safety / progress / refinement
```

四个动词必须保持不同语义：

| 动词 | 语义 |
|---|---|
| `compose` | 合取或并行组合独立 fragment |
| `refine` | 单调收窄一个 InterfaceProtocol 的合法行为 |
| `bind` | 在 VirtualDut 内把 attachment 绑定到具体 `InterfacePort` |
| `connect` | 用 `InterfaceConnection` 绑定完整逻辑接口；用 `connect_transport` 加入有向 transport hop |
| `elaborate` | 解析 topology、所有权、参数、capability 和全局语义 namespace |

这里的 bottom-up 只描述语义组合和构造依赖，不是协议栈上下层。`SystemProtocol` 聚合
InterfaceProtocol/transport profile 实例、VirtualDut boundary、topology 与 system contracts；它拥有 topology closure、
跨 connection owner/return、address/capability resolution 和 system monitor 等独有方法，但不继承
InterfaceProtocol 的 channel/role/refine API。若以后需要派生体验，应由不可变的 `derive(...)` 增加合同，
而不是建立 `AxiSystemProtocol`、`CrossbarSystemProtocol` 一类继承树。

## 4. VirtualDut 的边界

`VirtualDut` 是具体系统节点，而不是协议：

```text
VirtualDut
  name
  typed InterfacePort / TransportPort
  boundary contract
  opaque or constructed backend binding
  externally visible resources and capabilities
```

VirtualDut 不用互斥 kind 或 facet 驱动语义。外部 backend 可以保持内部状态不透明；需要构造
reference endpoint、bridge 或 crossbar 时，再使用 Source、Transform、Store、Correlate、Route、
Arbitrate 等行为算子。跨端口行为属于 DUT 边界 contract，连接后由 SystemProtocol 检查全局闭合。
具体分层见 [VirtualDut 方法论](virtual-dut.md)。

TileLink 文献中的 agent 可能比 RTL module 更细，因为一个 module 可以包含多个独立 agent。
遇到这种情况，不改变公共命名：一个 `VirtualDut` 可以在其内部声明多个 protocol context；只有
当它们必须作为独立 topology 节点验证时，才拆成多个具名 VirtualDut。

## 5. 递归组合与跨片

架构不在 SoC 之后继续增加 `ChipProtocol`、`BoardProtocol`、`RackProtocol` 等固定层级。
`SystemProtocol.as_virtual_dut()` 把一个已经构造的系统封装成带 boundary ports 的复合
VirtualDut，因此同一种组合规则可以递归用于：

```text
module → subsystem → SoC → chiplet/package → board → fabric
```

跨片协议真实存在，而且往往比片上协议增加 PHY、训练、lane、重传、热插拔、错误和异步时钟
语义。例如：

- [UCIe](https://www.uciexpress.org/specifications) 是 package 级 die-to-die/chiplet 标准，
  覆盖物理层、die-to-die protocol 和软件栈；
- [PCI Express](https://pcisig.com/specification-overview/pci-express-base) 定义系统和外设的
  interconnect、fabric management 与编程接口；
- [CXL](https://computeexpresslink.org/about-cxl/) 在处理器、内存扩展和加速器之间提供
  cache-coherent interconnect。

这些不是固定增加在 SystemProtocol 上方的新建模层级，而是 InterfaceProtocol、VirtualDut、SystemProtocol
与表示/运输 stack 的组合；物理边界差异由 RepresentationCodec、TransportLink、clock domain、transport
medium、fault model、training state 和 latency/resource contract 表达。

## 6. 当前实现边界

本页定义接口、模块和系统的长期判定作用域，不维护逐协议能力表。当前声明、elaboration、session、bridge/fabric 和
递归封装的实现范围见[实现状态](implementation-status.md)；construction lowering 与组网阶段见
[SystemProtocol 组网架构](network-construction.md)；bridge 内部的 typed Transform 见
[Bridge 与类型化事务转译](typed-transaction-translation.md)。源码职责骨架和当前文件的迁移地图见
[`protocol_model/system/README.md`](../../protocol_model/system/README.md)。

异步 emission、wait-for/deadlock、boundary refinement 和 nested runtime 的依赖顺序由
[Roadmap](technical-route/08-roadmap.md)维护。

SystemProtocol 可以视为一个选定通信作用域的模型聚合终点，但不是整个工程的终点。它之后仍有 resolution、
scenario/session、monitor/analysis 和 artifact projection；未来的 `Project` 只负责把这些验证活动编排到一起，
不成为更高一级协议。另一方面，`as_virtual_dut()` 可以把当前系统重新封装成一个复合 VirtualDut，因此
SystemProtocol 也不是物理层级上的永久顶点。
