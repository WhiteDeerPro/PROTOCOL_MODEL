# 通信建模的三张视图：构造依赖、判定作用域与表示/运输

Protocol Model 用三张正交视图描述 AXI、TileLink、CHI 以及片间协议。一个对象可以同时出现在多张视图中，
每张图的边具有独立含义。

| 视图 | 回答的问题 | 关系或产物 |
|---|---|---|
| 构造依赖 | 一个对象由哪些已有构件装配 | `uses`、`bind`、`connect`、`construct`、`elaborate` |
| 判定作用域 | 一项规则至少观察哪些对象，运行事实由谁持有 | `ConstraintScope`、state owner、projection、verdict |
| 表示/运输 | 通信事实采用什么形式，怎样占用资源移动 | operation/transaction/message/packet/flit/phit、codec、hop session |

这三张视图共同支持基础语义、`InterfaceProtocol`、`VirtualDut` 和 `SystemProtocol` 主线，并为 packetized
NoC、缓存一致性与 chip-to-chip transport 提供明确落点。

## 1. 规范术语与项目名称

公共名称按语义选择；协议族文档继续保留各规范的原词。

| 来源或语境 | 原词的含义 | Protocol Model 落点 |
|---|---|---|
| AXI/AHB/APB interface | 一组方向固定、共同完成协议行为的 channels/signals | `InterfaceProtocol`、`InterfacePort`、`InterfaceConnection` |
| TileLink link | 两个 agents 之间完成 operation 所需的一组 channels | 完整逻辑接口合同及其 `InterfaceConnection` |
| CHI Link | Transmitter 到 Receiver 的单向 flit flow-control connection | family `TransportLink`、`TransportPort`、`DirectedTransportConnection` |
| TileLink agent / CHI RN、HN、SN、MN | 协议 role、身份和 progress coupling 的参与者 | family participant/profile，按需绑定到 `VirtualDut` |
| CHI Network layer | message packetization、route identity 和 packet delivery | family representation/network slice |
| 工程中的 network | module connection graph、system authority 及其派生关系 | `SystemProtocol` topology、contracts、resolution、runtime、analysis |

`SystemProtocol` 是公共的系统聚合名称。`network` 在通用文档中指它拥有的 topology 及派生关系；CHI
Network layer、TileLink link、CHI Link layer、link credit 和 physical link 在协议族语境中保持规范原义。

## 2. 构造依赖视图

构造依赖记录对象装配时使用的构件：

```text
CanonicalEvent / Constraint / Resource / Obligation
                    ├── Pattern ─────────► InterfaceProtocol
                    ├── typed forms ─────► TranslationStage / RepresentationCodec
                    └── behavior primitives ─► VirtualDut backend

InterfaceProtocol + attachment + backend ──bind──► concrete VirtualDut

VirtualDuts
  + (InterfaceConnection | DirectedTransportConnection)
  + system contracts
                    ──construct──► SystemProtocol

SystemProtocol ──elaborate──► owner map + resolved address/transport plans
ResolvedTransportPlan + family profile ──execute──► family transport session
```

箭头表达“构造时使用”。基础语义提供 scope-neutral event、constraint、resource 和 obligation；
`InterfaceProtocol` 与 backend 各自构造，在 attachment/binding 处汇合。`SystemProtocol` 接收具名 module
boundary、显式 connections 和 system contracts。

SystemProtocol 读取 `VirtualDut` 的公开 boundary：port、capability、event 与 typed projection。backend
私有状态保持 opaque。协议族通过 attachment、factory、profile 或 projection 接入，通用包继续提供共享设施。

`SystemProtocol.connections` 是 interface connections 与 directed transport connections 的唯一 topology
权威；elaboration 只读派生 `ResolvedTransportPlan`。

## 3. 判定作用域与状态所有权视图

判定作用域描述一项规则所需的最小观察边界：

```text
Canonical event
   ├─ observed within one complete interface ─► INTERFACE
   └─ observed on one directed hop ───────────► TRANSPORT

port events + local backend state ────────────► VIRTUAL_DUT
multiple modules/connections + authority ─────► SYSTEM
```

`INTERFACE` 与 `TRANSPORT` 是并列的局部作用域。前者观察完整逻辑接口的 channel correlation 和 transaction
lifecycle；后者观察单向相邻 hop 的 flit 接纳与 flow-control resource。

