# SystemProtocol 组网架构

组网不引入一个与 `SystemProtocol` 竞争的新顶层对象。这里的 network 是 SystemProtocol 内部的 topology
及其派生关系；同一份 topology 可以渲染成星形、树形或传统的“长总线挂设备”视图。

本文同时使用完整逻辑接口侧的 `InterfaceProtocol`、`InterfaceConnection`、`InterfaceSession`，
以及 hop 侧的 `DirectedTransportConnection` 与 transport family/profile。这里的 network 不专指
CHI Network layer；构造依赖、判定作用域与 Protocol/Network/Link 表示栈的分工见
[通信建模的三张视图](communication-scope-and-transport.md)。

## 1. 网络由什么组成

```text
VirtualDut instances
  具体、具名的 module；边界可声明 InterfacePort 或 TransportPort

InterfaceConnection instances
  一份 InterfaceProtocol 的具体使用；把协议角色绑定到具体端口

DirectedTransportConnection instances
  一次单向 transmitter→receiver hop；把 transport family/profile 绑定到具体端口

System boundary
  尚未在本层连接、需要暴露给更外层系统的端口

System semantics
  只有观察多个 connection/module 才能判断的规则
```

一个 AXI/APB/AHB “总线”如果有 decoder、arbiter 或 response mux，这些功能不会隐含在一条抽象长线上：
它们被建成 bridge/fabric VirtualDut。AXI/APB/AHB 一类完整逻辑接口使用 `InterfaceConnection`；
显式展开 CHI NoC 内部时，单向 hop 使用 `DirectedTransportConnection`。两者共用
`SystemProtocol.connections` 这一 topology 权威，transport plan 只是 elaboration 产生的只读投影。

```text
manager ─ connection 0 ─ [decoder/fabric VirtualDut] ─ connection 1 ─ register bank
                                             └──────── connection 2 ─ memory
```

传统 bus-strip 只是这张星形 topology 的一种可视化投影。

### 1.1 Canonical topology 的图示语法

系统拓扑图默认采用接近网表的表达：`VirtualDut` 是 module 节点，`InterfaceConnection` 和
`DirectedTransportConnection` 是两种端口连接边。前者的边类型是 `InterfaceProtocol`；后者显示
transport family、方向与 profile。边的主标签显示协议或 transport family；次标签显示 connection instance 与
两端端口，例如 `sensor_path · crossbar.m_sensor ↔ sensor.axi`。同一种协议出现多次时，独立线条、端口和
instance 名共同区分每一条连接。

```text
[dma.axi] ── AXI4-Lite / dma_path ── [crossbar.s_dma]
```

二端点连接在 canonical topology 中直接画成边。需要专门讲解 `InterfaceConnection` 对象内部的 monitor、profile
或 contract 时，可以把 connection 展开成一张接口卡片；该视图属于协议对象说明图。三个以上 endpoint 共享
同一个通信实体时，可以使用中性 junction 或细长 bus bar 表达 hyperedge。

长条 bus bar 适合表达确实共享信号、广播可见性或统一仲裁域的 segment。AXI crossbar 的每个 ingress 和
egress 是独立接口，默认保留星形连线与显式 crossbar VirtualDut，以便看见并发端口和 response owner。面向
传统总线示意的 bus-strip 仍可由同一 topology 派生，但图例应说明它是折叠投影。

当前公共 `system_bus_strip_dot()` 只接受调用方显式指定的 `SingleIngressAddressFabricBackend`。它从既有
InterfaceConnection、fabric port 和 route window 自动生成长条视图，并在图中标明 canonical topology 仍是
显式星形。这个严格入口避免仅凭“线画得像总线”就推断共享信号、广播或仲裁语义。

单个 constructed VirtualDut 的展开图按边界向内部阅读：

```text
InterfaceConnection → InterfacePort → attachment → backend
```

`InterfacePort` 位于 module 最外层；attachment 存在时紧邻端口，负责协议事件与内部 operation 之间的转换。
多端口 bridge/crossbar 将 ingress 与 egress attachment 分别排在相应边界，不要求它们都占据页面物理顶部。
声明型或外部实现的 VirtualDut 可以只有 typed port，因此图例会把“未建 attachment”和“未知 backend”分别
表示。

### 1.2 Mesh 中谁是点、谁是边

“点”和“边”取决于图正在回答什么问题。项目的 canonical topology 是 module connection graph，因此采用
下面的稳定映射：

| 图中元素 | 模型对象 | 判定依据 |
|---|---|---|
| router、crosspoint、endpoint | `VirtualDut` 节点 | 是可独立实现、保存状态、转发、仲裁或被观测的 module |
| 一次 endpoint-to-router 完整逻辑接口 | `InterfaceConnection` 边 | 是两个具体 interface port 之间的一次接口连接 |
| AXI/APB 或折叠后的 packet interface 规则 | `InterfaceProtocol` 边类型 | 规定一条局部接口连接上允许的通信语言 |
| 展开 router transport 后的一次 TX→RX hop | `DirectedTransportConnection` 边 + family transport session | 声明 hop，并执行 flit flow control、VC/RP 和 hop resource |
| north/south/east/west/local | `InterfacePort` 或 `TransportPort` | 表示边落到 module boundary 的位置和角色/方向 |
| router 与本地 endpoint 的组合 | tile/composite 投影 | 用于 floorplan 或阅读分组，不自动增加运行对象 |

因此，mesh router 与 address crossbar 在“多入口、多出口、需要仲裁”方面相近，但路由依据和 transport 状态
不同。mesh router 通常按 destination/NodeID、route function 与 virtual channel 选择下一跳；address crossbar
按地址窗口选择 endpoint。二者可以复用 Route、Store、Arbitrate、Correlate 等构造思想，不能只因外形相似
就复用同一个 backend。

