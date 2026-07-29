# Bridge 构造：来自硬件生成与网络协议的设计启示

[返回架构索引](README.md) · [Canonical Bridge 架构](typed-transaction-translation.md) ·
[事务转译 V1 状态](translation-implementation.md) · [当前实现状态](implementation-status.md) ·
[SystemProtocol](system-protocol.md)

本文把硬件生成、HLS/dataflow、延迟不敏感设计和互联网 translator 的经验映射到 Bridge 构造。外部材料
提供问题形状和工程方法；AMBA、TileLink 及本项目 API 的合同仍以相应规范、InterfaceProtocol、
VirtualDut profile 和 SystemProtocol 为权威来源。

整条构造链可以概括为：

> 先在构造期闭合两侧能力与转换政策，再执行可追踪的 typed transaction translation；executor 显式管理
> queue、owner、capacity 和等待关系，最后把 topology 与端到端 property 交给 SystemProtocol。

## 1. 对象定位与构造主线

### 1.1 相似设备的区分依据

“两个协议口之间有一个 module”描述了外形，operation 关系和 completion 生命周期才能确定其构造类型：

| 构造 | operation 关系 | 两侧 session 与 completion | 典型状态或算子 |
|---|---|---|---|
| relay | operation 语义保持稳定 | 可以终结后重发，也可以按同协议转送 | route、仲裁、队列、ID/owner |
| interface bridge | 两端 wire protocol 不同，共享一种 operation form | 两条独立 InterfaceSession；下游结果重新编码为上游 completion | attachment、接口关联状态、Identity stage |
| semantic bridge | operation 粒度、属性或完成关系发生变化 | 两条独立 InterfaceSession；completion 经 lift/fold 返回 | split/merge、属性政策、result fold、调度 |
| encapsulation/tunnel | 原协议消息成为 opaque payload | tunnel endpoint 成对出现 | 封装、运输、解封装；中间系统转送 payload |

