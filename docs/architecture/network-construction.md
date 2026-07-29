# SystemProtocol 组网构造

本文定义从 module 声明到可执行网络的稳定构造方法。这里的 network 是 `SystemProtocol` 拥有的
canonical topology、系统合同及其派生计划；CHI Network layer 等协议专用含义继续由相应协议族解释。

组网沿一条显式流水线推进：

```text
VirtualDut boundary + connection intent + system contracts
                         │
                         ▼
              construction lowering
              ├─ generated VirtualDut
              ├─ explicit connections
              └─ construction provenance
                         │
                         ▼
              frozen SystemProtocol
                         │ elaborate / resolve
                         ▼
              ElaboratedSystemProtocol
              ├─ owner_by_port
              ├─ address_plan
              └─ transport_plan
                         │
                         ▼
             runtime → trace → monitor / analysis
```

当前对象覆盖、明确缺口与阶段边界统一记录在
[实现状态](implementation-status.md)；近期推进顺序见
[Roadmap](technical-route/08-roadmap.md)。

## 1. 阶段与交接

| 阶段 | 输入 | owner | 输出与交接 |
|---|---|---|---|
| 声明 | 具名 `VirtualDut`、typed ports、connection intent、system contracts | 调用方与协议族 recipe | 可追溯的构造输入 |
| construction lowering | 声明、授权的 factory/catalog/policy | `SystemProtocolBuilder` 与注入的 factory | 显式 module、connection、contract 和 provenance |
| elaboration / resolution | frozen `SystemProtocol` 与 module boundary projection | system elaboration、各类 resolver | `ElaboratedSystemProtocol` 及不可变 resolved plans |
| runtime | elaborated topology、resolved plan、scenario action | 根 `SystemSession` 或 family runtime | accepted event、causal edge、resource snapshot 和 trace |
| monitor / analysis | topology、authority、plan、trace、资源快照 | system monitor 与只读 analysis | reference ledger、verdict、wait-for 或 refinement evidence |

### 1.1 声明 module 边界

每个 `VirtualDut` 独立声明：

- `InterfacePort + InterfaceProtocol`，用于完整逻辑接口；
- `TransportPort + transport family/profile`，用于单向 hop 边界；
- role、capability、attachment binding、backend 和公开的 typed projection。

System 层只消费这些公开边界。AddressSpace、FIFO、arbiter、owner table、directory、snoop filter 等可变状态由
对应 backend 持有。

### 1.2 Construction lowering

`SystemProtocolBuilder` 汇合 module、connection、boundary 和 system contract。便捷 recipe 或 factory
可以生成 bridge、fabric、router 等具名 `VirtualDut`，并把生成的端口与连接写回 canonical topology。

lowering 的产物具备三项性质：

1. 生成对象拥有稳定名称；
2. 选择依据、输入合同和 factory 记录在 provenance 中；
3. 后续 elaboration 面对普通 `SystemProtocol`，使用统一的结构闭合规则。

协议族通过注入 factory、profile 或 typed boundary projection 参与 construction。通用 system 包的静态依赖
止于这些公共边界，AXI、AHB、APB、CHI 等具体实现位于协议族叶包。

### 1.3 Freeze 与 resolution

construction 完成后，elaboration 将系统声明作为 frozen input，依次完成：

| 闭合主题 | 主要检查 | 典型结果 |
|---|---|---|
| 结构与 ownership | 名称、端口引用、唯一占用、role/direction、protocol/family | `owner_by_port` |
| interface capability | event/channel、参数、width、burst、ID、ordering、domain | capability diagnostic 或 resolved requirement |
| address | ingress、route、remap、egress connection、receiver claim | `ResolvedAddressPlan` |
| transport | directed hop、transmitter/receiver、family、profile、邻接关系 | `ResolvedTransportPlan` |
| identity 与 system authority | NodeID、Home、domain membership、security zone | family 或 system resolved plan |
| construction provenance | generated module、connection、policy 与来源关系 | construction report / diagnostic |