设备在产品图中常被画在网格线旁或 tile 内。canonical topology 不把设备隐含地“挂在”某条经过的
router-to-router transport link 上，而是保留一条独立 local interface connection：

```text
[endpoint VirtualDut] ─ local connection ─ [router VirtualDut]
                                           │
                            neighbor transport connection
                                           │
                                    [router VirtualDut]
```

协议事务图会采用另一种投影：RN、HN、SN 等协议参与者可以成为时间线或消息图的点，而 transit router 被折叠。
这不改变 module topology 的所有权，只是隐藏了当前问题不关心的运输节点。

### 1.3 CHI 的 message、packet 与 hop transport

CHI 展开 NoC 时，同一笔通信会同时出现在协议、网络和相邻 Link 三个作用域。它们共享 lineage，但不共享
状态所有权：

```text
typed protocol message
       │ packetize：增加逐份 route identity
       ▼
network packet
       │ wrap：占用相邻 Link 的 flow-control unit
       ▼
protocol flit ── one directed hop ── protocol flit
       │
       └─ 在 CHI Issue H 中，一个 flit 对应一个 phit
```

一个 protocol message 可以形成一个或多个 network packets。每个 packet 拥有可独立路由的 source/target
identity；router、route table 和 network lineage 消费这个对象。CHI Issue H 又规定每个 protocol packet
恰好装入一个 protocol flit，并且每个 flit 由一个 phit 传送。这两个一对一关系不会合并对象：L-Credit、
activation、backpressure 和 deactivation 是逐 hop flit 生命周期，route identity 与 packet copy 则在跨 hop
网络中保持。当前 executable profile 采用一份 logical message 对应一个 packet；未来 multi-packet DAT
需要补 fragment/DataID/字段一致性以及 splitter；transaction/session 还要负责 reassembly、缺失/重复/乱序
检查和 terminal retirement。以 64B line 的 full-width data path 为例，128/256/512-bit DAT payload
通常分别形成 4/2/1 个 packet。它是表示与 transaction aggregation 的增量，不否定当前 packet/flit
网络的可运输性。类似地，opcode/conditional-field **encoding inventory** 属于表示；若声称 opcode
可执行，还必须同时给出 lifecycle、capability/flow、状态效应和 witness。

`LCrdReturn` 一类 link-maintenance flit 不携带 network packet。它只在当前 transmitter 与相邻 receiver
之间归还 Link resource，不经过 router，也不成为端到端 transaction 的 protocol message。当前模型同样不把
physical phit 展开成 raw pins、lane 或 PHY transfer；`AtomicFrame` 观察的是 normalized Link 边界。
这些 lowering 属于 observation/external-integration，并不构成 CHI participant lifecycle 或 resolved
network 的功能完整性条件。

SNP 给出了保留这些层次的直接理由。Snoop request 的协议格式不定义 `TgtID`，Snoopee 由 interconnect 选择。
因此 system/network construction 为每个选中的 Snoopee 建立一份显式 packet copy，并把选定 NodeID 放入
packet 的 `target_id`；相同的 typed SNP message 可以被多份 packet 引用。当前 CHI slice 已经支持
`SnpShared/SnpUnique/SnpNotSharedDirty/SnpCleanInvalid/SnpMakeInvalid` 表示、SNP channel 的
activation、L-Credit、
FIFO/reservation、背压和 capture/drain。受限 coherent Home 会从显式 directory holder 中选择目标，
生成 per-target packet，并聚合 clean response 或 dirty data。clean Shared/Unique、dirty unique
responsibility transfer 和 no-SD `ReadNotSharedDirty` 都能由组合 session 经 resolved network 逐份运输。
coherence-domain 成员已由 authority resolver 派生为有限 Snoopee set；stateful snoop filter、router
multicast、动态成员变化、shared-dirty state 与 forwarding lifecycle 都不由 transport 自动补出。其中 snoop filter
是 Home/ICN VirtualDut 维护的 cache-presence/选靶结构；当前 exact directory holder set 是 reference
oracle。容量型 filter 的假阳性只产生额外 Snoop，若依据 filter 抑制必要 Snoop，假阴性会破坏一致性。
router multicast 是 network forwarding 机制，动态 membership 是 SystemProtocol authority。`SD`/Owned
属于可选 coherence-state/policy；DCT（Direct Cache Transfer）是可独立增加的 forwarding
transaction/capability，不依赖 Owned。

## 2. 五个构建阶段

### 阶段 A：声明单模块边界

先独立构造 VirtualDut：按边界类型确定 `InterfacePort + InterfaceProtocol`，或
`TransportPort + transport family/profile`，再声明 role、attachment binding、backend 和对外
capability。这一阶段不需要知道模块将来连接到谁。

单模块能够长期稳定的关键，是 network 只消费它的边界投影，不反射 backend 私有状态。以后增加网络
route 或 wait-for 分析时，模块内部 AddressSpace、FIFO 实现或外部 RTL 代理不需要随之重写。

### 阶段 B：声明连接意图

当前使用 `SystemProtocolBuilder` 作为显式装配入口：

```text
add_dut(vdut)
connect(link_name, protocol, role -> port reference)
connect_transport(hop_name, family, transmitter, receiver, profile)
expose(boundary_name, port reference)
add_semantics(fragment)
build() -> SystemProtocol
```