| `ConstraintScope` | 关注内容 | 声明或判定合同 | 典型运行 owner |
|---|---|---|---|
| `EVENT` | 一次观察的字段、枚举、对齐与原子采样 | event schema、observation policy | observer / lowering session |
| `TRANSPORT` | 一个有向 hop 的 flit、credit、activation、lane/subchannel resource | family transport contract/profile | family transport link session |
| `INTERFACE` | 一个完整接口的 channel、ordering、correlation、outstanding | `InterfaceProtocol` | 每连接 `InterfaceSession` |
| `VIRTUAL_DUT` | 具名 module 的 decode、store、route、transform、completion | module boundary/backend contract | `VirtualDut` backend |
| `SYSTEM` | 多 module 的 route closure、端到端 owner、coherence、progress、refinement | system contract | system/family session 与 monitor |

scope 名称只编码最小观察范围；协议标准自己的层次由表示/运输映射单独记录。

### 3.1 一项事实对应一个运行权威

其他作用域通过不可变声明、typed projection、索引或 verdict 使用权威事实。

| 主题 | 可执行事实 owner | 系统声明或参考 owner |
|---|---|---|
| address/home routing | RN/HN/decoder/ICN backend 的 SAM、route、remap state | SystemProtocol 的 address/home authority、reachability 和 closure result |
| cache coherence | cache tags/data/permission、真实 directory、snoop-filter backend state | system monitor 的 reference coherence ledger |
| bridge/crossbar | FIFO、AW→W owner、ID remap、return table、arbiter state | 跨节点 request owner 与 completion-return ledger |
| flow control | interface/hop credit、lease、outstanding counter | wait-for projection、跨节点 dependency、deadlock witness |
| topology | `SystemProtocol.connections` 的 canonical 声明 | resolved plan 与 visualization 的只读投影 |

reference ledger 在名称和 API 上表明验证用途。monitor 消费公开事件并维护参考状态；module backend 继续执行
真实 directory、owner table 和资源状态。

### 3.2 Module 与协议参与者

| 概念 | 稳定含义 | 组合关系 |
|---|---|---|
| `VirtualDut` | 一个具体、具名、可连接的 module boundary | canonical topology 的节点 |
| 协议参与者 | role/profile、identity namespace、接口集合与 progress coupling | 可与 VirtualDut 建立多对多 family binding |

一个 module 可以包含 instruction-cache、data-cache 和配置等多个参与者；一个参与者也可以覆盖多个内部 RTL
module。当前 CHI 使用 family-specific participant binding，将共享状态的 RN、Home 或 router 绑定到同一
`VirtualDut` 的多组 `TransportPort`。跨协议公共 participant API 的抽取条件是第二个协议族证明字段与生命周期
可稳定复用。

## 4. 表示与运输视图

表示轴将用户意图逐步具体化为协议和传输对象：

| 形式 | 工程含义 | 示例 |
|---|---|---|
| Operation | 协议无关的意图与效果 | `AddressRead`、`AddressWrite`、permission acquire |
| Transaction | 关联请求、消息、完成与状态变化的一次有身份生命周期 | AXI AR→R、AW/W→B；CHI read transaction |
| Message | 参与者之间一次有类型的协议交换 | TileLink `Get`、CHI Request/Data response |
| Packet | 带 network identity、可独立路由的对象 | 带 SrcID/TgtID 的 CHI packet |
| Flit | 一个 hop 的 flow control 接纳和释放单位 | CHI protocol flit、link-maintenance flit |
| Phit | 相邻 network devices 间一次 physical-layer transfer | CHI Issue H Link transfer |

Transaction 首先表达 operation 的 lifecycle 与 correlation。具体协议 profile 决定 transaction 与 messages 的
cardinality，以及 message、packet、flit、phit 中实际采用的层次。AXI/APB 可以折叠中间表示；PHY 或
serialization 验证可以继续展开 lane beat 和 physical transfer unit。

### 4.1 三类变换

| 变换 | 输入与输出 | 持有的合同和状态 |
|---|---|---|
| Semantic translation | `operation → operation'` | `TranslationStage/Plan`；能力、拆分、完成与错误映射 |
| Representation codec | `message ↔ packet ↔ flit` | typed form、lineage、header provenance、split/merge/reassembly |
| Transport scheduling | `packet/flit → route + resource usage` | hop、VC/RP、buffer、arbiter lease、latency/progress |

semantic translation 可以改变 operation form 或完成方式；representation codec 保存声明的语义 projection；
transport scheduling 决定运输资源和时间。三者可以复用 typed forms、capacity pool 和 lifecycle ledger，并以
各自 contract 组合。

### 4.2 CanonicalEvent

`CanonicalEvent` 是 observation 或 attachment 已解码的一次通信事实，统一承载 trace、constraint 和 causal
evidence。event 的 typed payload/form 或显式 envelope 标明 message、packet、flit 等表示粒度。

当前 CHI Issue H slice 分别定义 protocol message、network packet 和 protocol-flit envelope；其他协议族按自身
表示链选择 typed form，并复用同一 event/trace 基础设施。