resolver 只读消费声明和 typed projection，并返回不可变计划。生成式 module 从同一份 system contract 派生本地
配置；外部 RTL/RPC module 则公开 boundary projection，供 resolution 核对。

### 1.4 Runtime、monitor 与 analysis

runtime 执行已经固定的 topology：

- 根 `SystemSession` 为每条 `InterfaceConnection` 建立独立 `InterfaceSession`，转发 canonical event，并调用
  目标 `VirtualDut` backend；
- family runtime 消费 `ResolvedTransportPlan`，解释 packet/flit、hop resource 和协议专用 progress；
- scenario 提供刺激、advance action、时间或调度选择；
- monitor 消费系统可见事件，维护跨连接 reference ledger 并形成 verdict；
- analysis 只读消费 topology、plan、trace 或资源快照，派生 reachability、wait-for、deadlock witness 和
  boundary refinement evidence。

协议输出始终由通信参与者产生。monitor 依据 authority 核对 fanout、completion return、coherence 或
progress，并把结论保存在 verdict 中。

## 2. Canonical topology

`SystemProtocol.connections` 是 interface connection 与 directed transport connection 的唯一 topology
权威。

| 图中对象 | 模型对象 | 保存的事实 |
|---|---|---|
| module 节点 | `VirtualDut` | 具名边界、端口和 backend binding |
| 完整逻辑接口边 | `InterfaceConnection` | 一份 `InterfaceProtocol` 的 roles 与两个具体端口 |
| 单向 transport 边 | `DirectedTransportConnection` | transmitter→receiver、transport family 与 profile |
| 外层接口 | system boundary | 留给外层 `SystemProtocol` 继续组合的端口引用 |

一个带 decoder、arbiter 或 response mux 的地址网络采用显式 fabric 节点：

```text
manager ─ connection 0 ─ [fabric VirtualDut] ─ connection 1 ─ register bank
                                      └──────── connection 2 ─ memory
```

星形、树形、mesh 和 bus strip 都是 topology 的视图。canonical topology 只记录声明过的 module 与
connection；共享信号、广播、decode、仲裁、转发和 response ownership 由具名 module 或 system contract
显式声明。禁止根据图形外观推断这些行为。

### 2.1 图示与折叠

系统拓扑图采用接近网表的表达：

- `VirtualDut` 是节点；
- `InterfaceConnection` 与 `DirectedTransportConnection` 是 typed edge；
- 主标签显示 protocol 或 transport family；
- 次标签显示 connection instance 与两端端口。

二端点连接直接画成边。共享通信实体可以用中性 junction 或 bus bar 表达 hyperedge，但图例需要声明共享
信号、广播可见性和统一仲裁域。`system_bus_strip_dot()` 接受调用方显式指定的
`SingleIngressAddressFabricBackend`，从既有 connection、fabric port 和 route window 派生折叠视图。

constructed module 的展开图按边界向内部阅读：

```text
InterfaceConnection → InterfacePort → attachment → backend
```

attachment 位于相应端口附近，承担协议 event 与内部 operation 的转换。bridge/crossbar 的多个 attachment
分别位于 ingress 和 egress 边界，跨端口状态集中在 backend。

### 2.2 Mesh 的节点与边

canonical module graph 采用以下映射：

| 元素 | topology 表达 | 解释 |
|---|---|---|
| router、crosspoint、endpoint | `VirtualDut` 节点 | 独立实现、保存状态、仲裁、转发或观测 |
| endpoint-to-router 逻辑接口 | `InterfaceConnection` | 两个 interface ports 的完整协议连接 |
| router-to-router 单向 hop | `DirectedTransportConnection` | family runtime 执行 flit flow control 与 hop resource |
| north/south/east/west/local | `InterfacePort` 或 `TransportPort` | module boundary 上的连接位置和方向 |
| tile 分组 | composite projection | floorplan 或阅读分组 |

