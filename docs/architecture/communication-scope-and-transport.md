# 通信建模的三张视图：构造依赖、判定作用域与表示/运输

本文规定 Protocol Model 如何同时容纳 AXI、TileLink、CHI 以及以后可能出现的片间协议。工程使用三张可以
互相引用、但不能压成一条“由低到高”继承链的视图：

1. **构造依赖**回答“一个对象需要哪些已有构件”；
2. **判定作用域**回答“判断一项规则至少要观察哪些对象，运行状态由谁持有”；
3. **表示/运输**回答“通信事实采用什么表示，以及如何使用传输资源移动”。

这一决定保留基础语义、VirtualDut 和 SystemProtocol 主线，同时为 packetized NoC、缓存一致性和
chip-to-chip transport 留出明确位置。工程使用 `InterfaceProtocol`、`InterfaceSession` 和
`InterfaceConnection` 表达完整逻辑接口，避免与 CHI Link layer、TileLink link 等规范术语混淆。

## 1. 为什么需要三张视图

不同协议对 `protocol`、`network`、`link` 使用了不同的技术含义：

- AXI、AHB 和 APB 通常把一组方向固定的 channel/signals 视为一个接口协议；
- TileLink 的 link 是两个 agent 之间完成 operation 所需的一组 channels；
- CHI 的 link 是一个 Transmitter 到一个 Receiver 的单向 flit 连接，双向 node interface 需要一对 links；
- CHI 还单独定义 Protocol、Network 和 Link 三层，通信粒度依次是 transaction、packet 和 flit；
- CHI C2C 在片间边界加入 packetization、data-link reliability 和 physical transport。

因此，仅使用一条名为“基础语义 → 协议 → 网络 → 链路”的工程层级，会混合三种不同关系：Python 构造依赖、
约束的观察范围，以及协议标准自己的表示栈。`InterfaceProtocol` 不是 VirtualDut 的“下一层硬件”，
CHI Link layer 也不是 SystemProtocol 的子层。三张视图分别记录这些关系。

## 2. 构造依赖视图

构造依赖说明对象怎样由已有构件装配。箭头只表示“构造时使用”，不表示协议栈层级或运行时数据必然依次经过：

```text
CanonicalEvent / Constraint / Resource / Obligation
                    ├── Pattern ──► InterfaceProtocol
                    ├── typed forms ──► TranslationStage / RepresentationCodec
                    └── behavior primitives ──► VirtualDut backend

InterfaceProtocol + attachment + backend ──► concrete VirtualDut
VirtualDuts + (InterfaceConnection | DirectedTransportConnection) + system contracts
                                                    ──► SystemProtocol
canonical directed edges ──► ResolvedTransportPlan ──► family transport session
```

基础语义是共享机制，不预先归属于 interface、VirtualDut 或 system。InterfaceProtocol 与 VirtualDut 行为分别
构造，在 attachment/binding 处汇合；SystemProtocol 消费已经声明清楚的模块边界和连接，不反射 attachment
私有状态。CHI transport 可以复用 EventSchema、monitor、resource 和 session product，也不需要伪装成
InterfaceProtocol。

## 3. 判定作用域与状态所有权视图

作用域表示判定一条约束所需的最小观察范围。状态遵循“一个事实由一个可变权威持有”的原则；其他作用域通过
不可变声明、typed projection、索引或 verdict 使用该事实。

```text
event-local
  ├─ transport-hop-local
  └─ interface-local
       ↓
VirtualDut / participant → system-wide
```

transport-hop-local 与 interface-local 是两种相邻的局部观察边界，不要求彼此包含。前者观察一个有向 hop
及其 flow-control 状态；后者观察一个完整逻辑接口上的 channel correlation 与 transaction lifecycle。

| 作用域 | 关注内容 | 典型状态所有者 |
|---|---|---|
| Event | 单次观察的字段、枚举、对齐和原子采样合法性 | Event schema / observation policy |
| Transport-hop | 一个有向相邻 hop 的 flit 接纳、credit、activation 和 lane/subchannel 资源 | transport link session |
| Interface-local | 一个接口连接上可判定的 channel、顺序、correlation 和 outstanding | `InterfaceSession` monitor |
| VirtualDut | 一个具名 module 跨端口作出的 decode、store、route、transform 和 completion 决策 | VirtualDut backend |
| System | 多个 module/interface 才能判定的路由闭合、端到端 owner、coherence、progress 和 refinement | SystemProtocol 声明与 system monitor |

