# Bridge 构造：来自硬件生成与网络协议的设计启示

[返回架构索引](README.md) · [Canonical Bridge 架构](typed-transaction-translation.md) ·
[事务转译 V1](translation-implementation.md) · [SystemProtocol](system-protocol.md)

本文解释 Bridge 架构为何采用 operation、stage、plan、executor 和 attachment 这些对象，并把硬件生成、
HLS/dataflow、延迟不敏感设计、互联网 gateway/translator 等领域的经验映射到本项目。外部系统用于帮助发现
问题形状，不作为 AMBA、TileLink 或本项目 API 的规范来源；真正进入工程的约束仍由所选 LinkProtocol、
VirtualDut profile 和 SystemProtocol 场景共同确定。

本文的结论可以先压缩成一句话：

> Bridge 构造不是找到一个 `A→B` 回调，而是先闭合两侧能力和转换政策，再执行可追踪的双向语义转译，
> 同时让队列、owner、容量和等待关系保持显式。

## 1. 先区分几种看起来相似的设备

“两个协议口之间有一个模块”还不足以判断它在做什么。至少需要区分下面四种构造：

| 构造 | 请求内容 | 两侧会话 | 典型内部工作 |
|---|---|---|---|
| relay | operation 基本不变 | 可以终结后重发，也可以按同协议转送 | route、仲裁、排队、ID/owner 关联 |
| transport bridge | 两端 wire protocol 不同，但可 decode/encode 同一种 operation form | 两条独立 LinkSession | codec、运输状态、correlation；中间可为 Identity stage |
| semantic bridge | operation 的粒度、属性或完成关系发生变化 | 两条独立 LinkSession | split/merge、属性政策、completion fold、调度 |
| encapsulation/tunnel | 原协议消息作为 opaque payload 被搬运 | tunnel endpoint 成对出现 | 封装、传输、解封装；中间网络不理解原 operation |