mesh router 通常按 destination/NodeID、route function 和 virtual channel 选取下一 hop；address crossbar 按
地址窗口选取 endpoint。两者可以共享 Route、Store、Arbitrate、Correlate 等构造思想，各自使用与路由依据、
资源状态和完成关系匹配的 backend。

产品视图可以把 endpoint 画在 tile 内，canonical topology 仍保留独立 local connection：

```text
[endpoint VirtualDut] ─ local connection ─ [router VirtualDut]
                                           │
                            neighbor transport connection
                                           │
                                    [router VirtualDut]
```

协议事务图可以折叠 transit router，把 RN、HN、SN 等参与者作为时间线节点。该投影隐藏运输细节，同时保留
module topology 的原始 ownership。

## 3. Connection ownership 与返回路径

elaboration 为每个 port 解析唯一 owner：一个 connection，或一个 system boundary。完整逻辑接口的全部
channels 归同一 `InterfaceConnection`；request/response 独立 NoC 则使用显式
`DirectedTransportConnection`，并由端到端 transaction ledger 关联。

跨端口返回关系按 source identity 的保留方式实现：

| 方法 | 保存的关系 | 适用边界 |
|---|---|---|
| 独占返回路径 | path 即 source identity | 每条路径或 virtual channel 只有一个 owner |
| 单活动 owner | egress → ingress | APB、简单 AHB 或单活动 crossbar profile |
| AXI ID 前缀 | downstream ID = ingress index + original ID | 下游允许扩展 ID |
| ID remap table | downstream tag → ingress、原 ID、ordering context | 固定 ID 宽度与多 outstanding |
| 串行化 | egress 或 egress+ID 同时保留一个 owner | 状态较小、并发受限 |

AXI 的 AR→R、AW/W→B 跨 channel correlation 属于完整接口合同；W channel 还需要 AW→W route FIFO 或等价的
burst-owner 状态。AHB/APB 通常在 address/setup 接纳时锁存 owner，在 data/access 完成后释放；burst、lock
或 wait-state 会延长这份租约。

| 观察范围 | owner 的职责 |
|---|---|
| `InterfaceProtocol` / `InterfaceSession` | 一条完整接口内的 channel correlation、ordering 和 outstanding |
| interconnect `VirtualDut` backend | 本 module 的 route、FIFO、arbiter、ID remap 和 response owner |
| `SystemProtocol` / monitor | 跨 module 的 origin、path closure、completion return 和 wait-for |

多端口 crossbar 默认是一个 `VirtualDut` 节点。验证目标需要分别观察 decoder、arbiter 或 request/return
network 时，可以把内部 module 和 connections 展开成子 `SystemProtocol`，再通过
`SystemProtocol.as_virtual_dut()` 封装到外层 topology。

## 4. System contracts 与单一 authority

一项可变事实对应一个执行权威；system declaration、module projection 和 monitor ledger 通过具名关系共享
所需信息。

| 事实类别 | 权威 owner | 交接方式 |
|---|---|---|
| canonical connections | `SystemProtocol.connections` | resolution 派生 adjacency 与 transport plan |
| address/home/NodeID/domain authority | system contract | 生成或核对 module boundary projection |
| decode、route、remap、FIFO、arbiter、directory | 对应 `VirtualDut` backend | event 与 typed projection |
| interface correlation | 对应 `InterfaceSession` | connection trace |
| packet route identity | protocol-family representation + resolved route | family runtime 逐 hop 转发 |
| 端到端 owner、coherence、progress 参考状态 | system monitor ledger | verdict 与 witness |

地址、Home 和身份分配在 system contract 中保留一个权威来源：

- 生成式 fabric/router 从该 contract 派生本地配置，并在 construction 时公开实际 projection；
- 外部 RTL/RPC module 将本地 decode 或 route 作为 boundary contract/projection；
- resolution 把 contract、route、connection、receiver claim 和 provenance 闭合成只读计划。