当前 Builder 可以显式加入 DUT、两种 connection、address claim，并通过注入 factory 从 `AddressRouterContract` 构造
address router。对于 bridge，目标 lowering 才会在调用方提供事务转译 plan，或授权一组可接受的
conversion/scheduling/storage policy 后编译 plan，并展开一个 bridge VirtualDut 与两条 InterfaceConnection。生成节点
仍进入最终 topology，不成为 runtime 中不可见的 adapter，也不改变 `SystemProtocol` 作为 lowered 语义对象的
定位。预先装配好的具名 recipe 仍可作为便捷入口，但不作为协议对 N² 扩张的核心机制。

### 阶段 C：elaboration

elaboration 将逐步分成几类可解释检查：

1. **结构闭合**：名称、端口引用、唯一占用，以及 interface role/protocol 或 transport
   direction/family 一致；当前已实现；
2. **interface compatibility**：event/channel/参数形状是否可以直接连接；当前要求相等协议声明；
3. **capability closure**：宽度、burst、ID、ordering、byte enable、clock/reset 能力是否匹配；通用
   InterfacePort algebra 待实现，CHI family 已先闭合 feature 所需的 participant offer 与 channel flow；
4. **address closure**：显式 `AddressClaim` 与 `AddressRouterContract` 已支持 route window、重映射和
   direct-neighbor 唯一覆盖；generated address router 的 backend projection 已在 construction 时核对，
   多跳、动态 route 和 external/opaque backend projection 核对待实现；
5. **construction provenance closure**：若 Builder 已展开 bridge，验证生成节点、connections 与选择依据完整；
   core elaboration 不自行搜索或插入 translation stage；待实现。

### 阶段 D：运行

当前 `SystemSession` 已经可以：

- 为每条 InterfaceConnection 建立独立 InterfaceSession；
- 根据 channel direction 找到目标端口；
- 执行目标 VirtualDut backend；
- 传播立即 emission，直到队列为空；
- 记录逐连接事件和因果边。

它目前适合同步、立即反应的点到点和微型网络，也能通过 caller-owned `DutAdvanceAction` 推进 queued
responder 与 scheduled crossbar 的延后 emission。自主 wakeup、定时 latency、多时钟、延后 emission 的完整
跨 connection lineage 和整个多连接 cascade 的事务回滚尚未纳入统一 runtime。

根 `SystemSession` 当前只执行 `InterfaceConnection`。CHI Issue H 的 `ChiTransportNetworkSession`
则消费 `ElaboratedSystemProtocol.transport_plan`，执行调用方声明的 directed hops 和 router 绑定。
它不固定 line、ring 或 mesh；这些形状是 recipe/fixture。受限的 `ChiReadNoSnpSystemSession` 已在 family
内部组合 requester ledger、Home participant、router 与 transport state，并以轮转 microstep 调度一个
direct-Home read lifecycle。`ChiCoherenceNetworkSession` 进一步组合 clean 与受限 dirty RN/Home
participant 和同一 transport network，以显式 pending egress batch 保存多 Snoopee fanout，并逐 packet
接受网络背压。当前组合已覆盖 clean Shared/Unique、dirty unique responsibility transfer 和 MESI no-SD
dirty-to-clean-shared 路径。
这些对象仍是 CHI family runtime，不扩张为通用 `SystemSession`；两类 runtime 的统一 scheduler 仍待更多
协议场景证明。

### 阶段 E：网络分析

当 capability、资源和 blocked reason 都有稳定投影后，再增加：

- address reachability；
- request owner / completion return；
- buffer、credit、outstanding occupancy；
- wait-for graph 与 deadlock witness；
- boundary hide 后的行为 refinement。

这些是 SystemProtocol/scenario 的派生验证 property，不应要求 InterfaceProtocol 或单个 VirtualDut 预先
知道完整网络，也不是某个 CHI opcode 或现有 route 可执行的前置条件。

## 3. System 对模块边界提出什么要求

组网会发现单模块声明阶段看不到的要求。例如一条地址路径可能要求 bridge 保留 Non-secure 属性，多个
coherent participant 需要唯一的 NodeID，两个直连端口也需要兼容的 clock/reset domain。这里需要把
“系统拥有的事实”“模块承诺的能力”和“线上流动的消息”分开，避免把它们都塞进 VirtualDut 的一个
`attributes` 映射。

| 事实类别 | 权威位置 | 典型内容 | 如何作用到模块 |
|---|---|---|---|
| 全局 authority | SystemProtocol 的 system intent/plan | address/home 分配、dynamic multi-Home、SAM（System Address Map）remap、NodeID namespace、coherence/DVM membership、security zone、QoS policy、clock/reset topology | elaboration 为相关 participant、port 或 backend 产生具名 projection |
| boundary capability / requirement | VirtualDut、ProtocolParticipant 或 InterfacePort 的边界合同 | width、burst、ID、outstanding、ordering、coherent opcode、security/QoS class、domain compatibility | 比较模块的 offer 与网络路径的 requirement；不满足时给出 construction diagnostic |
| per-transaction field/message | InterfaceProtocol event、typed operation 或 typed protocol message | `AxPROT`、`AxCACHE`、`AxQOS`、`AxDOMAIN/AxSNOOP`、CHI opcode/TxnID/address、interrupt notification | source backend/attachment 发出；接口或表示 contract 检查，bridge stage 显式 preserve、rewrite、default、drop 或 reject |
| per-packet route identity | CHI network representation 与 resolved route plan | source/target NodeID、packet copy identity；SNP 的选定 Snoopee target | system/network construction 生成 packet，router 按显式 route identity 转发；不回写 protocol message |
| local executable state | 对应 VirtualDut backend | cache tag/data/permission、真实 directory、SAM lookup/cache、snoop-filter、bridge FIFO、owner table、arbiter state | backend 依据输入和本地配置更新；SAM/snoop-filter 的本地实现不取代 SystemProtocol 的 address/Home 与 coherence-domain authority |
| system monitor ledger/property | stateful system monitor | 稀疏 owner/shared/dirty reference ledger、跨 connection transaction owner、response aggregation、PoC/PoS ordering、wait-for/fairness | 从系统可见事件更新，用来核对多个模块共同形成的行为 |