源码中的 `ConstraintScope.EVENT`、`TRANSPORT`、`INTERFACE`、`VIRTUAL_DUT` 和 `SYSTEM` 表达这条视图。
`TRANSPORT` 只说明最小判定范围是一个相邻 hop；它不把 transport 变成统一协议层，也不表示
TransportLink 归 InterfaceProtocol 所有。

### 3.1 局部状态、全局声明与参考账本

同一主题可能在几个作用域留下不同形态的数据：

| 主题 | VirtualDut 持有 | SystemProtocol / system monitor 持有 |
|---|---|---|
| 地址路由 | RN/HN/decoder/ICN 实际使用的 SAM、route table、remap state | NodeID 和 address/home 的权威分配、可达性与闭合检查 |
| 缓存一致性 | cache tags/data/permission，真实 directory 或 snoop-filter state | 从外部可见事件更新的 reference coherence ledger |
| bridge/crossbar | FIFO、AW→W owner、ID remap、return table | 经过多个节点后的端到端请求归属和 response return |
| flow control | 接口或 hop 的实际 credit/lease counter | wait-for projection、跨节点 dependency 和 deadlock witness |

reference ledger 需要在名称和 API 上表明其验证用途。真实 directory 是硬件模块时，它仍由对应 VirtualDut
backend 持有；system monitor 可以比较两者，但不成为第二份可随意修改的 directory 实现。

### 3.2 Module 与协议参与者

`VirtualDut` 表示一个具体、具名的 module 边界。协议参与者可能比 module 更细或更粗：

- 一个 module 可以包含彼此独立的 instruction-cache agent、data-cache agent 和配置 agent；
- 一个 agent 可以跨越多个内部 RTL modules，只在若干外部接口处体现其 progress coupling；
- 一个 CHI port 可以分配多个 NodeID；一个互连 module 内也可以同时包含 Home Node 和 transport routers。

“协议参与者”是描述 role/profile、身份 namespace、所拥有接口和 progress coupling 的概念，不必强制对应
一个通用 Python 基类。当前 CHI profile 使用 family-specific participant binding，把一个共享状态的 RN、Home
或 router 绑定到同一 VirtualDut 的多组 `TransportPort`。只有第二种协议族证明字段和生命周期能够稳定复用时，
才适合抽取公共 `ProtocolParticipant` API。无论是否抽取，它都不替代 VirtualDut；只有验证目标要求把参与者
当作独立 topology 节点时，才将它展开成单独的 VirtualDut。

## 4. 表示与运输视图

表示轴描述通信事实从用户意图到传输单元的逐步具体化。协议可以折叠其中若干级，但应明确折叠条件。

| 形式 | 工程含义 | 示例 |
|---|---|---|
| Operation | 协议无关的意图与效果 | `AddressRead`、`AddressWrite`、permission acquire |
| Transaction | 把相关请求、消息、完成和状态变化关联成一次协议生命周期 | AXI AR→R、AW/W→B；CHI read transaction |
| Message | 参与者之间一次有类型的协议交换 | TileLink `Get`、CHI Request 或 Data response |
| Packet | 带网络身份、可独立路由的传输对象 | 带 SrcID/TgtID 的 CHI packet |
| Flit | 由 link/hop flow control 接纳和释放的单位 | CHI protocol flit、link-maintenance flit |
| Phit | 相邻 network devices 间一次 physical-layer transfer | CHI Issue H 的单次 Link transfer |

Transaction 是一组有身份、有开始与结束条件的关系，不是位于 message 外面的强制编码盒。一个 transaction
可以产生多个 messages，消息也可以参与 multi-request 等更复杂关系；只有具体协议 profile 才决定 cardinality。
physical transfer unit、lane beat 或 phit 可以在需要验证 PHY/serialization 时继续展开。普通 AXI/APB 场景可以
折叠 message/packet/flit，不需要为了图形完整而制造空对象。

CHI Issue H 对当前切面给出两个明确的一对一关系：每个 network packet 恰好装入一个 protocol flit，每个
flit 恰好由一个 phit 传送。对象仍需分开，因为 packet 跨 hop 保存 route identity，flit 在一个 hop 上占用
L-Credit，而 phit 属于 physical transfer。`LCrdReturn` 等 link-maintenance flit 不携带 network packet，
只在相邻 transmitter/receiver 间产生和终止。

