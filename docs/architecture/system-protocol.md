# LinkProtocol、VirtualDut 与 SystemProtocol

## 1. 三个核心对象

新架构不把参与通信的 module 命名为 `Agent`。公共对象使用 `VirtualDut`，强调它是一个具体、
具名的 DUT/module，只是实现来自 Python 模型、外部代理、参考模型或嵌套系统，而不是当前被验
RTL 本体。

协议使用两个作用域名称：

- `LinkProtocol`：一个逻辑 link 上能够判定的局部通信语言；
- `SystemProtocol`：多个 links、VirtualDuts、资源和全局约束构成的用户通信协议。

`network` 仍是 `SystemProtocol` 的 topology graph，但不再作为最高层公共语义对象。这样可以
避免把“拓扑图”误认为“全部协议语义”，也避免 `NetworkProtocol` 与传统网络层协议混淆。

## 2. SystemProtocol 的语义作用域

只要一个对象定义了参与方之间哪些可观察通信行为合法，它就在定义协议。`SystemProtocol` 因而是协议，
但不是简单的 `LinkProtocol` refinement；二者观察 alphabet 不同：

```text
Traces(SystemProtocol)
  = Compose(LinkProtocols, VirtualDut semantics, topology, system constraints)
```

对其中一条 link `L`，局部正确性要求：

```text
Project[L](Traces(SystemProtocol)) ⊆ Traces(LinkProtocol[L])
```

这里的 `Traces/Compose/Project` 是架构目标的数学记法，不是当前同名 Python API。当前可执行对应物是：
LinkSession 检查单 link trace，SystemSession 传播具体事件，elaboration 组合静态 namespace；完整的 hide/project
refinement checker 仍属于后续实现。

在此基础上，SystemProtocol 再增加局部 link 无法单独判定的约束：

- 地址路由、目标唯一性和 capability 闭合；
- 跨 link ID 映射、请求所有权和端到端响应归还；其中单个 crossbar 内的 owner/ID table 是该
  VirtualDut 的实现状态，SystemProtocol 检查多个节点组合后的闭合；
- buffer、credit、outstanding 和 wait-for；
- broadcast/fork/join；
- coherence permission、ordering 和系统级 progress；
- hide internal links 后的外部边界 refinement。

Boundary refinement 指隐藏内部 module/link 以后，系统对外可见 trace 仍满足其声明的外部协议与保证；它不
要求外层知道内部采用了几个 bridge、FIFO 或 arbitration stage。

因此更准确的说法是“更大作用域、带更多关系的协议”，不是“同一协议对象的更深子类”。

所有 LinkProtocol 的具体使用都提升为 SystemProtocol，包括只有两个 VirtualDut 和一条 link
的 point-to-point 场景。`SystemProtocol.from_link()` 为这一退化形式提供直接构造；额外系统
constraint 可以为空。这样验证入口始终统一，同时不强迫简单总线承担网络复杂度。

## 3. 构建阶段

```text
SemanticConstraint / Resource / Obligation
                    │ compose
                    ▼
             SemanticFragment
                    │ define/refine
                    ▼
               LinkProtocol
                    │ bind to typed port
                    ▼
               VirtualDut
                    │ connect
                    ▼
              SystemProtocol
                    │ elaborate
                    ▼
       ElaboratedSystemProtocol
                    │ execute/explore（下一阶段）
                    ▼
       safety / progress / refinement
```

四个动词必须保持不同语义：

| 动词 | 语义 |
|---|---|
| `compose` | 合取或并行组合独立 fragment |
| `refine` | 单调收窄一个 LinkProtocol 的合法行为 |
| `bind` | 在 VirtualDut 内把 attachment 绑定到具体 `ProtocolPort` |
| `connect` | 用 `ProtocolLink` 把不同 VirtualDut 的端口接入 topology |
| `elaborate` | 解析 topology、所有权、参数、capability 和全局语义 namespace |

## 4. VirtualDut 的边界

`VirtualDut` 是具体系统节点，而不是协议：

```text
VirtualDut
  name
  typed protocol ports
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

这些不是新的建模层级，而是新的 LinkProtocol、VirtualDut 和 SystemProtocol 组合；物理边界
差异以后由 clock domain、transport medium、fault model、training state 和 latency/resource
fragment 表达。

## 6. 当前实现边界

本页定义三个对象的长期作用域，不维护逐协议能力表。当前声明、elaboration、session、bridge/fabric 和
递归封装的实现范围见[实现状态](implementation-status.md)；construction lowering 与组网阶段见
[SystemProtocol 组网架构](network-construction.md)；bridge 内部的 typed Transform 见
[Bridge 与类型化事务转译](typed-transaction-translation.md)。

异步 emission、wait-for/deadlock、boundary refinement 和 nested runtime 的依赖顺序由
[Roadmap](technical-route/08-roadmap.md)维护。