`ProtocolParticipant` 是这里的逻辑协议参与者。CHI Issue H 已先建立 family-specific
`ChiBehaviorFacet`：transaction 与 forwarding facet 可以组合在同一 VirtualDut 上，并通过
`ChiParticipantBinding` 关联多组 transport ports。`ChiResolvedIdentityPlan` 已闭合 NodeID ownership；
flow projector 与 feature resolver 再核对所需 channel path 和 participant behavior offer。它们仍留在 CHI
家族，因为 NodeID、REQ/RSP/DAT 和 RN/Home role 都是具体假设。一个 VirtualDut 可以包含 instruction/data
两个 cache participant，一个 CHI port 也可能承载多个 NodeID。普通 AXI/APB 网络不需要为了统一形式而创建
participant；等第二种协议提出相同的 identity/facet 查询后，再判断哪些字段值得上提通用层。

### 3.1 Elaboration 产生显式结果，不修改既有 VirtualDut

System 允许派生配置和要求，例如分配 NodeID、解析 address→home、确定某条路径所需的属性保持能力。这些
结果应进入带 provenance 的不可变 elaboration 产物：

```text
SystemIntent
    │ elaborate
    ▼
ResolvedSystemPlan
    ├─ port_requirements
    ├─ participant_assignments
    ├─ backend_projection_expectations
    └─ system_monitor_configuration
```

生成式 bridge/fabric 可以从同一份 resolved plan 构造本地 route、identity 或 policy 配置；外部 RTL/RPC
VirtualDut 则公开 boundary projection，供 elaboration 与期望比较。发生差异时报告 address、identity、domain
或 capability closure 失败。这个流程不会在 `SystemProtocol` 构造完成后修改 frozen VirtualDut，也不会同时
维护一份可自由变化的 system route table 和另一份不受核对的 backend route table。

当前已有三项具体结果：`ElaboratedSystemProtocol.address_plan` 保存显式
ingress×route×direct-neighbor claim 路径。生成式 address router 由
`SystemProtocolBuilder.construct_address_router()` 把同一个 `AddressRouterContract` 交给注入 factory；factory
返回的 backend 必须公开 `AddressRouterBoundaryProjection`，Builder 会先比较实际端口/route，再注册 DUT 与
contract。当前 AXI4-Lite witness factory 直接复用 `contract.routes`，projection 从 backend 配置派生。
`ElaboratedSystemProtocol.transport_plan` 则从 canonical `DirectedTransportConnection` 派生具名 hop 与
incoming/outgoing 查询，不维护第二份 topology。CHI family 的 `ResolvedChiSystem` 再组合 facet、NodeID
identity、所需 flow 与 participant capability，供 read/retry runtime 消费同一份构造证据。更广的
`ResolvedSystemPlan` 仍是目标职责名，后续再聚合 typed
capability、identity、domain、participant 和 monitor 配置，不把它们先塞进一个无类型通用字典。

### 3.2 System 不直接合成协议或控制信号

当前和目标运行语义都把线上动作归给通信参与者。根 `SystemSession` 根据 InterfaceConnection 转发
VirtualDut 发出的 canonical event；CHI family session 根据 resolved directed hops 搬运 network packet，
并在每条 hop 上显式包装/解包 protocol flit。Decoder、Home Node、
interrupt controller 或 router backend 决定何时从哪个端口发出
新的 event。System monitor 可以据 topology 与全局 authority 判断“应该出现哪些 snoop/response”，但它的
verdict 不冒充实际模块输出。

以缓存一致性为例：

- `domain/snoop/opcode` 的字段与单接口 correlation 属于 InterfaceProtocol 或相应 typed representation contract；
- cache permission、真实 directory 或 snoop-filter 属于相应 participant 的 VirtualDut backend；
- address→home、coherence membership 和 NodeID 唯一性属于 system authority；
- interconnect/Home backend 依据这些配置选择具体 coherent participants，并为每个 Snoopee 发出显式
  SNP packet copy；
- system monitor 核对 fanout、response aggregation 和全局 owner/shared/dirty 演化。

当前已实现 directory 选靶、per-Snoopee packet copy、clean SnpResp 与 dirty SnpRespData 聚合、
`I/SC/SD/UC/UCE/UD` permission、Home pending/commit 和稳定点 directory/cache 检查，并能经 resolved 多 hop
network 自动运输。`ReadNotSharedDirty→SnpNotSharedDirty→SnpRespData_SC_PD→Home pending 接管
dirty data/responsibility→CompData_SC→CompAck→Home backing/directory commit` 是当前 no-SD MESI
路径。当前 Home 固定选择吸收 PassDirty 并返回 `CompData_SC`，这是规范允许结果的受限子集。普通
clean `ReadShared` 与任一允许 `UD` 的 feature 组合仍在本 profile 之外。
`SC→ReadUnique→UC→local write→UD` 与保留本地数据的 `SC→CleanUnique→UC→local write→UD` 已实现；
clean `ReadUnique` 的单次 Retry 也已经经 resolved XP topology 自动闭合 RetryAck、PCrdGrant、
credited reissue 与原有 SnpUnique lifecycle；显式 `UD` writeback 已经经同类 topology 闭合。一般
same-line transient/hazard 与 deliberate dirty invalidate 是后续 lifecycle/profile；自动 dirty
victim/writeback scheduling 是可选 Cache VirtualDut policy；stateful snoop filter 是 Home/interconnect
backend policy；router multicast 是 network forwarding 扩展。一般 `SD`/Owned 是 no-SD MESI 之上的
coherence-state/policy；forwarding snoop/DCT 则是可独立增加的 CHI lifecycle/capability。