## 5. 公共对象与源码所有权

| 对象 | 稳定含义 | 主要源码 owner |
|---|---|---|
| `SemanticFragment` | 各作用域共享的 constraint/resource/obligation 组合 | `protocol_model.semantics` |
| `InterfaceProtocol` | 一次完整逻辑接口上的静态合同 | `protocol_model.interface` |
| `InterfaceSession` | 一份 interface connection 的可执行合同状态 | `protocol_model.interface` |
| `InterfacePort` | `VirtualDut` boundary 上带 protocol role 的完整接口端口 | `protocol_model.virtual_dut.boundary` |
| `InterfaceConnection` | 把 interface roles 绑定到具体 ports 的连接实例 | `protocol_model.system.topology` |
| `TransportPort` | transmitter 或 receiver 的 family transport boundary | `protocol_model.virtual_dut.boundary` |
| `DirectedTransportConnection` | canonical topology 中的一次 transmitter→receiver hop 声明 | `protocol_model.system.topology` |
| `TransportLink` | family 解释的一条单向 flow-control connection | `protocols/<family>/transport` |
| `ResolvedTransportPlan` | 从 directed connections 派生的只读 hop 查询 | `protocol_model.system.resolution` |
| `VirtualDut` | 具体、具名的 module boundary 与 backend binding | `protocol_model.virtual_dut` |
| `SystemProtocol` | VirtualDuts、connections、boundary 与 system contracts 的聚合 | `protocol_model.system` |
| `TranslationStage/Plan` | operation 级 semantic translation | `protocol_model.virtual_dut` 通用设施与 integrations |

具体协议标准位于 `protocol_model.protocols` 叶包。协议族选择真实场景所需的 interface、representation、
transport、participant 和 system 切面；公共内核通过 typed projection、profile 与 factory 保持依赖方向。

## 6. CHI 在三张视图中的映射