禁止维护一份可独立变化的 system route table 和另一份未经核对的 backend route table。

### 4.1 Address closure

`AddressClaim` 声明接收端窗口，`AddressRouterContract` 声明 ingress、egress、route 和 remap。
resolution 将每条 route 闭合到对应 egress connection 上唯一的 direct-neighbor claim：

```text
ingress
   │ AddressRouterContract route/remap
   ▼
fabric egress
   │ InterfaceConnection
   ▼
direct receiver AddressClaim
```

生成式 address router 由 `SystemProtocolBuilder.construct_address_router()` 把同一 contract 交给注入
factory。factory 返回的 backend 公开 `AddressRouterBoundaryProjection`，Builder 核对端口与 route 后再注册
DUT 和 contract。请求入队、仲裁和 owner return 继续由 fabric backend 执行。

### 4.2 Route、transport 与 capability closure

| 主题 | 声明 | resolved 结果 | 执行者 |
|---|---|---|---|
| interface path | `InterfaceConnection`、roles、ports | port owner 与局部 session namespace | `SystemSession` |
| transport path | `DirectedTransportConnection`、family/profile | named hops、incoming/outgoing adjacency | family transport session |
| network identity | NodeID/source/target、Home/domain authority | participant binding 与 route identity | family participant/router runtime |
| capability | endpoint offer、path requirement、translation effect | compatibility result 与 diagnostic | endpoint、bridge 或 family runtime |
| progress | resource、dependency、forward-progress contract | wait-for projection | runtime + system analysis |

runtime 使用 resolved path；新增 hop、bridge 或 adapter 由 construction 形成显式 topology。禁止 runtime
根据 protocol mismatch 搜索或插入隐式路由。

QoS、security、clock/reset 和 interrupt 也沿同一方法分配：

| 主题 | transaction / interface | module | system |
|---|---|---|---|
| QoS | `AxQOS` 等字段 | 队列与仲裁算法 | fairness、bandwidth、latency property |
| Security | security intent | endpoint/firewall 的允许或拒绝 | security-zone reachability |
| Clock/reset | port domain | CDC、reset-isolation module | control topology 与 compatibility closure |
| Interrupt | notification interface 或 MSI address operation | interrupt controller | delivery reachability 与 owner |

## 5. Bridge 与 interconnect lowering

当两个 endpoint 需要事务转译时，construction 接受调用方授权的 catalog、stage 和 policy：

```text
connection intent + endpoint ports + authorized translation catalog
                         │
                         ▼
             compile immutable TranslationPlan
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

direct connection 是默认策略。调用方显式授权 transaction translation 后，construction 才查询 catalog；
零个候选产生 form/capability diagnostic，多个候选要求调用方或 policy 消除歧义。属性 effect、burst split、
completion fold、错误映射、调度与容量全部进入 typed plan 或显式 policy。

bridge 内部职责按观察范围分配：

| 组成 | owner | 保存的事实 |
|---|---|---|
| ingress/egress attachment | 单个 port | codec、wire fragment join、接口 transaction context |
| translation stage/plan | typed translation | operation form、attribute effect、split/fold 与完成映射 |
| executor/backend | bridge `VirtualDut` | parent queue、lease、lineage、ID remap、serialize 与 owner return |
| system contract/resolution | `SystemProtocol` | 两端 connection、path capability、address/identity closure |

### 5.1 Address fabric 与 N×M crossbar

一个最小星形地址网络可以写成：

```text
injected manager
      │ APB
      ▼
single-ingress AddressFabric
      ├─ APB → RegisterRegion
      └─ APB → MemoryRegion