clean `WriteEvictFull(CAH=0)` 也已作为独立 REQ/RSP/DAT feature 闭合：调用方先显式选择一条 resident
`UC` line，Home 用 `CompDBIDResp` 分配 DBID，RN 发出 full-line `CopyBackWrData_UC` 并进入 `I`；
Home 将数据安装到协议无关的 Snoop-domain clean-residency core，同时保持 reference backing
payload/version 不变。该 feature 不产生 SNP traffic，但 resolver 仍要求所选 Home authority 显式绑定
coherence domain；membership 继续属于 SystemProtocol。与另一 coherence transaction 组合时，pending
WEF 已可接纳 pre-DBID `SnpUnique`/`SnpCleanInvalid`/`SnpMakeInvalid`，保留 CopyBack correlation，
再以零 payload 的 `CopyBackWrData_I` 退休；SNP flow 仍归触发 Snoop 的 feature。Home 对 cancel
只释放 DBID，不改 directory、backing 或 clean residency。当前固定 sparse retain，不包含自动
victim/replacement、容量策略或下游 read hit；这些属于可选 Home/Cache VirtualDut policy。`CAH=1`、
post-DBID Snoop、Retry/error 与级联 eviction 则属于后续 lifecycle/profile。

`WriteEvictOrEvict(CAH=0)` 也已作为独立 feature 闭合。Requester 从 resident `UC` 或 clean `SC`
发起，`LikelyShared` 与 participant permission/directory holder 必须一致；显式 Home policy 可选择
`CompDBIDResp→CopyBackWrData_{UC,SC}` data outcome，或 `Comp_I→CompAck` no-data outcome。前者安装
Snoop-domain clean residency，后者不搬运数据；两者都只删除 requester authority、使 RN 进入 `I`，
并保持 reference backing payload/version 不变。resolver 同时闭合 REQ、Home→Requester RSP、
Requester→Home DAT 与 CompAck RSP 四条 flow，`UC/SC × data/no-data` resolved witness 各恰好运输三个
packet。response 前的同址 invalidating Snoop 另由 direct 双 Requester witness 闭合：RN 保存
`CANCELED_I`，迟到 data/no-data outcome 分别形成零载荷 `CopyBackWrData_I`/`CompAck_I`，Home
只退休旧 correlation。当前不含 post-response/其他 Snoop phase、Retry/error、CAH=1、容量驱动
outcome policy 或自动 replacement。前四项限制 WEOE profile，自动 replacement 是可选 VirtualDut
policy；二者不合并为一个网络可用性判断。

clean `Evict` 已作为独立 REQ/RSP-only feature 闭合：RN 从 `UC/UCE/SC` 先转 `I`，Home 只条件删除
matching clean holder 并返回 `Comp_I`；stale 或目录明确标记为 shared-dirty responsibility 的 hint
no-op，且不产生 SNP/DAT/CompAck 或 backing update。最小
direct topology witness 证明这两条 flow 可由同一 resolved network runtime 自动推进。独立 Retry
modifier 另闭合 `Evict→RetryAck→PCrdGrant→AllowRetry=0 重发→Comp_I`：拒绝阶段不改
directory/backing，Grant 预留真实 Home capacity，system 对两个 retry response 使用一次性 exact packet
evidence；五 packet witness 仍为零 SNP/DAT/CompAck。

`MakeUnique` 也已作为独立、无 DAT 的 feature 闭合。REQ `MakeUnique(0x0C)` 不携带写数据，requester
另存 RN-local 512-bit store intent；Home 对实际 peer 发 `SnpMakeInvalid(0x0A)`，peer 无论原来是否 dirty
都进入 `I` 并只返回 `SnpResp_I`。Requester 收到 `Comp_UC` 时原子覆盖/安装 intent 为 `UD` 并发送
`CompAck`；Home 到 Ack 才提交 requester unique authority，backing payload/version 不变。resolved
dirty-peer witness 恰好运输 REQ、SNP、SnpResp、Comp、CompAck 五个 packet，确认零 DAT。规范 expected
initial requester state 为 `I/SC/SD`；当前模型还允许 `UC/UCE`，拒绝 `UD`。feature dependency
独立于 CleanUnique；若与 clean ReadUnique/CleanUnique base 组合，当前 construction 因 MakeUnique 可产生
`UD` 而分别要求 dirty-unique/shared-dirty modifier。MakeUnique 与 MESI ReadNotSharedDirty 的双向
same-line transient 尚未闭合，当前 construction 拒绝同时选择。这些是阶段 closure，不是协议永久禁配。

这里仍按三种投影保存权威：message/opcode/field 与 transaction-local correlation 属于 typed
representation 和完整逻辑接口合同；cache/directory/backing/pending 属于 participant VirtualDut；
NodeID、Home/domain authority、feature/flow closure 和跨节点 invariant 属于 SystemProtocol。
`TransportLink` 只表示一条有向 transmitter→receiver hop，不解释 coherence opcode；`InterfaceProtocol`
是项目中完整逻辑接口的作用域名称，不是 CHI 规范 Link layer 的别名。