[HTTP Semantics 对 gateway 的定义](https://www.rfc-editor.org/rfc/rfc9110.html#section-3.7)提供了角色切换的
外部例子：gateway 在上游一侧表现为 server，在下游一侧作为 client 发起请求。AXI→APB Bridge 同样在
AXI 侧承担 subordinate 责任，在 APB 侧承担 requester 责任；Bridge 接收下游结果后，按上游协议生成
completion。

[IPv4/IPv6 过渡架构](https://www.rfc-editor.org/rfc/rfc6144.html)把 translation 与 tunneling 分开。
`AXI over chip-to-chip link` 可以建模为 tunnel endpoints 加中间 SystemProtocol；AXI→APB 则由两个 codec
和 typed translation 组成。这些名称适合作为 `TranslationProfile` 的构造维度，同一个 VirtualDut 也可以
同时执行 route、transport conversion 和 semantic translation。

早期的[异构协议接口自动合成研究](https://iris.unitn.it/handle/11572/95174)把抽象 message 与具体
signaling protocol 上的传输轨迹分开。operation/codec 延续这个分界；burst、atomic、ordering 和错误聚合
继续由 typed stage 与显式 profile 定义。

### 1.2 四阶段构造链

```text
port offer/requirement + profile
                │
                ▼
construction closure ──► immutable TranslationPlan
                │
                ▼
typed transaction translation ──► parent/child lineage + result fold
                │
                ▼
resource-aware execution ──► queue/owner/lease/wait-for
                │
                ▼
VirtualDut boundary ──► SystemProtocol topology + end-to-end properties
```

四个阶段使用关联的 token 和 provenance，同时持有不同事实：

| 关系视图 | 回答的问题 | 主要对象 | 产物或状态 owner |
|---|---|---|---|
| 构造期闭合图 | 组件组合是否具有完整定义 | signature、capability relation、profile、stage contract | `TranslationPlan` / construction report |
| 事务转译图 | 一笔 parent 如何产生 child 并形成结果 | operation、lineage、`SemanticEffect`、lift/fold | translation frame / fanout ledger |
| 资源等待图 | 哪个 token 持有什么，又等待什么 | queue、lease、owner table、blocked demand | executor/backend |
| 系统交接图 | module、connection 和端到端事实怎样闭合 | boundary projection、topology、system contract | SystemProtocol resolution/runtime |

语义 cardinality 说明一笔 parent 产生多少 child；execution capacity 说明同一时刻可以发行多少 child。
construction closure 选择政策，runtime 只执行已经冻结的 plan。

## 2. 构造期闭合

### 2.1 双向能力协商

构造期闭合同时检查 request 的正向路径和 completion 的反向路径：

```text
source port offer ───────────────► request capability
        ▲                                  │
        │                                  ▼
source requirement ◄── ordered stage relations ──► target offer
                                                   ▲
                                                   │
                                      target requirement

completion capability 沿相反方向闭合
```

这里传播 operation signature、宽度、cardinality、ordering、backpressure、属性保持和 completion 能力。
成功结果是一份不可变 `TranslationPlan`；失败结果指出具体 edge、property 和 mismatch。

[Diplomatic Design Patterns](https://carrv.github.io/2017/papers/cook-diplomacy-carrv2017.pdf)把 topology
发现、双向参数协商和 module elaboration 分开；[Chipyard AdapterNode](https://chipyard.readthedocs.io/en/1.12.2/TileLink-Diplomacy-Reference/NodeTypes.html)
分别变换 client 与 manager 两个方向的参数。映射到本项目，构造过程依次完成：

1. ingress/egress codec 声明各自提供和需要的 operation 能力；
2. stage 声明 request 与 completion 两个方向的 capability relation；
3. planner 按顺序组合 relation，并检查每个中间不变量；
4. closure 成功后冻结 plan；
5. construction report 保存 codec、stage、policy、executor profile 和 provenance。

目标端错误分类较弱时，源端在构造期选择 error fold policy；源端要求保持 ID ordering 时，目标端能力与
executor profile 共同给出实现条件。这类约束需要双向传播。

### 2.2 按差异维度组合算子

[Chipyard Diplomatic Widgets](https://chipyard.readthedocs.io/en/1.12.2/TileLink-Diplomacy-Reference/Widgets.html)
展示了 fragment、width、source-ID、FIFO ordering、buffer 和 protocol conversion 等单一职责组件。
[CIRCT Handshake](https://circt.llvm.org/docs/Dialects/Handshake/RationaleHandshake/)与
[ESI](https://circt.llvm.org/docs/Dialects/ESI/)则用显式 join、fork、merge、mux、buffer 和 typed channel
区分数据关系与运输实现。

本项目按照差异维度选择算子：

| 算子 | 构造期声明 | 运行状态 owner | 典型用途 |
|---|---|---|---|
| ingress/egress codec | event 与 operation signature、reply context | attachment | wire protocol decode/encode |
| shape normalization | pre/postcondition、字段几何 | stage 或 codec | single/burst form 规范化 |
| fragment / merge | cardinality、lineage、completion fold | fanout ledger / result fold | burst 拆分、块合并 |
| width / lane transform | alignment、byte validity、属性条件 | stage；必要 buffer 归 executor | split/merge lane |
| attribute policy | preserve、recompute、weaken、reject | immutable plan | protection、USER、atomic policy |
| ID / order repair | identity mapping 与 ordering requirement | owner table / scheduler | deinterleave、ID remap |
| route / arbitrate | destination relation、selection policy | interconnect backend | 多出口选择与竞争 |
| buffer / clock / ready lowering | transport capability、capacity、equivalence | executor、gasket 或 transport | register slice、FIFO、CDC |

每个 `TranslationStage` 声明静态 pre/postcondition、逐 operation applicability、semantic effects、
completion rule 和与相邻 stage 的顺序依赖。Planner 因而组合一条受约束的 pass pipeline。例如，
fragmenter 可以限制 burst/atomic 范围，width conversion 依赖 alignment 与可修改属性，deinterleave 则放在
产生相应 ordering pressure 的转换之后。

### 2.3 Profile、stage 与 plan

跨领域经验最终收敛到三个构造对象：

| 对象 | 需要闭合的内容 |
|---|---|
| `TranslationProfile` | source/target signature、direction predicate、ordering、capability relation、semantic effect authorization、executor/storage、completion mapping、equivalence、reset/cancel/failure |
| `StageContract` | source/target signature、cardinality、forward offer、backward requirement、pre/postcondition、applicability、effects、lower、lift/fold、provenance |
| `TranslationPlan` | 有序 stage、双向 closure、所选 policy、executor compatibility 和 construction report |

通用 planner 可以从具名 preset 开始，由 preset 选择 codec、stage 顺序和 executor，再由公共 validator 执行
同一套闭合检查。自动 stage 搜索属于 planner 能力演进，稳定对象合同保持一致。

## 3. Typed transaction translation

### 3.1 Parent/child 生命周期

一笔已接纳工作沿 typed path 完成：

```text
CanonicalEvent
    │ ingress decode/join
    ▼
ParentEnvelope(operation + reply context + token)
    │ lower / split / rewrite
    ▼
child operation(s) ──► downstream completion(s)
    ▲                            │
    └──── lineage + lift/fold ───┘
                     │
                     ▼
             parent result
                     │ ingress encode
                     ▼
              upstream completion
```

codec 持有 wire event 与 operation 的映射；stage 持有 typed semantic transformation；fanout ledger 持有
parent/child obligation；result fold 持有 completion 的聚合规则。FIFO 深度和并发窗口归 executor，
一笔 operation 的既定翻译含义在资源压力下保持稳定。

### 3.2 SemanticEffect

[IP/ICMP Translation](https://www.rfc-editor.org/rfc/rfc7915.html)展示了 translator 对 payload、header、
checksum、fragment 和错误的显式处理。对应到本项目，每项重要性质都记录 `SemanticEffect`：

| Effect | 含义 | AXI4→APB 例子 |
|---|---|---|
| preserve | 下游继续表达同一性质 | address、有效 byte data |
| recompute | 根据目标形状重新计算 | child address、lane/strobe |
| split/aggregate | 一份工作拆分或多份结果合并 | burst、response fold |
| rebind | identity 改由内部 context 保存 | AXI ID 保存在 reply/owner context |
| synthesize/default | 目标信息由 policy 产生 | 可配置默认 protection 属性 |
| weaken/drop | 保证或信息变弱 | profile 授权的 USER/ordering 处理 |
| reject | 当前 profile 拒绝该 operation | 无法保持的 exclusive/atomic |

`CapabilityRelation` 回答 plan 能否闭合；`SemanticEffect` 记录闭合过程改变了什么。construction report
保存 effects 与授权来源，使“可构造”和“无损转换”拥有各自证据。

### 3.3 Fragment、lineage 与部分失败

[IPv6 Fragmentation](https://www.rfc-editor.org/rfc/rfc8200.html#section-4.5)和
[Stateful NAT64](https://www.rfc-editor.org/rfc/rfc6146.html)强调 fragment identity、offset、乱序与有限
storage。`AddressBurst→AddressAccess[N]` 具有相似的生命周期形状：

| 事实 | Owner |
|---|---|
| parent token 与 child index 的 lineage | translation frame / fanout ledger |
| child 总数与 completion cardinality | stage contract / ledger |
| 同时发行数与重组容量 | executor pool / storage profile |
| completion 顺序与 error aggregation | result fold policy |
| duplicate、missing、cancel 和 reset | profile + executor lifecycle |
| 已发生的 child side effect | 下游 endpoint contract |

APB child 可以在后续 child 失败前已经产生外部副作用。`AddressBurst` 表达访问之间的关联和次序；事务
原子性需要 profile 与 endpoint contract 另行声明。partial failure policy 决定剩余 child、上游 completion
和 provenance 的处理；已经发生的 child side effect 继续按下游 endpoint contract 生效。

### 3.4 Wire completion 与 completion origin

[Proxy-Status](https://www.rfc-editor.org/rfc/rfc9209.html)把面向客户端的协议结果与 intermediary 内部错误
来源分开。Bridge 也保存两条线：

| completion origin | 对上游的可能编码 | 事实性质与 owner |
|---|---|---|
| downstream completion | OKAY、SLVERR 等 | 正常协议结果；egress codec + fold |
| local route/policy completion | DECERR 或 profile 指定结果 | module-local 正常 completion；backend |
| resource/runtime failure | profile 指定错误或 fault | 模型/runtime fault；executor |
| reset/cancel | profile 指定结果、drain 或 fault | lifecycle policy |
| malformed completion | fault，必要时映射 wire error | 协议诊断；session/codec |

同一个 wire code 可以对应多个 origin。trace、fault 和 construction provenance 保留真实来源；wire
completion 继续满足上游接口合同。

### 3.5 Typed metadata 与持久状态

[P4₁₆](https://p4.org/wp-content/uploads/sites/53/p4-spec/docs/P4-16-v1.2.4.html)把 parser、typed
headers/metadata、control、deparser 与 table/extern 分开。它与 Bridge 的对应关系为：

| P4 构件 | Bridge 构件 |
|---|---|
| parser | ingress attachment decode/join |
| typed data | operation + opaque reply context |
| control | `TranslationStage` / `TranslationPlan` |
| extern | executor owner/FIFO/resource |
| deparser | egress attachment encode |
| architecture | `ExecutorProfile` / VirtualDut capability |

typed data 经显式 stage 变换，跨 transaction 的持久状态归 executor/backend。Bridge 还具有 completion 的
反向传播，因此 lift/fold 和 parent lifecycle 构成额外合同。

## 4. Resource-aware execution

### 4.1 Stage、executor 与访问模式

[AMD HLS Tasks and Channels](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Tasks-and-Channels)把持久 task 与
有深度的 channel 分开；[Dataflow Viewer](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Dataflow-Viewer)
把阻塞原因和 FIFO occupancy 作为独立诊断事实。对应关系为：

| 对象 | 外部类比 | 保存的内容 |
|---|---|---|
| `TranslationStage` | typed rewrite | lower/lift/fold、适用条件和 effect |
| executor/backend | persistent task/module | queue、cursor、owner、continuation、scheduler |
| capacity pool/channel | bounded FIFO/resource | lease、usage、empty/full、blocked demand |
| plan | elaborated process graph | stage 顺序、policy 和 executor compatibility |

stage 与 executor 还声明访问模式：

| 模式 | 执行含义 | 例子 |
|---|---|---|
| `streaming_sequential` | child 可按 index 逐个生成和消费 | AXI burst 串行拆为 APB transfer |
| `materialize_block` | 下游开始前形成完整块 | merge、全块校验 |
| `random_access/reorder` | completion 按 index 回填 | window-K、多 ID、跨 child 重排 |

`burst256` 表示 256 个 child obligations；serial executor 的 egress lease 峰值可以保持为 1。serial、
window-K 和 reorder 是 execution profile，协议合同负责规定外部可观察行为。

[AMD AXI Infrastructure Cores](https://docs.amd.com/r/en-US/pg059-axi-interconnect/AXI-Infrastructure-Cores)
把 crossbar、width converter、clock converter、protocol converter、FIFO 和 register slice 作为可组合部件。
[AXI4→AXI4-Lite conversion](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Conversion-to-AXI4-Lite)
展示了 admission、ID 保存和 burst 展开；
[width conversion](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Width-Conversion)则依赖 width、
alignment、burst kind 和属性。由此得到的独立参数包括：

| 参数 | Owner |
|---|---|
| 每笔 operation 的 child count | stage applicability/cardinality |
| 上游 admission | ingress boundary + executor capacity |
| 下游并发窗口 | scheduler + egress pool |
| ID 保存与 return owner | reply context / owner table |
| response 聚合与 early completion | fold + completion policy |

### 4.2 状态分类与释放边界

[RFC 7915](https://www.rfc-editor.org/rfc/rfc7915.html)区分 stateless 与 stateful translation；
[Stateful NAT64](https://www.rfc-editor.org/rfc/rfc6146.html)进一步区分长期 binding、per-flow session 和
临时 fragment storage。Executor 状态按作用域与寿命声明：

| 状态类 | 例子 | 典型 key/owner | 释放边界 |
|---|---|---|---|
| static configuration | route、attribute policy | plan/module | module replacement |
| transport assembly | AXI AW/W join | port + descriptor | decode complete/cancel/reset |
| shared binding | ID remap、return owner table | mapped ID/egress | 最后相关 transaction 完成 |
| per-parent semantic | fanout ledger、fold accumulator | parent token | parent completion/cancel |
| capacity lease | queue/egress slot | current owner | completion/cancel |
| performance-only | prefetch/cache、optional buffer | implementation | eviction/reset |
| diagnostic | lineage、fault provenance | evidence record | artifact retention policy |

每类状态同时声明 reset 后的 discard、wire completion、drain 或 reconstruction policy。这样，FIFO 保持为
执行资源，correlation 状态保留在持有相应 acquire/release 生命周期的 controller。

### 4.3 Backpressure、buffer 与等价层级

[Latency-Insensitive Protocols](https://www2.eecs.berkeley.edu/Pubs/TechRpts/1999/3585.html)在 patient/stallable
process 和事件序列等价的条件下分离通信时延与计算功能。
[Chisel ReadyValid/Decoupled](https://www.chisel-lang.org/docs/explanations/interfaces-and-connections#the-standard-ready-valid-interface-readyvalidio--decoupled)
提供 ready、valid、bits 的运输形状；payload stability 等协议规则仍由具体 observer/contract 执行。

Translation profile 明确选择等价层级：

| 等价层级 | 允许的实现变化 | 需要相邻合同继续闭合的事实 |
|---|---|---|
| operation/effect trace | cycle 和内部 child 形状可以变化 | ordering、effect 与 completion policy |
| interface transaction/order | 可插入满足条件的等待和 buffer | pin waveform 由 observation profile 解释 |
| pin/cycle | 采用 profile 列出的时序变化 | queue、retiming、reset 和 timeout 条件 |

入口支持 backpressure 时，admission 在接纳前核对 capacity，并由资源状态驱动 READY。入口采用不可回压
profile 时，boundary gasket 在构造期声明足够的 buffer 与 overflow/failure contract。
`AddressBurst→AddressAccess` stage 只声明 semantic cardinality；transport capability 与 buffer 由
boundary/executor 声明。

### 4.4 Credit 与本地资源

[TCP receive window](https://www.rfc-editor.org/rfc/rfc9293.html)是端点间可观察的协议状态，关联 sequence
space 和 window update；本地 buffer 只是其实现输入之一。本项目使用四类独立生命周期：

| 数量 | 含义 | Owner 与释放/更新 |
|---|---|---|
| protocol credit/window/READY | 两端可观察的接纳契约 | InterfaceProtocol 或 transport contract |
| parent/child obligation | 尚待完成的语义工作 | transaction/translation lifecycle |
| executor lease | 当前 owner 占用的实现资源 | capacity pool，completion/cancel 时释放 |
| configured capacity | 局部接纳上限 | immutable profile / boundary projection |

admission policy 可以用本地 slot 决定 READY；投影关系保留两边各自的更新规则与证据。

## 5. System handoff

### 5.1 局部保证与端到端 owner

[End-to-End Arguments in System Design](https://groups.csail.mit.edu/ana/Publications/PubPDFs/End-to-End%20Arguments%20in%20System%20Design.pdf)
与 [RFC 1958](https://www.rfc-editor.org/rfc/rfc1958.html)强调端点知识与端到端验证。Bridge 完成局部合同，
SystemProtocol 和 endpoint contract 闭合更大范围：

| 事实或保证 | 最小判定范围 | Owner |
|---|---|---|
| request/completion 配对 | 单个 Bridge port/session | attachment + InterfaceSession |
| typed conversion 与 `SemanticEffect` | Bridge parent/child lifecycle | plan + executor |
| local ordering、capacity、backpressure | Bridge boundary | backend + boundary projection |
| topology、route ownership、return closure | 多 module / connection | SystemProtocol |
| 最终存储持久化与全系统可见性 | endpoint + system property | endpoint contract / SystemProtocol |
| 多节点 wait-for 与 deadlock | resolved network resources | SystemProtocol runtime/analysis |
| pin/cycle conformant trace | observation boundary | observer + external integration |

Bridge 的 queue、owner 和 outstanding state 用于履行局部协议责任。SystemProtocol 通过 boundary
contract/projection 消费显式 capability、resource 和 wait demand，backend 保留私有运行状态。

### 5.2 Tunnel、nexus 与多端口互连

Tunnel 由成对 endpoint 保存原协议语义，中间 topology 归 SystemProtocol。多 fan-in/fan-out 使用显式
join、fork、arbiter、route 与 completion owner；crossbar 作为多端口 VirtualDut 持有局部仲裁和 owner
table，并把全局 route/return/deadlock 事实交给 SystemProtocol。

### 5.3 外部类比的适用边界

| 外部领域 | 可复用的方法 | 本项目中的重新闭合点 |
|---|---|---|
| Diplomacy | 静态 topology、双向 capability、elaboration | 外部 DUT 与既有 trace 继续由 runtime monitor 提供证据 |
| HLS/dataflow | task、channel、capacity 和 blocked reason 分离 | AXI 多 channel、ID reorder、owner 由协议和 backend 合同补充 |
| latency-insensitive | stallable boundary 与 trace equivalence | reset、timeout、pin cycle 和不可回压入口使用显式 profile |
| TCP/IP/NAT/fragment | binding、lineage、reassembly、partial failure | 目标协议/profile 决定是否采用 retransmission、timeout 等行为 |
| semantic waist | 少量稳定 operation form 提升复用 | address、stream、atomic、coherent domain 保持各自 typed form |

这张表集中记录类比的使用范围。外部领域帮助选择对象和问题分解方式，协议要求仍回到对应规范与本项目
canonical contract。

### 5.4 实现状态与路线入口

稳定对象和机制由 [Bridge 与类型化事务转译](typed-transaction-translation.md) 定义；当前 V1 覆盖、限制和
接入计划集中在[事务转译 V1 实施状态](translation-implementation.md)；全仓能力矩阵见
[当前实现状态](implementation-status.md)，工作顺序见[技术路线](technical-route/08-roadmap.md)。本文维护
跨领域设计依据和构造方法。

## 6. 参考资料与各自用途

| 来源 | 本文吸收的内容 |
|---|---|
| [Automatic Synthesis of Interfaces between Incompatible Protocols](https://iris.unitn.it/handle/11572/95174) | 抽象 message 与 signaling protocol 轨迹的分离 |
| [Diplomatic Design Patterns](https://carrv.github.io/2017/papers/cook-diplomacy-carrv2017.pdf) | topology 发现、双向参数协商、elaboration 分离 |
| [Chipyard Node Types](https://chipyard.readthedocs.io/en/1.12.2/TileLink-Diplomacy-Reference/NodeTypes.html) | adapter 与 nexus、双向参数函数 |
| [Chipyard Widgets](https://chipyard.readthedocs.io/en/1.12.2/TileLink-Diplomacy-Reference/Widgets.html) | thin adapters、顺序依赖、ID/order/width/fragment 处理 |
| [AMD HLS Tasks and Channels](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Tasks-and-Channels) / [Dataflow Viewer](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Dataflow-Viewer) | persistent task、FIFO/PIPO、容量、occupancy 与阻塞 |
| [CIRCT Handshake](https://circt.llvm.org/docs/Dialects/Handshake/RationaleHandshake/) / [ESI](https://circt.llvm.org/docs/Dialects/ESI/) | typed channel、fork/join、buffer lowering |
| [Latency-Insensitive Protocols](https://www2.eecs.berkeley.edu/Pubs/TechRpts/1999/3585.html) | 计算/通信解耦的前提与等价边界 |
| [Chisel ReadyValid/Decoupled](https://www.chisel-lang.org/docs/explanations/interfaces-and-connections#the-standard-ready-valid-interface-readyvalidio--decoupled) | ready-valid 运输形状与协议规则的 owner |
| [AMD AXI Infrastructure Cores](https://docs.amd.com/r/en-US/pg059-axi-interconnect/AXI-Infrastructure-Cores) / [AXI4→AXI4-Lite](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Conversion-to-AXI4-Lite) / [Width Conversion](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Width-Conversion) | converter、admission、ID、width、FIFO 与 register slice 的组合 |
| [HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html#section-3.7) | gateway 在两侧承担不同协议角色 |
| [IPv4/IPv6 Translation Framework](https://www.rfc-editor.org/rfc/rfc6144.html) | translation 与 tunnel、场景/profile 边界 |
| [IP/ICMP Translation](https://www.rfc-editor.org/rfc/rfc7915.html) / [Stateful NAT64](https://www.rfc-editor.org/rfc/rfc6146.html) | 语义映射、显式状态、错误与 fragment 资源 |
| [IPv6 Fragmentation](https://www.rfc-editor.org/rfc/rfc8200.html#section-4.5) | lineage、重组、乱序与部分失败边界 |
| [Proxy-Status](https://www.rfc-editor.org/rfc/rfc9209.html) | wire completion 与内部错误来源 |
| [TCP](https://www.rfc-editor.org/rfc/rfc9293.html) | 协议 window 与本地 buffer/lease 的区别 |
| [End-to-End Arguments](https://groups.csail.mit.edu/ana/Publications/PubPDFs/End-to-End%20Arguments%20in%20System%20Design.pdf) / [RFC 1958](https://www.rfc-editor.org/rfc/rfc1958.html) | 局部机制与端到端保证的边界 |
| [P4₁₆](https://p4.org/wp-content/uploads/sites/53/p4-spec/docs/P4-16-v1.2.4.html) | typed metadata、显式持久状态与 target architecture |