[Arm AMBA CHI Issue H](https://developer.arm.com/documentation/ihi0050/h) 用三层分配协议、网络和 Link 职责：

| CHI 层 | 规范职责 | Protocol Model 视图 |
|---|---|---|
| Protocol | transaction、cache state transition、message flow、protocol-level flow control | typed protocol contract、participant lifecycle |
| Network | message packetization、source/target NodeID 与 packet routing | representation codec、network packet、resolved system identity/route |
| Link | 相邻 devices 之间的 flit flow control 与 channel dependency | `TransportLink`、directed hop、family transport session |

B1.3 区分 transaction、message、packet、flit 和 phit；B13.2 将 Link 定义为一对
Transmitter/Receiver 之间的单向连接。Issue H 中每个 network packet 装入一个 protocol flit，每个 flit 由一个
phit 传送。对象分开保存各自事实：packet 保存跨 hop route identity，flit 占用当前 hop 的 L-Credit，phit
表达 physical transfer。`LCrdReturn` 等 link-maintenance flit 在相邻 transmitter/receiver 间完成 Link resource
归还，其表示链从 flit 开始。

Snoop request 的协议格式省略 `TgtID`。interconnect 选择 Snoopee 后，Network layer 为每个目的地建立带显式
target route identity 的 packet copy；Link layer 将 packet 对应的 protocol flit 运过当前 hop。Home/interconnect
backend 持有选靶、fanout 和 response aggregation 的执行状态，system monitor 核对跨节点结果。

### 6.1 CHI 概念 owner

| CHI 概念 | Protocol Model owner |
|---|---|
| REQ/RSP/SNP/DAT message schema、TxnID/DBID、Retry、P-Credit lifecycle | CHI protocol contract 与 participant/session ledger |
| RN-F/RN-I/HN-F/HN-I/SN/MN 行为和本地 cache/home 状态 | family participant profile + `VirtualDut` backend |
| NodeID、system address/home assignment、coherence membership | `SystemProtocol` contract 是 authority；CHI resolved plan 保存闭合投影 |
| RN/HN/ICN 实际 SAM、TgtID remap、route table | 对应 `VirtualDut` backend；typed projection 参与 system closure |
| message→packet、routing fields、packet copy identity | representation codec + network packet form |
| packet→flit、L-Credit、Link activation | transport profile、link/hop session |
| snoop target、fanout、direct data return、Home completion aggregation | Home/interconnect backend + system transaction session |
| router buffer、Resource Plane、跨 hop dependency | family transport runtime + system analysis |

Protocol Credit 与 Link Credit 使用不同的 resource domain：

| Resource | 表达的接纳保证 | owner 与释放条件 |
|---|---|---|
| P-Credit | completer 对 protocol transaction resource 的接纳及 Retry lifecycle | participant/session transaction ledger |
| L-Credit | 相邻 receiver 对一次 flit 的接纳能力 | 当前 `TransportLink` session |

二者可以建立在通用 resource/lease 设施上，各自保存计数与释放条件。

### 6.2 NodeID 与 SAM

CHI B3 规定 Requester 通过 System Address Map 确定 TgtID，并允许 SAM 位于 Request Node 或 interconnect；
interconnect 可以 remap TgtID。一个 Port 可以拥有多个 NodeID，每个 NodeID 分配给一个 Port。

```text
SystemProtocol
  NodeID uniqueness + address/home authority + reachability
                    │ typed projection / closure
                    ▼
VirtualDut backend
  implemented SAM + remap table + local routing state
```

生成式 interconnect 从 system authority 派生本地配置；外部 RTL 公开 typed projection，供 elaboration 或
monitor 与期望闭合。

### 6.3 CHI C2C

[Arm CHI C2C](https://documentation-service.arm.com/static/691c2cfd69f16e048ca621a4) 在 on-chip CHI 与 chip
pins 之间划分 Protocol、Packetization、Link 和 Physical 层。Packetization 可以把多个 message 装入定长
container，Link 增加 CRC 和 flit retry，Physical 层处理电气连接、skew 和 training。

这些层次形成可叠加的 representation/transport stack，并可通过 `SystemProtocol.as_virtual_dut()` 进入更外层
system composition。

## 7. TileLink 在三张视图中的映射

[SiFive TileLink Specification 1.9.3](https://sifive.cdn.prismic.io/sifive/928d6a82-77a9-4291-8b60-5e815429b1ab_tilelink_spec_1.9.3.pdf)
使用 agent、link 和 channel 描述通信：

- agent 拥有一个或多个 TileLink links；
- link 汇集两个 agents 之间完成 operations 所需的 channels；
- channel 是单向、同优先级的 message connection；
- agent graph 以 agent 为顶点、以 master interface→slave interface（规范原词）的 link 为有向边，用于分析
  channel priority 和 forward progress；
- RTL module 与 agent 允许多对多组织。

| TileLink 概念 | Protocol Model owner |
|---|---|
| A/B/C/D/E channel schema 与 request/response correlation | interface-local protocol 与 `InterfaceSession` |
| TL-UL/TL-UH/TL-C、地址空间 capability | endpoint/interface capability + system address claims |
| agent | family participant/profile；按 module boundary 绑定 `VirtualDut` |
| agent graph、channel priority、forward progress | system dependency projection 与 analysis |
| crossbar/cache/adapter 的局部转发与状态 | `VirtualDut` backend |
| per-address route、manager ownership、global permission | route plan + system coherence monitor |

当前 TileLink package 只公开 family identity；上表描述目标 owner 映射。建立 executable interface
builder/observer 与 family transport profile 后，单个 TileLink agent 可绑定为一个
`VirtualDut`/participant；需要验证 router buffer、route 和 channel dependency 时，再在同一
`SystemProtocol.connections` 中展开 `TransportPort` 与 `DirectedTransportConnection`，并派生只读
transport plan。

## 8. 实现状态、扩展与规范依据

本文维护三张视图、术语映射与 owner 边界。当前 opcode、profile、witness 和明确缺口统一见
[实现状态](implementation-status.md)；近期实施依赖见
[技术路线](technical-route/08-roadmap.md)；长期研究方向见[项目 Roadmap](../../ROADMAP.md)。

后续能力沿相应视图加入：typed capability 与 identity/home closure 属于构造和 system scope；
message/packet/flit codec 属于 representation；virtual channel、Resource Plane、C2C reliability 和 PHY
lifecycle 属于 transport。它们共享 scope-neutral 语义与 typed projection。

规范依据：

- [Arm AMBA CHI Architecture Specification, Issue H](https://developer.arm.com/documentation/ihi0050/h)：B1.1.3
  architecture layers，B1.3 terminology，B3 Network Layer，B13 Link Layer，B15 System Coherency Interface；
- [Arm AMBA CHI C2C Architecture Specification](https://documentation-service.arm.com/static/691c2cfd69f16e048ca621a4)：
  B2 interface structures、Protocol/Packetization/Link/Physical layers；
- [SiFive TileLink Specification 1.9.3](https://sifive.cdn.prismic.io/sifive/928d6a82-77a9-4291-8b60-5e815429b1ab_tilelink_spec_1.9.3.pdf)：
  2.1 Network Topology、2.2 Channel Priorities、5 Forward Progress；
- [UCB BAR TileLink overview](https://bar.eecs.berkeley.edu/projects/tilelink.html)：TileLink 对 coherence policy、
  cache controllers 与 on-chip network 的解耦定位。