当前 Home reference backing 已足以检查上述 coherence slice 的 payload/authority invariant。若验证目标要求
观察独立 memory protocol commit，应另构造 SN participant、topology-visible HN→SN flow 与 system witness；
这是下游 system-integration slice，不把 AXI/APB memory backend 暗绑成 Home state，也不作为现有 RN↔Home
网络 closure 的前置条件。

QoS 也沿相同边界展开：`AxQOS` 是事务字段，仲裁算法和队列状态属于 interconnect VirtualDut，端到端
fairness、带宽或 latency 目标属于 system/scenario property。Security transaction intent 由 attachment
解码，endpoint/firewall backend 作实际允许或拒绝决定，SystemProtocol 检查 security-zone reachability。

clock/reset 通常形成独立的 control topology。`InterfacePort` 可以声明所在 domain，系统检查直连兼容性并
要求不兼容路径经过明确 CDC/reset-isolation module；观察层再把 RTL pin 采样 lowering 为模型动作。Interrupt
若使用专用线，应建成 notification/control interface 并经过 interrupt-controller VirtualDut；MSI 则自然表现为
地址写操作。两者都不需要向每笔 AMBA address transaction 追加隐式字段。

当前 CDC elaboration 与异步采样仍是跨协议的通用 control-topology/观察方法议题；RTL pin、physical
phit/lane 和 cycle timing 则是 observation/external-integration。它们不计作 CHI lifecycle 或 logical
network 的功能完整性缺口。

### 3.3 当前代码边界

当前实现已经提供单一 topology、interface 同步事件传播、typed address resolution 和 directed
transport projection；其余 property 仍未闭合：

- `InterfacePort.capability` 仍是 `object | None`，没有 typed offer/requirement algebra；
- `clock_domain`、`reset_domain` 只是端口字符串，elaboration 尚未检查相连端口或 CDC/isolation；
- `InterfaceConnection.parameters` 只拒绝未知 key，尚未验证或应用 parameter value；
- `ElaboratedSystemProtocol` 保存组合 semantics、typed `owner_by_port`、`ResolvedAddressPlan` 与
  `ResolvedTransportPlan`；结构检查覆盖两种 connection 的端口类型、方向/role、family/protocol、唯一占用和未连接端口；
- `SystemSession` 执行 InterfaceSession monitor 和 VirtualDut backend，没有 stateful system monitor、按字段路由、
  broadcast/fanout 或 clock/reset scheduler；
- CHI family session 已执行共享 Link activation 下的 REQ/RSP/SNP/DAT mixed-channel connection、有限 router
  与原子 admission；direct-Home read/retry slice 已有 participant facet、NodeID ownership、flow/capability
  closure 和受限 family scheduler。clean `ReadShared/ReadUnique` 已进入 participant lifecycle，并由
  topology-driven composition scheduler 自动推进 REQ/SNP/RSP/DAT/CompAck；dirty unique transfer 与
  no-SD `ReadNotSharedDirty` 也已闭合，其中后者以 CompAck 后的 Home backing/directory commit 结束
  dirty responsibility；clean/shared-dirty-peer `CleanUnique` 与显式 `UD` writeback 已闭合经 XP 的
  REQ/SNP/RSP/DAT route 和相应提交结果；clean `WriteEvictFull(CAH=0)` 则经 RN↔Home direct
  topology 闭合 REQ/RSP/DAT，使用独立 clean residency core 且不提交 reference backing；
  `WriteEvictOrEvict(CAH=0)` 另闭合四条 capability flow、Home-selected data/no-data outcome 与四个
  `UC/SC × outcome` 三 packet witness，同样不提交 reference backing。
  clean ReadUnique Retry modifier 复用 transaction-local
  Request-Retry/P-Credit 合同，Home grant 与 requester reissue 由同一 composition scheduler 自主推进；
  clean Evict Retry 以独立 feature/policy gate 复用同一 ledger，并闭合 exact RetryAck/P-Credit
  correlation 与五 packet resolved witness；
  direct address-backed read 已把 authority 内 decode/access failure 映射为沿原 DAT route 返回的
  `CompData_I(NDERR)`；coherent `ReadUnique` 也已闭合 pre-snoop
  `CompData_I(NDERR)→CompAck`、零 SNP 与 cache/directory/backing 不变式。MakeUnique 的独立
  Requester/Home/Snoopee capability、五类 flow、participant lifecycle 和 dirty-peer topology witness
  也已闭合，且不依赖 CleanUnique。Retry 与 NDERR modifier
  现可联合闭合经 XP 的六 packet 路径；direct 双 Requester witness 另证明等待 P-Credit 时可响应独立
  同址 Snoop 而保留 correlation。当前 CHI lifecycle/profile 不含 coherent cancel、DERR 或同一 accepted
  request 已发出 Snoop 后的 error，
  或超出该窄 witness 的 Retry/Snoop 到达次序，也未闭合 MakeUnique Retry/error/MTE Update/partial-write、
  deliberate dirty invalidate、`WriteEvictFull` CAH/post-DBID-Snoop/Retry/error modifier、
  `WriteEvictOrEvict` post-response/其他 Snoop phase、Retry/error、CAH=1、容量驱动 outcome policy 与一般
  same-line transient/hazard；其 response 前 invalidating-Snoop cancel 已以
  `CANCELED_I→CopyBackWrData_I/CompAck_I` 闭合。通用 participant plan 和 dynamic multi-Home/SAM 是
  system construction；自动 dirty victim/writeback 是可选 VirtualDut policy；`SD`/Owned 是
  coherence-state 扩展，forwarding/DCT 是可选 CHI lifecycle/capability；多 waiter policy/fairness 与
  network deadlock analyzer/verdict 是验证 property，但被建模网络仍须满足适用的 channel-dependency 与
  forward-progress 合同。它们仍待各自场景驱动，但不是一组等价的
  CHI network blocker；