[HTTP Semantics 对 gateway 的定义](https://www.rfc-editor.org/rfc/rfc9110.html#section-3.7)提供了一个很好的
外部视角：gateway 在上游一侧表现为 server，在下游一侧重新作为 client 发起请求。AXI→APB Bridge 也会在
AXI 侧承担 subordinate 责任，在 APB 侧承担 requester 责任。因此 completion 不是原样“穿过”模块，而是
Bridge 接受下游结果后，按上游协议重新产生 completion。

[IPv4/IPv6 过渡架构](https://www.rfc-editor.org/rfc/rfc6144.html)还区分了 translation 与 tunneling：前者让
不同协议端点直接互通，后者保存原协议并借另一种网络运输。映射到芯片场景，`AXI over chip-to-chip link`
通常更接近一对 tunnel endpoint 加中间 SystemProtocol；它不应自动退化为一个孤立的 AXI→X Bridge。

这些名称不需要形成继承树。它们更适合作为 `BridgeProfile` 的构造维度，因为同一个具体 VirtualDut 可能同时
执行 route、transport conversion 和 semantic translation。

早期的[异构协议接口自动合成研究](https://iris.unitn.it/handle/11572/95174)已经把抽象 message 与 message 在
具体 signaling protocol 上的传输轨迹分开。这个分界支持 operation/codec 的设计，但不能替我们决定 burst、
atomic、ordering 或错误聚合政策；后者仍需类型化 semantic stage 和显式 profile。

## 2. Bridge 实际上同时涉及三张图

只画 `AXI → Transform → APB` 会遮住两个重要问题：为什么这条路径可以成立，以及它运行时可能等待什么。
工程应分别保存三张可以互相投影、但不能混成一张的关系图。

### 2.1 构造期约束图

它回答“这组组件能否组成一个有定义的 Bridge”：

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

这里传播的是 operation signature、宽度、基数、ordering、backpressure、属性保留和 completion 能力，而不是
运行中的事务。结果是一份不可变 `TranslationPlan`，或者一份能指出具体 mismatch 的构造失败报告。

[Diplomacy 的 TileLink 案例论文](https://carrv.github.io/2017/papers/cook-diplomacy-carrv2017.pdf)把 topology
发现、双向参数协商和实际 module elaboration 分开；[Chipyard 的 AdapterNode 文档](https://chipyard.readthedocs.io/en/1.12.2/TileLink-Diplomacy-Reference/NodeTypes.html)
也明确让 adapter 分别变换 client 与 manager 两个方向的参数。值得吸收的不是某个 Scala API，而是：一个
Bridge 不能只验证请求方向的输出类型，还必须从目标端反向验证 completion、ordering 和资源要求。

### 2.2 运行期语义转译图

它回答“一笔被接纳的工作怎样产生 child，又怎样形成上游结果”：

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

这张图保存类型、parent/child lineage、语义变化、错误聚合和完成条件。它不决定 FIFO 深度，也不因为某个
queue 满了就改变一笔事务“应该翻译成什么”。

### 2.3 运行期等待图

它回答“谁持有资源，又在等谁”：

```text
parent token ──holds──► parent slot
     │
     ├──waits──► ordering predecessor
     └──waits──► child completion
                         ▲
child token ──holds──► egress lease
                         │
                         └──waits──► downstream readiness/completion
```

这里出现 executor、FIFO、owner table、lease、empty/full、completion 和 ordering barrier。它才是局部阻塞与
SystemProtocol wait-for/deadlock 分析的输入。一个 burst 的 child 数量属于语义转译图；同时能发行几个 child
属于等待图。两者有关，但不是同一种计数。

## 3. 硬件生成领域提供的深层启示

### 3.1 Diplomacy：先协商边，再生成模块

Diplomacy 的重点并不是“自动插入任意转换器”，而是让相邻节点声明能力和需求，在构造期得到每条 edge 的
确定参数，并在不闭合时尽早失败。对本项目可以抽取为：

1. ingress/egress codec 分别声明能提供和需要的 operation 能力；
2. stage 不只是 `source_type → target_type`，还声明两个方向的能力关系；
3. planner 按顺序组合关系，检查每个中间不变量；
4. 闭合后冻结 plan，runtime 不再临时猜测转换政策；
5. construction report 保存选择了哪些 codec、stage、policy 和 executor profile。

这比单一 `required/guaranteed` 集合更强。某些约束需要双向传播，例如目标端只能返回较弱错误分类时，源端
必须提前选择聚合政策；源端要求保持 ID ordering 时，目标端和 executor 又必须共同给出实现条件。

当前 V1 是单入口、单出口的线性 plan，可以用确定的正向/反向遍历完成闭合。将来若 planner 处理 nexus、
多出口或可选 adapter，才需要在更一般的约束图上求解；不必为了模仿 Diplomacy 提前复制整套 LazyModule
体系。

### 3.2 Thin adapters：按差异维度组合，而不是按协议对复制

[Chipyard 的 Diplomatic Widgets](https://chipyard.readthedocs.io/en/1.12.2/TileLink-Diplomacy-Reference/Widgets.html)
展示了 fragment、width、source-ID、FIFO ordering、buffer 和 protocol conversion 等单一职责组件。真实的
TileLink↔AXI 路径会在 converter 前后组合 fragmenter、deinterleaver、user metadata 处理器，而不是假设一个
converter 能独自吸收所有差异。

本项目可以采用同样的构造原则：

```text
normalize shape
    → fragment or merge
    → width/lane transform
    → attribute policy
    → ID/order repair
    → target codec
```

这不是所有 Bridge 都要遵循的固定次序。每个 stage 应声明：

- 静态 precondition/postcondition；
- 对单笔 operation 的 `applicable` 条件；
- 保留、重算、削弱或拒绝的性质；
- completion/error 的反向规则；
- 与前后 stage 的排序依赖。

例如 fragmenter 可能只接受特定 burst/atomic 范围，width conversion 可能受 alignment 和可修改属性控制，
deinterleave 则必须位于产生相应 ordering pressure 的转换之后。Planner 的工作因而更像“受约束的 pass
pipeline 组合”，不是只按类型名字寻找最短路径。

### 3.3 HLS dataflow：stage 不是 persistent task

[AMD HLS 的 task/channel 模型](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Tasks-and-Channels)把持久任务与
有深度的通信 channel 分开；channel 读空或写满都可能使数据流停顿。[Dataflow Viewer](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Dataflow-Viewer)
也把阻塞原因和 FIFO occupancy 作为独立诊断事实。

这强化了本项目的分工：

| 对象 | 类比 | 应保存的内容 |
|---|---|---|
| `TranslationStage` | 无状态的 typed rewrite | lower/lift/fold 规则和适用边界 |
| executor/backend | persistent task/module | queue、cursor、owner、continuation、scheduler |
| capacity pool/channel | bounded FIFO/resource | lease、usage、empty/full 和等待原因 |
| plan | elaborated process graph | 已选择的 stage 顺序和 executor profile |

HLS 还区分顺序 FIFO 与需要整体块/随机访问的 PIPO 或 memory channel。对应到 Bridge，stage/executor 应声明
访问与物化方式：

| 模式 | 含义 | 例子 |
|---|---|---|
| `streaming_sequential` | child 可按 index 逐个生成和消费 | AXI burst 串行拆为 APB transfer |
| `materialize_block` | 下游开始前需要完整块 | 某些 merge、全块校验 |
| `random_access/reorder` | completion 可乱序到达并按 index 回填 | window-K、多 ID 或跨 child 重排 |

所以 `burst256` 表示 256 个 child obligation；在 serial APB executor 中，egress lease 峰值仍是 1。FIFO 深度
影响运行进度，甚至可能参与 deadlock，但它不把 256 份工作改写成 1 份工作。

### 3.4 CIRCT：把控制、数据和 buffer lowering 分开

[CIRCT Handshake](https://circt.llvm.org/docs/Dialects/Handshake/RationaleHandshake/)用显式的 join、fork、merge、
mux、buffer、source 和 sink 表达 dataflow；[ESI](https://circt.llvm.org/docs/Dialects/ESI/)则把 typed channel
与具体 valid-ready/FIFO 运输形式分开。这给本项目三个直接提醒：

- parent token、reply context 和 semantic payload 可以拥有不同表示与寿命；
- buffer insertion 是运输/实现 lowering，不应悄悄藏进 semantic stage；
- 多 fan-in/fan-out 需要显式 join/fork/arbiter/owner，crossbar 不能伪装成独立 Bridge 的简单堆叠。

如果某个入口不能 backpressure，容量检查必须在接纳之前完成，或由边界 gasket 提供足够且有声明的缓冲。
这是一项 transport capability，不应被 `AddressBurst→AddressAccess` stage 自行推断。

### 3.5 Latency-insensitive：允许延迟变化，不等于语义自动正确

[Latency-Insensitive Protocols](https://www2.eecs.berkeley.edu/Pubs/TechRpts/1999/3585.html)尝试把通信时延与
计算功能分开，但成立条件包括 patient/stallable process 和相应的事件序列等价。[Chisel 的 Decoupled
接口](https://www.chisel-lang.org/docs/explanations/interfaces-and-connections#the-standard-ready-valid-interface-readyvalidio--decoupled)
也只提供 ready、valid 和 bits 的传输形状；它不会自动证明 stalled payload 稳定等协议规则。

因此 Bridge profile 需要说明它保持哪一种等价：

| 等价层级 | 允许变化 | 不能由它单独保证 |
|---|---|---|
| operation/effect trace | 周期和内部 child 形状可变 | pin 周期一致、未声明的 ordering |
| link transaction/order | 可插入满足条件的等待和 buffer | 原始 cycle-by-cycle 波形 |
| pin/cycle | 只允许 profile 明确列出的时序差异 | 任意 queue/retiming |

插入 FIFO 或 register slice 通常只在前两种等价的特定条件下安全。它解决“何时传”，不替代 burst 拆分、
错误聚合和属性降级等语义政策。

### 3.6 成熟 AXI converter：串行只是一个 profile

[AMD AXI Infrastructure Cores](https://docs.amd.com/r/en-US/pg059-axi-interconnect/AXI-Infrastructure-Cores)
把 crossbar、width converter、clock converter、protocol converter、FIFO 和 register slice 作为可以按连接
需求组合的部件。[AXI4→AXI4-Lite conversion](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Conversion-to-AXI4-Lite)
的一种实现会限制接纳、保存原 ID 并把 burst 展开成 singles；[width conversion](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Width-Conversion)
又会根据 width、alignment、burst kind 和属性选择拆分或合并。

对本项目的结论是：

- serial AXI→APB/APB-like executor 是合理的 V1 profile，不是 AXI 规范规定的唯一实现；
- child count 可以是运行期 operation 的函数，stage 需要逐笔 legality guard；
- 上游 admission、下游并发和语义 cardinality 是三个不同参数；
- ID 的保存位置、response 聚合及 early completion 都必须成为显式 policy。

## 4. 网络协议领域提供的广角启示

### 4.1 Translator 的状态要按作用域和寿命分类

[RFC 7915](https://www.rfc-editor.org/rfc/rfc7915.html)区分 stateless 与 stateful IP/ICMP translation；
[Stateful NAT64](https://www.rfc-editor.org/rfc/rfc6146.html)进一步区分长期 binding、每 flow session 和临时
fragment storage。这比一句“Bridge 有状态”更有分析价值。

Executor 中的状态建议至少声明：

| 状态类 | 例子 | 典型 key/owner | 释放边界 |
|---|---|---|---|
| static configuration | route、attribute policy | plan/module | module replacement |
| transport assembly | AXI AW/W join | port + descriptor | decode complete/cancel/reset |
| shared binding | ID remap、return owner table | mapped ID/egress | 最后相关 transaction 完成 |
| per-parent semantic | fanout ledger、fold accumulator | parent token | parent completion/cancel |
| capacity lease | queue/egress slot | current owner | completion/cancel |
| performance-only | prefetch/cache、optional buffer | implementation | eviction/reset |
| diagnostic | lineage、fault provenance | evidence record | artifact retention policy |

每类状态还应说明 reset 后是丢弃、形成上游错误、等待 drain，还是能从其他事实重建。这样既不会把 FIFO
误当作 VirtualDut 的业务本体，也不会因为追求“无状态 transform”而隐藏必要的 correlation 状态。

### 4.2 Fragment/reassembly：重点是 lineage 与部分失败

[IPv6 fragmentation](https://www.rfc-editor.org/rfc/rfc8200.html#section-4.5)依赖端点、fragment ID、offset 和
超时来重组；NAT64 还要考虑乱序 fragment 和有限 storage。这与 `AddressBurst→AddressAccess[N]` 的结构相似：

- parent token 与 child index 构成 lineage；
- fold policy 说明是否允许乱序完成；
- duplicate、missing child、cancel/reset 和 partial failure 需要明确处理；
- 总工作量与同时占用的重组/执行容量分开记录。

但两者不是相同语义。APB child 可能已经产生外部副作用，也拥有逐 child completion；一个后续 child 失败
通常不能回滚先前写入。因此 `AddressBurst` 只表示有关联、有顺序关系的访问集合，不宣称事务原子性。

### 4.3 SemanticEffect：类型匹配还不够

网络 translator 会保留 payload、重写 header、重算 checksum、调整分片、合并错误，也可能拒绝无法表达的
字段。[RFC 7915 的转换规则](https://www.rfc-editor.org/rfc/rfc7915.html)说明了为何 `A→B` 类型相连并不
自动代表语义可接受。

本项目中的 stage/plan 应为每个重要性质记录 `SemanticEffect`：

| Effect | 含义 | AXI4→APB 例子 |
|---|---|---|
| preserve | 下游仍表达同一性质 | address、有效 byte data |
| recompute | 根据目标形状重新计算 | child address、lane/strobe |
| split/aggregate | 一份工作拆分或多份结果合并 | burst、response fold |
| rebind | identity 改由内部 context 保存 | AXI ID 不进入 APB |
| synthesize/default | 目标所需信息由 policy 产生 | 可配置默认 protection 属性 |
| weaken/drop | 保证或信息变弱 | 未支持的 USER/ordering 属性 |
| reject | 当前 profile 不接受 | 无法保持的 exclusive/atomic |

`CapabilityRelation` 回答 plan 是否闭合，`SemanticEffect` 回答闭合过程中具体改变了什么。后者必须进入
construction report，避免“能构造”被误读成“无损转换”。

### 4.4 completion 与诊断事实要保留两条线

[Proxy-Status RFC 9209](https://www.rfc-editor.org/rfc/rfc9209.html)区分面向客户端的协议结果与 intermediary
内部更具体的错误来源。Bridge 同样需要同时保存：

```text
wire-visible completion             internal provenance
AXI OKAY / SLVERR / DECERR          downstream error
                                     local route/policy result
                                     local resource/runtime fault
                                     reset or cancel
                                     malformed completion
```

Route miss 可以是正常 local completion 并编码为 `DECERR`；APB error 可以映射为 AXI response；executor
容量故障则仍可能是模型/runtime fault。即使最终 wire code 相同，也不应抹掉 `completion origin` 和真实原因。

### 4.5 TCP window 提醒我们不要混用“credit”

[TCP receive window](https://www.rfc-editor.org/rfc/rfc9293.html)是端点之间、与 sequence space 和后续更新行为
相关的协议状态。它通常受 buffer 影响，却不是“内部 FIFO 还剩几个 slot”的另一个名字。

映射到本项目应继续区分：

- protocol credit/window/READY：两端可观察的通信契约；
- parent/child obligation：尚未完成的语义工作；
- executor lease：当前被某 owner 占用的实现资源；
- configured capacity：允许接纳的局部上限。

这些量可以相互投影，例如 admission policy 根据本地 slot 决定 READY，但不能因此共用一套运行规则。

### 4.6 端到端原则限定局部 Bridge 的保证

[End-to-End Arguments in System Design](https://groups.csail.mit.edu/ana/Publications/PubPDFs/End-to-End%20Arguments%20in%20System%20Design.pdf)
与 [RFC 1958](https://www.rfc-editor.org/rfc/rfc1958.html)提醒：中间层缺少完整端点知识时，不应把局部机制
宣称为端到端保证。对本项目而言：

- Bridge 可以保证本地 request/completion 配对和已声明的转换政策；
- Bridge 可以报告它保持了哪些 link ordering；
- 它不能只凭本地 completion 证明最终存储持久化、全系统可见性或网络无死锁；
- 后三者需要 SystemProtocol、endpoint contract 或 scenario property 闭合。

这也不意味着 Bridge 应追求无状态。owner、queue 和 outstanding state 可能是履行局部协议责任所必需的；
关键是说明状态的作用域、失败语义，以及它是否只是性能优化。

### 4.7 P4：typed metadata 与持久状态分离

[P4₁₆ 规范](https://p4.org/wp-content/uploads/sites/53/p4-spec/docs/P4-16-v1.2.4.html)把 packet processing
组织为 parser、typed headers/metadata、control、deparser，并把跨 packet 状态放入显式 table/extern。
它与本项目的对应关系是：

```text
parser       ↔ ingress attachment decode/join
typed data   ↔ operation + opaque reply context
control      ↔ TranslationStage / Plan
extern       ↔ executor owner/FIFO/resource
deparser     ↔ egress attachment encode
architecture ↔ ExecutorProfile / VirtualDut capability
```

适合吸收的是“状态通过显式对象使用”，不让 stage 随意修改全局 backend。P4 主要描述单向 packet pipeline，
而 Bridge 还需要 completion 逆向传播，因此 lift/fold 和 parent lifecycle 仍是本项目自己的核心契约。

## 5. 落到本项目的构造方法

综合这些启示，一份 Bridge 不应按协议对手写完整状态机，而应按下面的顺序形成：

```text
1. 声明意图
   source port + target port + requested semantic profile
                         │
2. 选择 codec
   link events ↔ typed operation + reply context
                         │
3. 双向协商
   request capability 向下；completion/requirement 向上
                         │
4. 组合有序 stage
   pre/postcondition + applicability + SemanticEffect + fold
                         │
5. 选择 executor profile
   serial/window-K/reorder；storage/access mode；capacity
                         │
6. 校验三张图
   construction closure；translation lifecycle；runtime resource boundary
                         │
7. 装配具体 VirtualDut
   ports + attachments + immutable plan + persistent backend
                         │
8. 交给 SystemProtocol
   topology、route ownership、return closure、端到端 property
```

建议的 `BridgeProfile` 至少表达：

```text
BridgeProfile
├── ingress/egress role
├── source/target operation signature
├── supported direction and operation predicates
├── ordering profile
├── capability relation
├── semantic effects and unsupported policy
├── executor/storage profile
├── completion/error mapping
├── equivalence level
└── reset/cancel/failure contract
```

`TranslationStage` 的构造期契约则至少回答：

```text
StageContract
├── source/target signature
├── cardinality
├── forward offer projection
├── backward requirement projection
├── static preconditions/postconditions
├── per-operation applicability
├── semantic effects / preservation obligations
├── lower + lift/fold
└── provenance
```

这里不要求第一版立即建立通用自动搜索器。V1 可以由具名 preset 选择 codec、stage 顺序和 serial executor，
再让公共 plan validator 执行同一套闭合检查。这样保留手工取舍自由，同时避免每个 preset 复制执行核心。

## 6. 对 V1 的直接调整

在不扩大 V1 runtime 功能的前提下，当前文档/API 设计应吸收以下内容：

1. 用构造期约束图、运行期转译图和运行期等待图分别解释 plan、stage 与 executor；
2. `CapabilityEffect` 演进为双向 relation，至少能闭合 request 与 completion 两个方向；
3. stage 增加 pre/postcondition、逐 operation applicability 和 `SemanticEffect`；
4. completion fold 同时记录 wire result 与 completion origin/fault provenance；
5. executor profile 声明 sequential/materialized/reorder 访问模式和 equivalence level；
6. executor state 声明 owner、key、lifetime、release 和 reset/cancel 行为；
7. plan validator 检查 stage ordering，并保存 catalog rule 与 parent/child lineage provenance；
8. 把 serial AXI→APB 写成一个默认 profile，而不是协议唯一实现。

仍然留到 V1 之后的内容包括自动 stage 搜索、blocked/deferred runtime、parallel child、reorder、timeout、
paired tunnel、crossbar nexus 和多节点 deadlock 闭合。它们需要扩充 executor 或 SystemProtocol，不必为了让
第一版“看起来通用”而提前混入。

## 7. 哪些经验不应直接照搬

- Diplomacy 假定构造者控制静态 topology 和 RTL elaboration；本项目还要描述外部 DUT 和已有 trace，因此
  构造期协商不能取代 runtime monitor。
- HLS 常见的单 producer/single consumer FIFO 模型覆盖不了 AXI 多 channel、ID reorder 和 crossbar owner；
  它适合说明 task/channel/resource 分离，不是完整总线执行模型。
- Latency-insensitive 方法在 patient/stallable 边界和相应 trace equivalence 下成立；reset、timeout、精确
  cycle 与不可回压端口需要额外契约。
- TCP retransmission、fragment timeout 或 NAT binding 不会因为“结构相似”就自动成为总线 Bridge 行为；
  只有目标协议/profile 需要时才加入。
- 一个通用 address form 不应吞并 stream、atomic 或 coherent domain。少量稳定 semantic waist 有利于复用，
  一个无边界的万能 operation 反而会把语义差异藏进 optional fields。

## 8. 参考资料与各自用途

| 来源 | 本文吸收的内容 |
|---|---|
| [Automatic Synthesis of Interfaces between Incompatible Protocols](https://iris.unitn.it/handle/11572/95174) | 抽象 message 与 signaling protocol 轨迹的分离 |
| [Diplomatic Design Patterns](https://carrv.github.io/2017/papers/cook-diplomacy-carrv2017.pdf) | topology 发现、双向参数协商、elaboration 分离 |
| [Chipyard Node Types](https://chipyard.readthedocs.io/en/1.12.2/TileLink-Diplomacy-Reference/NodeTypes.html) | adapter 与 nexus、双向参数函数 |
| [Chipyard Widgets](https://chipyard.readthedocs.io/en/1.12.2/TileLink-Diplomacy-Reference/Widgets.html) | thin adapters、顺序依赖、ID/order/width/fragment 处理 |
| [Chisel ReadyValid/Decoupled](https://www.chisel-lang.org/docs/explanations/interfaces-and-connections#the-standard-ready-valid-interface-readyvalidio--decoupled) | 运输接口形状不等于协议完整保证 |
| [AMD HLS Tasks and Channels](https://docs.amd.com/r/en-US/ug1399-vitis-hls/Tasks-and-Channels) | persistent task、FIFO/PIPO、容量与阻塞 |
| [CIRCT Handshake](https://circt.llvm.org/docs/Dialects/Handshake/RationaleHandshake/) / [ESI](https://circt.llvm.org/docs/Dialects/ESI/) | typed channel、fork/join、buffer lowering |
| [Latency-Insensitive Protocols](https://www2.eecs.berkeley.edu/Pubs/TechRpts/1999/3585.html) | 计算/通信解耦的前提与等价边界 |
| [AMD AXI Infrastructure Cores](https://docs.amd.com/r/en-US/pg059-axi-interconnect/AXI-Infrastructure-Cores) | converter、FIFO、register slice 与 crossbar 的组合 |
| [HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html#section-3.7) | gateway 在两侧承担不同协议角色 |
| [IPv4/IPv6 Translation Framework](https://www.rfc-editor.org/rfc/rfc6144.html) | translation 与 tunnel、场景/profile 边界 |
| [IP/ICMP Translation](https://www.rfc-editor.org/rfc/rfc7915.html) / [Stateful NAT64](https://www.rfc-editor.org/rfc/rfc6146.html) | 语义映射、显式状态、错误与 fragment 资源 |
| [IPv6 Fragmentation](https://www.rfc-editor.org/rfc/rfc8200.html#section-4.5) | lineage、重组、乱序与部分失败边界 |
| [TCP](https://www.rfc-editor.org/rfc/rfc9293.html) | 协议 window 与本地 buffer/lease 的区别 |
| [End-to-End Arguments](https://groups.csail.mit.edu/ana/Publications/PubPDFs/End-to-End%20Arguments%20in%20System%20Design.pdf) / [RFC 1958](https://www.rfc-editor.org/rfc/rfc1958.html) | 局部机制与端到端保证的边界 |
| [P4₁₆](https://p4.org/wp-content/uploads/sites/53/p4-spec/docs/P4-16-v1.2.4.html) | typed metadata、显式持久状态与 target architecture |