### 4.1 三类变换需要分开

```text
operation --semantic translation--> operation'
message   --representation codec--> packet --> flit
packet    --transport scheduling--> route + resource usage
```

1. **Semantic translation** 可以改变 operation form、能力或完成方式。例如 AXI burst 被展开成多个 APB
   accesses。`TranslationStage`、`TranslationPlan` 和 bridge executor 负责这类行为。
2. **Representation codec** 在声明的 projection 下保持语义，将 message 编码为 packet/flit，或执行
   split、merge、pack 和 unpack。它需要记录 lineage、header provenance 和重组完成条件。
3. **Transport scheduling** 选择 hop、virtual channel/resource plane、buffer 和 arbitration lease。它影响时序、
   容量与 progress，但通常不修改 operation 的功能效果。

这三类行为可以共享 typed forms、capacity pool 和 lifecycle ledger；它们仍使用不同 contract。这样可以避免
为了复用 bridge stage，将 CHI packetization 错写成有损的协议转译。

### 4.2 CanonicalEvent 的位置

`CanonicalEvent` 是一次已经被 observation 或 attachment 解码的通信事实。它适合统一 trace、constraint 和
causal evidence，但当前的 `kind + payload` 结构不能单独证明该事实属于 message、packet 还是 flit。

typed representation 应作为 CanonicalEvent 的 payload/form contract，或由显式 envelope 关联。当前 CHI
Issue H slice 已分别建立 protocol message、network packet 和 protocol-flit envelope；其他协议无需因此被迫
实例化相同链条。无需为每个粒度复制一套 event/trace 系统；同时也不依赖字段名字猜测粒度。

## 5. CHI 对三张视图的验证