- 多跳 address/coherence plan、通用 `ProtocolParticipant`，以及 external/opaque VirtualDut projection 核对
  仍待实现；generated address router 的 route projection 和 CHI-family identity plan 已先行接通；
- translation 内已有 V1 `CapabilitySet/CapabilityRelation` 和 `SemanticEffect`，但尚未与 InterfacePort capability
  或 system closure 接通。

近期可以沿现有 address slice，让 bridge/crossbar 的 typed plan 继续公开 request/completion capability、
attribute effect、ordering 和 resource projection，再由 elaboration 消费这些边界事实。缓存一致性和显式
NoC 需要的 participant/global ledger 可以在首个多接口场景中继续收敛，不阻塞普通 AXI/AHB/APB 主线。

## 4. integration 在组网中的位置

Attachment 只服务一个端口：把该 interface 的 canonical event 转成 backend operation，再把结果编码回来。
Integration 是协议与 VirtualDut 的依赖汇合区；其中 recipe 可以组合多个 attachment 与跨端口 backend。
SystemProtocol 连接 `InterfacePort`，不会识别 `ApbCompleterAttachment`、AXI AW/W join state 等私有类型。

桥接时会同时出现三类工作：

- 每个端口的协议 codec、wire fragment join 和 transaction/correlation context，属于两侧 attachment；
- operation 的 burst fanout、地址/属性变换和 completion fold，属于 typed stage/plan；
- parent queue、serialize、lease、lineage、ID remap 和 owner return，属于 bridge executor/backend。

后两类行为需要同时观察两个端口。把它们塞进任一 attachment，会让两侧各自只看到半个 bridge，无法拥有
统一的资源和完成关系。

## 5. 地址星形网络与 N×M crossbar

一个最小、可解释的星形地址网络如下：

```text
injected manager
      │ APB
      ▼
single-ingress AddressFabric
      ├─ APB → RegisterRegion
      └─ APB → MemoryRegion
```

这个示例分离验证 topology、地址解码、owner return、decode error 和可视化，不要求同时解决异构 bridge。
AHB 与 AXI4-Lite 已能复用同一 fabric backend；AXI4 burst endpoint 使用协议相关 backend。
AXI4-Lite→APB 首个 bridge 已验证异构 attachment、route、owner return 与错误映射。full AXI4→APB
进一步加入有界父事务队列、AW/W join 后的 burst split、严格串行 APB 调度和 AXI completion 聚合。
serial bridge 的 translation parent pool 目前仍把容量耗尽报告为 VirtualDut fault，尚待迁移到公共
admission policy。queued responder 和 scheduled crossbar 已默认返回 typed `BLOCK`，也可显式选择有序
deferred error 或 `FAULT`。这些 event-level 结果还没有 lowering 为 READY/HREADY/PREADY；narrow/width
conversion 和 wait-for 投影也仍需在后续边界/runtime 中闭合。

当前 `ScheduledAddressCrossbarBackend` 已把共享出口所需的 admission、per-egress round-robin、active slot
和 response owner 放进同一个协议无关 backend，而不是把多组独立 bridge path 并排后推断共享调度。
`build_axi4_lite_address_crossbar_vdut()` 为它装配 N 个 AXI4-Lite subordinate attachment 和 M 个 manager
attachment；一次显式 advance 可以同时 grant 不同 egress，同一 ingress/egress 保持最多一笔 active。

System 侧用 `AddressRouterContract` 显式声明 ingress、egress 和 route，并把每条重映射后的 route 闭合到
对应 egress connection 上唯一的 direct-neighbor `AddressClaim`。这个 resolution 不产生 crossbar 事件；请求入队、
仲裁和 owner return 仍由 VirtualDut backend 执行。当前具体 N×M recipe 只覆盖 AXI4-Lite single access。
Full AXI 还需要 AW/W route ownership、ID namespace/remap、burst preservation 和同 ID response ordering，
不属于该 slice 的自然别名。

## 6. 返回路径与层级边界

“同一路返回”只有在这条路仍能唯一确定原 source 时才足以消除返回表。多个入口共享一个 AXI egress 时，
从该 egress 的 B/R channel 返回只能确定下游出口，不能单独确定最初使用哪个 ingress。

常见实现可以按 source identity 的保留方式归纳：

| 方法 | 保存的关系 | 适用边界 |
|---|---|---|
| 独占返回路径 | path 本身就是 source identity | 每条路径只有一个 owner，或一个 virtual channel 只服务一个 source |
| 单活动 owner | egress → ingress | 无 ID、每个出口一笔活动事务；APB、简单 AHB/crossbar profile |
| AXI ID 前缀 | downstream ID = ingress index + original ID | 下游允许扩展 ID，返回时可直接拆出 ingress |
| ID remap table | downstream tag → ingress、原 ID、顺序 context | 下游 ID 宽度固定、允许多 outstanding |
| 串行化 | 每个 egress 或 egress+ID 同时只有一个 owner | 状态较小，但并发与 head-of-line 行为更受限 |

AXI 的 request/response 本来跨 channel：AR 对应 R，AW/W 对应 B。W 没有 WID，因此即使 B/R 使用 ID
前缀，仍需要 AW→W route FIFO 或等价的 burst-owner 状态。AHB/APB 没有 AXI 式 transaction ID，通常在
地址/setup 被接受时锁存 owner，并在 data/access 完成后释放；burst、lock 或 wait-state 会延长这份租约。