```

`ScheduledAddressCrossbarBackend` 集中持有 admission、per-egress round-robin、active slot 和 response
owner。`build_axi4_lite_address_crossbar_vdut()` 为它装配 N 个 AXI4-Lite subordinate attachments 与 M 个
manager attachments；不同 egress 可以并行 grant，同一 ingress/egress 按 profile 限定 active 数量。

full AXI crossbar 还需要显式闭合 AW/W route ownership、ID namespace/remap、burst preservation 和同 ID
response ordering。具体实现覆盖见 [实现状态](implementation-status.md)，相关稳定方法见
[AddressFabric](address-fabric.md) 和
[Bridge 与类型化事务转译](typed-transaction-translation.md)。

## 6. CHI 作为分层验证实例

CHI 展开 NoC 时，同一通信同时具有协议、网络和相邻 Link 三种表示：

```text
typed protocol message
       │ packetize：增加逐份 route identity
       ▼
network packet
       │ wrap：占用相邻 Link 的 flow-control unit
       ▼
protocol flit ── one directed hop ── protocol flit
```

message 保存协议交换，packet 保存跨 hop route identity，flit 占用当前 Link 的 activation、L-Credit 和
buffer resource。`LCrdReturn` 等 link-maintenance flit 在相邻 transmitter/receiver 之间归还 Link resource。

Snoop request 的协议格式省略 `TgtID`。Home/interconnect backend 根据 system coherence authority 选择
Snoopee，为每个目标建立带 `target_id` 的 packet copy，并聚合 clean response 或 dirty data；family runtime
把每份 packet 逐 hop 运送，system monitor 核对 fanout 与全局 permission 演化。

当前 slice 已包含
`SnpShared/SnpSharedFwd/SnpUnique/SnpNotSharedDirty/SnpCleanInvalid/SnpMakeInvalid` 表示。首个 clean
`ReadShared` DCT 已作为独立 forwarding transaction/capability 闭合，并保持对 Owned state 的独立性；
dirty、`RetToSrc=1`、动态多 peer 与一般 forwarding catalog 由后续 profile 扩展。完整 feature 覆盖和证据入口
以 [实现状态](implementation-status.md) 为准，推进顺序以
[Roadmap](technical-route/08-roadmap.md)为准。

这一实例验证以下通用边界：

| CHI 事实 | owner |
|---|---|
| opcode、TxnID/DBID、Retry、P-Credit lifecycle | CHI protocol/participant transaction ledger |
| cache permission、directory、snoop filter | participant `VirtualDut` backend |
| NodeID、Home、coherence-domain authority | `SystemProtocol` contract |
| packet copy、source/target route identity | CHI network representation 与 resolved route |
| L-Credit、activation、hop buffer | family transport session |
| fanout、completion aggregation、全局 invariant | Home/interconnect backend + system monitor |

## 7. 强约束

以下约束保护 topology 与运行事实的单一来源：

1. `SystemProtocol.connections` 是 canonical topology 权威；resolved plans 是只读投影。
2. construction 在 runtime 之前展开 recipe、factory 与 translation，生成对象进入 canonical topology。
3. resolution 只读消费 frozen 声明，并保留 provenance。
4. route、broadcast、arbitration 和 response ownership 由具名 backend 或 system contract 显式定义。
5. 地址、Home 与 identity authority 各保留一个系统来源；backend 配置通过派生或 projection 核对。
6. runtime 执行 fixed topology；monitor 消费事件并形成 verdict；analysis 只读派生证据。
7. 通用 system 包依赖 typed boundary 与注入 factory，具体协议实现继续位于协议族叶包。

## 8. 相邻文档

- [InterfaceProtocol、VirtualDut 与 SystemProtocol](system-protocol.md)
- [通信建模的三张视图](communication-scope-and-transport.md)
- [VirtualDut 方法论](virtual-dut.md)
- [AddressFabric](address-fabric.md)
- [Bridge 与类型化事务转译](typed-transaction-translation.md)
- [事务转译 V1 实施边界](translation-implementation.md)
- [SystemProtocol 源码导航](../../protocol_model/system/README.md)