[Arm AMBA CHI Issue H](https://developer.arm.com/documentation/ihi0050/h) 在 B1.1.3 中给出三层职责：

- Protocol layer 生成和处理 transaction、规定 cache state transition、transaction flow 及 protocol-level flow
  control；
- Network layer 把 protocol message packetize，并确定用于路由的 source/target Node ID；
- Link layer 用 flit 在 network devices 之间执行 flow control，并通过 channel 依赖规则支持 deadlock-free
  switching。

同一规范在 B1.3 区分 transaction、message、packet、flit 和 phit；B13.2 又把 link 精确定义为一对
Transmitter/Receiver 之间的单向连接。这些定义直接支持本文的表示/运输轴。

Snoop request 的协议格式不定义 `TgtID`。interconnect 选择 Snoopee 后，Network layer 为每个目的地建立
带显式 target route identity 的 packet copy；Link layer 只负责把该 packet 作为 protocol flit 运过当前
hop。自动选靶、fanout 和 response aggregation 因此不能由 SNP transport channel 推断。

### 5.1 CHI 概念在项目中的落点

| CHI 概念 | Protocol Model 落点 |
|---|---|
| REQ/RSP/SNP/DAT message schema、TxnID/DBID、Retry 与 P-Credit lifecycle | CHI protocol contract；局部部分由 interface session monitor 执行 |
| RN-F/RN-I/HN-F/HN-I/SN/MN 的行为和本地 cache/home 状态 | ProtocolParticipant profile + VirtualDut backend |
| NodeID、系统 address/home assignment | SystemProtocol/elaboration 的 network identity plan |
| RN/HN/ICN 实际 SAM 与 TgtID remap | 对应 VirtualDut backend；由 system projection 校验 |
| message→packet、routing fields | representation codec + network packet form |
| packet→flit、L-Credit、link activation | transport interface/hop contract |
| snoop target selection、fanout、direct data return、Home completion aggregation | Home participant/VirtualDut backend + system transaction session；monitor 只读核对跨节点结果 |
| router buffer、Resource Plane、跨 hop dependency | canonical directed topology + family transport runtime + system analysis |

CHI 的 Protocol Credit 与 Link Credit 需要分开的 resource domain。前者表达 completer 对 transaction resource 的
接纳保证和 retry lifecycle；后者表达相邻 Transmitter/Receiver 间的一次 flit 接纳能力。两者可以复用通用
resource/lease 设施，但不能共用同一计数器或释放条件。

### 5.2 NodeID 与 SAM 的所有权

CHI B3 规定 Requester 通过 System Address Map 确定 TgtID，同时允许 SAM 位于 Request Node 或 interconnect，
interconnect 也可以 remap TgtID。规范还允许一个 Port 拥有多个 NodeID，而每个 NodeID 只能分配给一个 Port。

这带来一项明确的分工：

```text
SystemProtocol:  NodeID uniqueness + address/home authority + reachability
        │ projection / closure check
        ▼
VirtualDut:      implemented SAM + remap table + local routing state
```

系统声明提供权威配置和验证期望；生成式 interconnect 可以从该声明派生 backend 配置，外部 RTL 则公开 typed
projection 供 elaboration 或 monitor 比较。

### 5.3 C2C 的继续扩展

[Arm CHI C2C](https://documentation-service.arm.com/static/691c2cfd69f16e048ca621a4) 在 on-chip CHI 与
chip pins 之间划分 Protocol、Packetization、Link 和 Physical 层。Packetization 可以把多个 message 装入定长
container，Link 可以增加 CRC 和 flit retry，Physical 层处理电气连接、skew 和 training。

这组层次适合建成可叠加的 representation/transport stack，并通过 `SystemProtocol.as_virtual_dut()` 继续递归
组合。它没有要求工程在 SoC 之后固定增加 `ChipProtocol` 层级。

## 6. TileLink 对三张视图的验证

[SiFive TileLink Specification 1.9.3](https://sifive.cdn.prismic.io/sifive/928d6a82-77a9-4291-8b60-5e815429b1ab_tilelink_spec_1.9.3.pdf)
给出了另一组同样合理、但与 CHI 不同的术语：

- agent 是拥有一个或多个 TileLink links 的协议参与者；
- link 是两个 agents 之间完成 operations 所需的一组 channels；
- channel 是单向、同优先级的 message connection；
- agent graph 以 agent 为顶点、以 master interface→slave interface（规范原词）的 link 为有向边，用于论证
  channel priority 和 forward progress；
- 一个 RTL module 可以包含多个独立 agents，一个 agent 也可以覆盖芯片中大量 modules。

TileLink 的 `link` 更接近项目 `InterfaceConnection` 所表达的 channel bundle；CHI 的 `link` 则对应
`TransportLink` 的单向 hop。两个规范对同一术语的使用差异，说明通用公共 API 需要采用更明确的
`InterfaceProtocol` / `InterfaceConnection` 名称。

### 6.1 TileLink 概念在项目中的落点

| TileLink 概念 | Protocol Model 落点 |
|---|---|
| A/B/C/D/E channel message schema 与 request/response correlation | interface-local protocol |
| TL-UL/TL-UH/TL-C、地址空间 capability | endpoint/interface capability + system address claims |
| agent | ProtocolParticipant；与 VirtualDut module 边界独立 |
| agent graph 和 channel priority | SystemProtocol 的 progress/dependency projection |
| crossbar/cache/adapter 的局部转发与状态 | VirtualDut backend |
| per-address 唯一路径、manager ownership、全局 permission | route plan + system coherence monitor |

TileLink 规范允许 NoC 在协议边界上表现为单个 agent，而内部 token ring 或 mesh topology 不进入 agent graph。
因此项目也应区分 protocol dependency graph、外部 topology graph 和展开后的 transport projection。验证目标只观察
NoC 边界时，它是一个 VirtualDut/participant；验证 router buffer 和 route dependency 时，在同一
SystemProtocol topology 中展开 `TransportPort` 和 `DirectedTransportConnection`，再派生只读 transport plan。

## 7. 本项目现有对象的定位

| 当前对象 | 本文中的稳定含义 | 备注 |
|---|---|---|
| `SemanticFragment` | 各作用域共享的 constraint/resource/obligation 组合 | 保留 |
| `InterfaceProtocol` | 一个逻辑接口连接上可判定的协议合同 | 不等同于 CHI Link layer |
| `InterfaceSession` | 上述接口合同的一份可执行状态 | 每个连接实例独立持有 |
| `InterfacePort` | VirtualDut 边界上的完整接口端口 | 关联 InterfaceProtocol role；不表示 CHI transport endpoint |
| `TransportPort` | VirtualDut 边界上的单向 transport 端口 | 声明 family、TX/RX 方向与边界 capability |
| `VirtualDut` | 具体、具名的虚拟 module | 保留 |
| `InterfaceConnection` | 把接口合同的 roles 绑定到具体端口的一份连接实例 | topology edge，不等同于 transport hop |
| `DirectedTransportConnection` | 一次 transmitter→receiver hop 声明 | 与 InterfaceConnection 共用 canonical topology 注册表 |
| `ResolvedTransportPlan` | elaboration 从 directed connections 派生的只读 hop 投影 | 为 family session 提供按名称/端口查询，不成为第二 topology |
| `SystemProtocol` | VirtualDuts、connections、boundary 与系统约束的组合 | 保留 |
| `TranslationStage/Plan` | operation 级语义转译 | 保留，不承担 transport packetization |

五个 `ConstraintScope` 表达判定作用域；接口局部使用 `ConstraintScope.INTERFACE`，单 hop 的 flit/credit/
activation 使用 `ConstraintScope.TRANSPORT`。scope 仍只回答最小观察范围；不能仅凭 scope 名称推断一个对象
属于 CHI 的哪一规范层。

## 8. 公共命名与源码所有权

| 名称 | 稳定含义 | 主要源码所有权 |
|---|---|---|
| `InterfaceProtocol` / `InterfaceSession` | 一个完整逻辑接口的静态合同及其每连接运行状态 | `protocol_model.interface` |
| `InterfaceConnection` | 把接口 roles 绑定到具体 `InterfacePort` 的连接实例 | `protocol_model.system.topology` |
| `TransportPort` / `DirectedTransportConnection` | 单向 transmitter→receiver transport 边界与 hop | VirtualDut boundary / system topology |
| `TransportLink` | 具体协议族解释的单向 flow-control connection | 对应 `protocols/<family>/transport` |
| `VirtualDut` | 具体、具名的 module 边界 | `protocol_model.virtual_dut` |
| `SystemProtocol` | VirtualDuts、connections、boundary 与系统合同的聚合 | `protocol_model.system` |

`NetworkProtocol` 不作为公共顶层名称：它容易与 CHI Network layer 混淆，也不足以覆盖系统的地址、身份、
coherence、clock/reset 和 boundary contract。规范原词 TileLink link、CHI Link layer、link credit 和物理 link
继续按原义使用，不做无边界替换。

具体标准位于 `protocol_model.protocols` 叶包。一个协议族只建立真实场景需要的 interface、representation、
transport、participant 或 system 切面，不要求填满统一目录模板。公共内核不反向依赖具体协议族。

## 9. 实现状态与扩展入口

本文只规定视图和职责，不复制当前 opcode、profile 与测试清单。已经实现的 CHI/AMBA 范围和明确缺口统一见
[实现状态](implementation-status.md)，近期实施依赖见[技术路线](technical-route/08-roadmap.md)，长期研究方向见
[项目 Roadmap](../../ROADMAP.md)。

后续能力仍沿三张视图增加：typed capability 与 identity/home closure 属于构造和系统作用域；更完整的
message/packet/flit codec 属于表示；virtual channel、Resource Plane、C2C reliability 和 PHY lifecycle 属于
transport。它们共享基础语义，但不合并成新的巨型协议对象。

## 10. 规范依据

- [Arm AMBA CHI Architecture Specification, Issue H](https://developer.arm.com/documentation/ihi0050/h)：B1.1.3
  architecture layers，B1.3 terminology，B3 Network Layer，B13 Link Layer，B15 System Coherency Interface；
- [Arm AMBA CHI C2C Architecture Specification](https://documentation-service.arm.com/static/691c2cfd69f16e048ca621a4)：
  B2 interface structures、Protocol/Packetization/Link/Physical layers；
- [SiFive TileLink Specification 1.9.3](https://sifive.cdn.prismic.io/sifive/928d6a82-77a9-4291-8b60-5e815429b1ab_tilelink_spec_1.9.3.pdf)：
  2.1 Network Topology、2.2 Channel Priorities、5 Forward Progress；
- [UCB BAR TileLink overview](https://bar.eecs.berkeley.edu/projects/tilelink.html)：TileLink 对 coherence policy、
  cache controllers 与 on-chip network 的解耦定位。