作用域按观察范围区分：

- `InterfaceProtocol` 检查一个逻辑接口连接内的 AR→R、AW/W→B、AHB phase/burst 等关系；
- crossbar `VirtualDut` 决定本模块收到下游 completion 后从哪个 ingress port 发出，并维护本地 owner/ID；
- `SystemProtocol` 检查经过多个节点后是否回到原发起者、地址路径是否闭合，以及多个节点资源形成的
  wait-for/deadlock。

因此，多端口不会自动把 crossbar 变成 `SystemProtocol`。隐藏内部实现时它仍是一个 VirtualDut 节点；
只有当 decoder、arbiter、request/return network 被展开为独立 module/interface connection 以供观察时，这些
内部对象才组成一个可再封装的子 SystemProtocol。

当前 `InterfaceConnection` 把一个 protocol role 的全部 channel 绑定到一个端口。
普通 crossbar 在上下游分别终止一条 point-to-point interface connection，再由 backend 跨 connection
correlation；它不把一个 AXI interface 的 AR 放在 connection A、R 放在 connection B。若未来要显式建模
request/response 独立 NoC，应在同一 SystemProtocol topology 中使用不同
`DirectedTransportConnection`，并增加端到端 transaction correlation；一个 InterfaceSession 不跨未知 hop
隐式闭合 obligation。

## 7. Construction lowering：把连接意图展开成显式网络

目标便捷组网 API 可以接受“连接这两个端口，并允许某类事务转译”的意图。当前
`SystemProtocolBuilder` 已实现显式 DUT、两类 connection、address claim/router 的 construction，并允许注入 factory 从同一
router contract 构造 crossbar；自动选择 transaction translation 的 bridge lowering 仍按下图作为后续边界：

```text
connection intent + endpoint ports + injected translation catalog
                         │
                         ▼
            compile an immutable TranslationPlan
                         │
                         ▼
          bridge VirtualDut + two InterfaceConnections
                         │
                         ▼
              ordinary SystemProtocol
                         │
                         ▼
                 core elaboration
```

Construction lowering 是声明展开，不是 runtime adapter。它与 core elaboration 的边界是：

| 阶段 | 责任 |
|---|---|
| Builder lowering | 在调用方授权范围内选择 codec/stage/policy，生成 bridge 和 connections，记录 provenance |
| core elaboration | 检查已经展开的名称、引用、role、port ownership、protocol 和 namespace 闭合 |
| 根 `SystemSession` / family transport session | 分别运行已解析的 interface connections / transport plan，不因协议不匹配而修改网络 |

默认连接策略仍是 direct。只有调用方显式授权 transaction translation 才查询 catalog；没有计划时报告
form/capability mismatch，多个计划同时成立时要求消除歧义。属性损失、burst split、错误映射、调度和容量
必须由 policy 闭合。

当前工程已经可以用显式 route/profile、typed plan 和公共 executor 装配统一 AMBA serial bridge；typed
address claim、router contract、injected construction factory、generated router boundary projection 和
direct-neighbor address resolution 也已接通。
组网侧接下来仍缺 InterfacePort capability algebra、bridge 与 external fabric boundary projection、construction report、
自动 translation catalog lowering 与多跳 resolution。主线因此是让现有 plan/resource/effect 逐项进入 System
resolution，而不是在 runtime 中隐式搜索或插入 adapter。

## 8. 与 Bridge 实施计划的分工

本页只规定网络构造阶段和生成对象的可见性。Operation form、stage、completion fold、resource lease、
AXI/AHB/APB 组合以及具体源码实现由以下文档负责：

- [Bridge 与类型化事务转译](typed-transaction-translation.md)：稳定概念、设计理由和层级边界；
- [事务转译 V1 实施计划](translation-implementation.md)：当前代码起点、实施顺序和验收条件；
- [当前实现状态](implementation-status.md)：已经进入主线的能力。

## 9. NoC 通用构造与协议家族运行时

“可以声明任意拓扑”与“形成通用 NoC 协议”是两件事。当前通用层负责保存弱结构和构造阶段，
协议家族负责解释线上资源、路由身份和功能闭合：

| 可稳定复用的构造底座 | 当前保留在协议家族的含义 |
|---|---|
| `VirtualDut`、typed port、directed connection、system boundary | RN/HN/SN/MN 等 participant role |
| topology ownership、elaboration、resolved adjacency | NodeID namespace、address→home 与 coherence authority |
| 有限资源、blocked/fault、原子候选提交 | CHI L-Credit、P-Credit、Retry、Resource Plane |
| route/store/arbitrate/correlate 的组合思想 | `channel + TgtID` route、REQ/RSP/DAT/SNP 及其 ordering |
| observation、lineage、只读分析接口 | flit codec、virtual channel、switching 和 family progress rule |

这使 ring、mesh、tree 或自定义拓扑可以共享同一个 SystemProtocol 构造过程，同时不要求 AXI fabric、
CHI NoC 和未来 TileLink 网络使用相同的 packet、credit 或 identity 定义。当前 CHI
store-forward router、participant facet、identity resolver 和 capability projector 是
family-specific NoC runtime；它们验证了公共构造底座的接口，但还不足以单独定义“所有 NoC”的统一 API。

一项能力适合上提时，应至少有第二种真实实现提出相同的查询和生命周期。例如另一协议也需要在一个
module 上组合多个 participant facet，或另一 switching mode 也消费相同的 route/store/service 合同。
如果复用点只剩相似名词，继续留在协议家族通常更容易保持边界清楚。
