# Bridge 与类型化事务转译

[返回架构索引](README.md) · [构造方法的跨领域启示](bridge-construction-insights.md) ·
[Integration 与 binding](technical-route/04-integration-and-binding.md) ·
[SystemProtocol 组网](network-construction.md) · [当前状态](migration-status.md)

Bridge 是一个具体、具名、多端口的 `VirtualDut`。它在两侧 LinkProtocol 之间保存一笔通信的业务含义，
同时改变线上编码、事务粒度、属性表示或执行顺序。类型化事务转译是构造这种 VirtualDut 的方法，不是
位于 VirtualDut 与 SystemProtocol 之间的新语义层。

本文是 bridge/Transform 的 canonical 架构说明。当前代码迁移顺序和验收边界单独记录在
[事务转译 V1 实施计划](translation-v1-plan.md)。

| 状态 | 本文中的含义 |
|---|---|
| 已有 bridge witness | full AXI4→APB 仍使用 pair-specific backend；AXI4-Lite→APB recipe 复用 `SingleIngressAddressFabricBackend`；full AXI burst accesses 当前由 attachment 物化 |
| 已实现的公共内核 | `OperationSignature`、`BridgeProfile`、typed unary/fanout stage、双向 plan closure、fanout ledger、capacity lease 与 operation-level serial executor |
| 下一段迁移 | attachment-aware 事务式 encode/decode 外壳、`AddressBurst`/address stages，以及 AXI4→APB 对公共 executor 的接入 |
| Later | blocked/deferred demand、pin-level backpressure、并行 child、width merge、crossbar executor 和自动多跳搜索 |

公共内核位于 `protocol_model.virtual_dut.translation`。它现在接收已经 decode 的 operation，不直接接收
`CanonicalEvent`；因此它已经是可执行的 bridge 构造底座，但还不会脱离 attachment 自动装配协议对。

## 1. Bridge 的语义位置

一条 bridge 路径包含两种不同方向的工作：request 向下游翻译，completion 向原请求方折返。

```text
source LinkProtocol
        │ canonical events
        ▼
ingress attachment / codec
        │ typed parent operation
        ▼
TranslationPlan + executor
        │ typed child operation
        ▼
egress attachment / codec
        │ canonical events
        ▼
target LinkProtocol

completion 沿相反方向 decode、lift/fold、encode
```

各对象的职责如下：

| 对象 | 描述的事实 | 不负责 |
|---|---|---|
| `LinkProtocol` | 一个 link 上允许出现的 event、角色和先后关系 | 跨端口事务转换 |
| attachment/codec | 单端口 event 与 operation 之间的编码 | 跨端口调度、共享 owner |
| operation form | 一笔协议无关工作的类型和数据 | 何时发行、占多少容量 |
| `TranslationStage` | 两种 operation form 间的 lower/lift 关系 | parent 队列和调度算法 |
| `BridgeProfile` | 本次转换承诺的适用范围、语义效果、ordering、等价层级和失败政策 | 保存运行中的 owner/queue |
| `TranslationPlan` | 已闭合的 stage、双向能力、语义效果和 provenance | 调度/容量选择与具体运行状态 |
| executable binding | plan、executor profile、两侧 codec/port binding 的一次构造选择 | 定义协议本身或隐藏 topology |
| plan executor/backend | 执行 plan，保存队列、lease、owner 和 continuation | 定义两侧 LinkProtocol |
| integration recipe | 选择端口、attachment、plan 和 backend 并装配 VirtualDut | 创造另一套运行语义 |
| `SystemProtocol` | 把 bridge 端口接入 topology，检查端到端闭合 | 反射 backend 私有状态 |

这个分法保留了一个重要事实：装配完成的产物是 VirtualDut，而协议相关依赖的汇合位置是 integration。
“产物属于哪一层”和“装配代码放在哪个包”因而可以有不同答案。

从协议角色看，Bridge 更接近一个两侧 gateway：它终结 ingress LinkSession，在 egress 侧以另一角色发起
新的 LinkSession。相同 operation 只改变运输编码时，可以使用 Identity translation；operation 粒度、属性或
completion 关系变化时，才需要 semantic stage。若原协议作为 opaque payload 被成对封装/解封装，则更接近
tunnel endpoint 和 SystemProtocol recipe，不应与单个 Bridge 混称。

### 1.1 三张相互关联的图

Bridge 构造和执行需要区分三种关系：

| 图 | 时间 | 回答的问题 | 主要对象 |
|---|---|---|---|
| 构造期约束图 | elaboration | 两端能力、stage 顺序和转换政策能否闭合 | port offer/requirement、codec、stage contract、plan |
| 运行期语义转译图 | 每笔事务 | parent 怎样产生 child，completion 怎样 lift/fold | operation、envelope、lineage、semantic effect |
| 运行期等待图 | 每个执行状态 | token 持有什么、等待什么，哪里可能阻塞 | executor、owner、queue、lease、demand |

三者可以互相投影，但不能合并为一份计数。例如 burst 的 child count 位于语义转译图，serial executor 的
active slot 位于等待图；构造期只验证两者的资源政策相容。相关领域依据和不适用边界见
[Bridge 构造的跨领域启示](bridge-construction-insights.md)。

## 2. 显式事务转译的必要性

### 2.1 控制协议数量带来的组合增长

若每一对协议都拥有独立 backend，`N` 种协议可能诱导出接近 `N²` 个实现。很多实现会重复 burst 拆分、
地址重映射、属性投影、串行调度和错误聚合。

类型化转译把变化拆成两类：

- 每种协议提供到少量 operation form 的 codec；
- 每种真实语义差异提供可复用 stage。

新增一个能够编码 `AddressAccess` 的协议时，可以复用已有 address stage 和 executor。只有出现 atomic、
coherence、message ordering 等新的语义差异时，才需要增加新的 form 或 stage。常用协议对仍可保留具名
preset，但 preset 只是审计过的装配方案，不拥有另一套执行核心。

### 2.2 让 request 与 completion 保持成对

事务转换不是单向字段映射。AXI burst 拆成多个 APB transfer 后，还必须知道：

- 每个 child 属于哪个 parent；
- child 失败怎样映射为 parent response；
- read data 怎样恢复 beat 位置；
- 何时可以释放 parent context；
- reset/cancel 时哪些 obligation 仍未解除。

这些关系要求 stage 同时声明正向 lower 和反向 lift/fold。只有 `map(event)` 的 callback 可以产生输出，却
无法单独证明完成关系闭合。

### 2.3 把语义变化和执行策略分开

“一个 burst 包含 256 个 child”是事务基数；“同时允许几个 child 运行”是调度策略；“为它们保存多少
descriptor/result”是存储策略。混在一个 backend profile 中，会让功能正确性、性能选择和容量故障难以
分别解释。

分开以后，同一个 `BurstToAccess` stage 可以使用 serial、window-K 或其他 scheduler，而不改变 burst 的
业务含义。SystemProtocol 也能从显式 lease/demand 派生 wait-for 关系，而不是从协议对类名猜测资源。

### 2.4 让构造失败可解释

一份 plan 应记录每个属性是 preserve、default、remap、reject 还是 emulate，并记录选择这些策略的来源。
当两侧能力不能闭合时，elaboration 可以指出具体的 operation form、stage 或 capability mismatch，而不是
只报告“没有 AXI4→X recipe”。

## 3. Operation form：被转译的类型化语义

Operation form 描述模块实际处理的工作，不复刻某种协议的全部 wire fields。一个 form 至少包含 request
类型和稳定的语义名称；有 request/completion 生命周期的 family 还声明 completion 类型，单向 stream 可用
`Unit`/无 completion signature 表示。这个边界可用 `OperationSignature` 表示。

```text
OperationSignature
├── request form
├── completion form
└── semantic domain / version
```

Attachment decode 的产物还需要保留协议返回所需的 opaque context。它不属于 operation form，而由 executor
连同内部 token 一起装入 parent envelope：

```text
DecodedOperation                 ParentEnvelope
├── operation ───────────────┐   ├── parent token（executor 分配）
└── reply context（opaque）──┴──►├── semantic operation
                                 └── reply context / ingress binding
```

Stage 只读取 semantic operation；reply context 原样保存，parent result 形成后再交回 ingress attachment。
AXI 的 ARID/AWID、读写方向和 descriptor provenance 因而可以参与 R/B 编码，却不会污染通用 address form。
Parent token 由 executor 为每次接纳分配，不能直接复用 AXI ID；同一个 AXI ID 可以先后对应多笔
outstanding parent。

当前最重要的 form 是：

| Form | 含义 | 典型使用者 |
|---|---|---|
| `AddressBurst` | 一笔有 beat geometry、属性和有序结果关系的地址 burst | full AXI ingress、后续可选 AHB burst codec |
| `AddressAccess` / `AccessResult` | 一次原子 byte-range read/write 及其结果 | APB、AXI4-Lite、AHB accepted beat、single-beat AXI |
| `StreamTransfer` | 一次带 lane mask、packet boundary、ID/destination 的流 beat | AXI4-Stream |

`AddressBurst` 表示有序的地址访问集合，不宣称整个 burst 是一个原子内存操作。它保存 count、geometry、
attributes 和必要的 beat-local payload；AXI ID 等 wire identity 留在 parent envelope 的 ingress reply context，
不进入通用 form。

并非所有协议都应该压成 `AddressAccess`。TileLink atomic、CHI coherent message 或 cache maintenance 可能需要
新的 semantic domain。Stream 与 AddressAccess 之间也没有默认路径；DMA 是一个具名、状态化 VirtualDut，
不能由 planner 根据两个端口类型自行猜出。

当前 AMBA attachment 与目标 form 的关系如下：

| 端口 profile | 接收协议时 decode 成 | 驱动协议时 encode 自 | 架构方向 |
|---|---|---|---|
| AXI4 subordinate | 私有 `Axi4BurstRequest(AddressAccess[])` | — | 抽出协议无关 `AddressBurst` |
| AXI4 serialized manager | — | 单笔 `AddressAccess` | V1 保持 single-beat egress |
| AXI4-Lite subordinate/manager | `AddressAccess` | `AddressAccess` | 复用 address leaf stages |
| AHB subordinate/manager | 每个 accepted beat 为 `AddressAccess` | `AddressAccess`（SINGLE） | 复用 address leaf stages |
| APB completer/requester | `AddressAccess` | `AddressAccess` | 严格串行 address leaf |
| AXI4-Stream receiver/transmitter | `StreamTransfer` | `StreamTransfer` | 独立 stream domain |

## 4. TranslationStage：类型之间的双向关系

Operation form 是名词，`TranslationStage` 是带类型的箭头。Stage family 的共同元数据包括：

- source request/completion signature；
- target request/completion signature；
- `1→1`、`0/1` 或 `1→N` 等基数；
- request 的 lower/split/rewrite；
- child completion 的 lift 或增量 fold；
- 请求方向的 offer projection 与 completion 方向的 requirement projection；
- 静态 precondition/postcondition 和逐 operation applicability；
- 属性 preserve/recompute/split/aggregate/rebind/default/weaken/reject 等 `SemanticEffect`；
- completion/error mapping、origin 和 preservation obligation；
- parent→child lineage、本地完成条件和 rule provenance。

V1 根据基数提供两种执行形状。单值 stage 适合 1→1 或 0/1 leaf 变换：

```python
class UnaryTranslationStage[ParentReq, ParentResult, ChildReq, ChildResult]:
    source: OperationSignature
    target: OperationSignature
    cardinality: StageCardinality
    contract: StageContract

    def applicable(self, parent: ParentReq) -> Applicability: ...
    def lower(self, parent: ParentReq) -> UnaryLowering[ChildReq]: ...
    def lift(self, context: object, child_result: ChildResult) -> ParentResult: ...
```

1→N stage 使用索引式 child 生成和增量 fold，避免接口强制预先物化全部 child/result：

```python
class FanoutTranslationStage[ParentReq, ParentResult, ChildReq, ChildResult]:
    source: OperationSignature
    target: OperationSignature
    cardinality: StageCardinality
    contract: StageContract

    def applicable(self, parent: ParentReq) -> Applicability: ...
    def begin(self, parent: ParentReq) -> FanoutStart: ...
    def child_at(self, context: object, index: int) -> ChildReq: ...
    def fold_one(
        self,
        context: object,
        fold_state: object,
        index: int,
        child_result: ChildResult,
    ) -> object: ...
    def finish(self, context: object, fold_state: object) -> ParentResult: ...
```

`FanoutStart` 保存 child count、stage context 和初始 fold state。`FanoutLedger` 决定何时允许调用
`finish()`，stage 不再维护另一份 issued/completed 计数。AXI write 可以用 O(1) status accumulator；V1 的
AXI read 仍可保存有序 beat results，逐 child 向上游流式返回属于后续 executor profile。

`UnaryLowering` 与 `FanoutStart` 分别使用适合自身基数的 DTO，但都需要表达以下三类语义结果：

| 结果 | 含义 | 示例 |
|---|---|---|
| child expansion | 产生可向下游发行的 child | burst 生成多个 `AddressAccess` |
| local completion | 不访问下游即可形成正常结果 | route miss 映射为 `DECODE_ERROR` |
| rejection | 当前 conversion policy 无法表达 | 目标协议无法保留且策略未允许丢弃的属性 |

容量不足不属于 stage 的语义转换结果。它由 executor 的 admission/resource policy 判定；这样更换
scheduler 不会改变 stage 对一笔事务“应该变成什么”的定义。

V1 沿用当前同步 runtime 的边界：typed pool 先产生 `CapacityFailure`，operation executor 再把它保留为
translation fault detail，并投影成带 pool、usage 和 owner 信息的 VirtualDut-scope fault。完整端口
`VirtualDutModel` 的 fault/READY 映射属于 attachment-aware 外壳。
等非立即 emission 进入运行时后，同一份资源状态再产生 typed `ResourceDemand`/blocked 状态；READY/
backpressure 的 pin-level 投影还需要 observation/runtime 闭合。这里把资源 DTO 设计成可投影，是为了保留
后续演进路径，并不把异步阻塞塞进 V1。

### 4.1 首批 address stages

| Stage | Request 方向 | Completion 方向 |
|---|---|---|
| `BurstToAccess` | `AddressBurst → AddressAccess[N]` | N 个 `AccessResult` 形成 burst result |
| `AddressWindow` | route check 与地址 remap | response 原样返回；miss 可 local-complete |
| `AttributePolicy` | preserve/default/project/reject attributes | 必要时恢复 parent-facing 表达 |
| `TransferShapeGuard` | 检查 width、alignment、byte enable | response 原样返回 |
| `Identity` | 1→1 保持 operation | 1→1 保持 result |
| `WidthSplit/Merge` | 后续按 byte/lane 拆分 | 重组 read data 与错误状态 |

### 4.2 Stage contract 与双向能力关系

类型相连只是必要条件。一个 stage 还必须回答“在什么条件下能用”和“转换后哪些性质仍成立”。建议的
`StageContract` 由以下关系组成：

```text
source offer ──forward projection──► target offer
source requirement ◄──backward projection── target requirement

source operation ──applicability──► accepted / local result / rejected
source property  ──SemanticEffect─► target property + completion rule
```

静态关系用于 plan construction，例如 source/target width、ordering capability 和 backpressure 能力；逐笔
`applicability` 用于 burst kind、alignment、attribute value 等运行期才知道的条件。后者仍是已声明的转换政策，
不等同于 executor 容量临时不足。

`SemanticEffect` 至少区分：

| Effect | 含义 |
|---|---|
| preserve | 两侧表达同一性质 |
| recompute | 按目标 shape 重新计算 |
| split/aggregate | 请求拆分或 completion 聚合 |
| rebind | identity/metadata 转由 reply context 或 owner 保存 |
| synthesize/default | 按显式 policy 产生缺省信息 |
| weaken/drop | 保证或信息变弱，并在 report 中显露 |
| reject | 当前 profile 不接纳该 operation |

`CapabilityRelation` 负责判断完整 plan 是否闭合；`SemanticEffect` 负责说明闭合过程中发生了什么。Planner
不能因为最终 signature 相同就省略中间的 loss、ordering 或 completion 政策。

### 4.3 与其他“变换”概念的区别

本工程已有多种转换，但它们解决的不是同一个问题：

| 机制 | 作用域 | 作用 |
|---|---|---|
| `compose_fragments()` | 同一语义域 | 合取多个规则 fragment |
| `LinkProtocol.refine()` | 同一 link language | 单调收窄合法行为 |
| protocol embedding/variant | 协议 schema/event | 补默认字段或构造协议变体 |
| observation lowering | 表示层 → link event | pin/frame 解释成 `CanonicalEvent` |
| attachment codec | link event ↔ operation | 单端口协议编码 |
| transaction translation | operation ↔ operation | 跨端口 split/rewrite/fold |
| artifact renderer | model/trace → 文档格式 | 展示与存储投影 |

项目现有 bottom-up 方法擅长从小规则构造更具体的同域协议。类型化转译补充的是横向的 `A→B` 关系，
并不取代 bottom-up 思维；复杂 plan 仍由较小 stage 组合而来。

## 5. 事务生命周期与容量

Bridge 执行时需要把四种量分别记录：

| 概念 | 回答的问题 | 典型状态 |
|---|---|---|
| transaction token | 这是谁的一笔工作 | executor 内部唯一的 parent token；不等同于 wire ID |
| work obligation | 还欠多少 child/completion | total、issued、completed |
| capacity lease | 当前谁占用了有限资源 | pool、amount、owner |
| stored state | 为以后继续实际保存什么 | descriptor、cursor、payload、result fold |

它们的作用域也不同：

| 对象 | 作用域 | 责任 |
|---|---|---|
| `ParentEnvelope` | bridge VirtualDut runtime | 关联内部 token、semantic operation、reply context 与 ingress binding |
| `CardinalityToken` | LinkProtocol monitor | 检查本 link 声明的 beat/completion 数量 |
| `FanoutLedger` | bridge VirtualDut runtime | 驱动 parent→child 的 issued/completed/inflight 生命周期 |
| `ResourceDecl` | 声明与分析投影 | 表达某资源对外可见的种类和边界 |
| `CapacityPool/Lease` | VirtualDut 执行状态 | 表示一次运行中具体的占用者和数量 |

Concrete pool/profile 应派生 `ResourceDecl` 投影，避免分别维护两份容量事实。Link monitor 可以与
VirtualDut ledger 共享 token/obligation 词汇，但不承担 bridge 调度。

“stored state”还需要按用途和寿命细分，避免只用“有状态/无状态”描述整个 Bridge：

| 状态类 | 例子 | 释放或恢复边界 |
|---|---|---|
| static configuration | route、attribute policy | module/plan replacement |
| transport assembly | AW/W join、partial request | decode complete、cancel 或 reset |
| shared binding | ID remap、return owner table | 最后相关 transaction 完成 |
| per-parent semantic | fanout ledger、fold accumulator | parent completion 或 cancel |
| capacity | queue slot、egress lease | completion 或 cancel |
| performance-only | optional buffer/cache | eviction 或 reset；不得改变业务结果 |
| diagnostic | lineage、fault provenance | evidence retention policy |

每个 concrete state 应声明 owner、key、lifetime、release、reset/cancel 后果，以及能否从其他事实重建。
completion 同时保存 wire-visible result 和内部 origin；`DOWNSTREAM`、`LOCAL_POLICY`、
`LOCAL_RESOURCE_FAULT`、`RESET_OR_CANCEL` 等来源不能仅因最后映射成同一 response code 而丢失。

### 5.1 256-beat burst 的账目

以 AXI4 burst 经严格串行 APB bridge 为例：

| 量 | 数量 | 原因 |
|---|---:|---|
| parent transaction identity | 1 | 一笔 AXI parent burst |
| bridge parent slot 峰值 | 1 | 所有 child 完成前保留 context |
| child work obligations | 256 | 需要执行 256 笔 APB transfer |
| APB active lease 峰值 | 1 | serial scheduler 每次只发行一个 child |
| child lease 累计借还 | 256 次 | 同一个执行 slot 反复使用 |
| semantic parent result | 1 | executor 把 child results fold 成一个 burst result |
| AXI read link completion | 256 个 R event | ingress codec 把一个 read burst result 编码成逐 beat R |
| AXI write link completion | 1 个 B event | ingress codec 把聚合 write result 编码成 B |

这里不是“一份 credit 变成 256 份同种 credit”。一个 parent token 打开了 256 个 work obligation；并发
容量由调度窗口和下游能力决定：

```text
peak child lease = min(child count, scheduling window, downstream capacity)
```

若实现预先物化全部 child，还会占用相应 child-buffer entries。采用 descriptor + cursor 的 lazy expansion
可以降低 child 描述存储。V1 的存储边界是：

| Parent | Request storage | Result storage |
|---|---|---|
| AXI read burst | descriptor/cursor 可保持 O(1) | 暂缓逐 child 返回，因此有序 read data 为 O(N) |
| AXI write burst | 已接纳的 W payload 本身为 O(N) | response status 可增量聚合为 O(1) |

这些是 storage/fold policy，不改变 1→N 的事务语义，也不把整个 burst translation 笼统宣称为 O(1)。

### 5.2 资源与 deadlock 的联系

Wait-for 分析关心“某 token 持有什么 lease，同时等待什么 demand”。V1 严格串行路径发行 child 后持有
egress lease，等待的是该 child completion；queued parent 等待前序 parent 结束，并不会在当前 profile 中
形成一个尚未取得的共享 egress-slot demand。未来 window/shared-pool/crossbar profile 才会出现“持有某些
lease、等待另一个 slot”的动态 demand。Fanout 数量只表示总工作量，本身不能证明 deadlock。

V1 先建立 lease、obligation 和可诊断的 admission failure；后续引入非立即 emission 时，再把未满足的
admission 或执行条件转成动态 demand，供 SystemProtocol 组合多个节点的等待边。

CHI Link Credit 等在线上传递的显式 credit 仍由相应 LinkProtocol 维护。它们以后可以投影到系统资源图，
但不与本地 FIFO slot 共用一套链路运行规则。

## 6. TranslationPlan 与执行 backend

`TranslationPlan` 是构造期校验并由 compiler witness 封住的无运行状态结果。它会冻结 closure/report 并在
执行前核对 stage metadata；stage 实现本身仍须遵守无跨事务可变状态合同。V1 的有序 stage 结构允许
fanout 前后的 1→1 转换，但至多包含一个 fanout：

```text
TranslationPlan
├── source / target OperationSignature
├── BridgeProfile / equivalence level
├── zero or more 1→1 prefix stages
├── zero or one 1→N expansion
├── zero or more 0/1 or 1→1 suffix stages
├── bidirectional capability closure / semantic effects
└── provenance and rejection diagnostics
```

调度、容量与端口绑定不是 semantic plan 的字段。当前 `SerialExecutorProfile` 单独选择 parent capacity 和
serial egress slot；T4 再用 `ExecutableTranslationBinding`（名称可在实现时微调）把 plan、executor profile、
ingress/egress codec 与具体 port binding 封成一次可审计构造，并把这些选择加入完整 construction provenance。
这样同一个语义 plan 可以换 scheduler，又不会让 plan 报告它尚未证明的运行资源性质。

Plan compiler 同时闭合正向和反向类型。执行顺序为：

```text
request:    prefix.lower → expansion.child_at → suffix.lower → egress
completion: egress → suffix.lift → expansion.fold_one/finish → prefix.lift → ingress
```

因此 suffix 改写后的 child result 必须先 lift 回 expansion 的 target result，prefix context 则保留到整个
parent 完成后再逆序 lift。这个反向闭合是 plan 校验的一部分，不由 recipe 临时拼 callback。

### 6.1 构造期闭合与 stage 顺序

Plan construction 按下面的逻辑进行：

```text
source/target port offers + requested BridgeProfile
    → choose ingress/egress codecs
    → propagate request capabilities forward
    → propagate completion requirements backward
    → validate ordered stage pre/postconditions
    → accumulate SemanticEffects and unsupported policies
    → choose executor/storage/resource profile
    → freeze plan + construction report
```

线性 V1 可以用一次有序的正向与反向校验完成；未来 nexus 或可选 stage graph 才可能需要更一般的约束求解。
Stage 列表不是任意可交换集合。fragment、width、attribute、ID/order repair 之间的先后由各自 pre/postcondition
决定，plan validator 应报告第一个不闭合的中间不变量，而不是只报告“没有协议对 recipe”。

Plan 还声明保持的等价层级：operation/effect trace、link transaction/order 或 pin/cycle。Buffer、register
slice 或 CDC lowering 通常属于运输实现；只有在相应 stallability、reset 和等价条件闭合后才能加入，不能由
semantic stage 隐式产生。

### 6.2 Executor 的运行状态

Plan 本身不保存运行状态。已实现的 operation executor 保存：

- pending parent queue；
- 每个 parent 的 translation frame、`FanoutLedger` 和 continuation；
- active child 与 egress owner；
- 已获取的 resource leases；
- result fold state。

待实现的 attachment-aware backend 另外保存两侧运输状态和 emission 编码候选，并把 attachment 与
executor 的候选状态作为一个整体提交。二者不应在当前公共 executor 中混成万能协议 payload 接口。

等待原因也应结构化为 `input_empty`、`output_full`、`await_completion`、`ordering_barrier` 等类别。V1 同步
runtime 仍可把无法接纳表示为 fault；这些分类为后续 blocked/deferred transition 和 SystemProtocol wait-for
投影保留稳定语义。

Translation frame 保存语义数据，例如 expansion cursor、stage context 和 result accumulator；`FanoutLedger`
只保存 total/issued/completed/inflight 等生命周期账目。Scheduler 消费 ledger 与 pool 状态，不再复制一份
completion count。

一次 bridge 执行中的状态所有权如下：

| 状态或资源 | Runtime owner | 释放或转移边界 |
|---|---|---|
| pending AW、pre-AW W、partial W | ingress attachment state | 完整 parent operation 形成时释放或显式移交 payload |
| parent envelope、queue、continuation | executor | parent result 连同 reply context 被 ingress attachment 编码完成 |
| payload beat storage | attachment 或 translation frame 中的唯一 owner | child 消费、cancel/reset 或 parent 完成 |
| child scheduling window | executor capacity pool | child completion/cancel |
| APB sole pending 等单端口运输状态 | egress attachment state | 该协议 completion 被 decode |
| child→parent lineage | executor `FanoutLedger` | child obligation 解除 |
| result tuple/fold accumulator | translation frame | parent result 形成 |
| link outstanding | 各自 `LinkSession` | 对应 link completion 被接受 |

同一个 runtime 资源只由一个 owner 更新；`ResourceDecl`、boundary capability 和可视化 usage 从该 owner
投影，不再维护另一份可修改计数。

一个严格串行 executor 的生命周期是：

```text
accept request fragments
  → ingress attachment owns partial transport state

form complete parent
  → attachment returns DecodedOperation
  → executor assigns token and owns ParentEnvelope
  → acquire parent lease
  → create fanout obligation(total=N)

issue child[i]
  → acquire one egress execution lease
  → record parent/child correlation

complete child[i]
  → fold result
  → release egress lease
  → advance ledger

all children complete
  → form one semantic parent result
  → ingress attachment uses reply context to encode link completion event(s)
  → successful encoding releases parent lease and envelope
```

Route miss 等 local completion 直接推进 ledger，不获取 egress lease。Normal completion 与模型故障保持
分离，便于 bridge 正确表达目标地址不存在、只读写入等设备结果。

AXI read 中，bridge 的一个 semantic parent result 与 AXI link 上的多个 R event 是两个作用域。Parent envelope
在 codec 成功形成全部 emissions 后释放；`LinkSession` 的 AR→R cardinality obligation 随各个 R event 被接受
而逐项解除，不与 `FanoutLedger` 共用 remaining count。V1 parent scheduler 按“完整 parent operation 形成顺序”
严格 FIFO；它能保持同 ID 返回顺序，也会对不同 ID 施加比 AXI 基础规则更强的串行限制。

## 7. 从 Plan 装配 Bridge VirtualDut

Integration recipe 是 composition root：它可以同时依赖协议 attachment、通用 stage、executor 和
VirtualDut boundary。装配过程如下：

```text
ingress ProtocolPort + ingress attachment
                     │
                     ├─ validated TranslationPlan
                     │
egress ProtocolPort  + egress attachment
                     ▼
          plan executor backend
                     ▼
             bridge VirtualDut
```

具名的 `build_axi4_to_apb_bridge_vdut()` 可以作为易读、审计过的 preset。目标结构中它只选择：

- AXI4 ingress codec；
- `AddressBurst→AddressAccess` 与 address leaf stages；
- 明确适用范围、ordering、SemanticEffect、unsupported policy 和 equivalence level 的 `BridgeProfile`；
- serial scheduler、访问/物化方式和 storage profile；
- APB egress codec；
- completion/error origin、reset/cancel、两侧端口与 route policy。

它不再拥有一套 `Axi4ToApbBridgeBackend` 专属的 split/schedule/correlate 实现。

目标 `SystemProtocolBuilder` 的 construction lowering 在调用方授权后选择同样的 plan，并把结果展开为：

```text
source ─ source link ─ bridge VirtualDut ─ target link ─ target
```

展开后的节点和 links 才交给 core SystemProtocol elaboration 做普通结构闭合检查。Construction report 保存
intent→codec→stage→policy→module 的 provenance；运行期不会因为遇到协议不匹配而临时插入不可见
adapter。

## 8. Bridge、Crossbar 与 SystemProtocol 的边界

Bridge 的 `1→1` 指端口路径形状，不表示每笔事务只能产生一个 child。AXI4→APB bridge 可以是一个 ingress
port、一个 egress port，同时在内部执行 1→256 fanout。

Crossbar 在事务转译之外增加多入口共享：

- route/decode；
- admission 与 arbitration；
- AW→W route ownership；
- downstream ID namespace/remap；
- response owner table；
- 多 parent 并发和 ordering policy。

Crossbar 可以复用 codec 和 leaf stages，但不能默认建成若干彼此独立的 bridge executor。共享出口的选择和
owner 必须由同一 backend/fabric contract 统一拥有。

| 判断或状态 | 所属位置 |
|---|---|
| 单 link channel/schema/order | `LinkProtocol` / `LinkSession` |
| 单端口 fragment join、wire ID context | attachment state |
| 1→N 转译与 result fold | stage + bridge executor |
| 单 bridge queue、child owner | bridge VirtualDut backend |
| 多入口仲裁、共享 egress lease、返回 owner | crossbar/fabric VirtualDut backend |
| 多节点可达性、端到端 return closure | `SystemProtocol` |
| 跨节点 held/waited resource 与 deadlock | SystemProtocol analysis |

这些局部状态属于 interconnect VirtualDut。SystemProtocol 负责 bridge/crossbar 外部端口接到谁、地址和
capability 是否端到端闭合，以及多个节点资源是否形成 wait-for 环。只有验证目标需要观察互连内部 module/
link 时，才把它展开为内部 SystemProtocol。

Full AXI→AXI transparent relay/crossbar 也未必适合先降为 `AddressAccess`。如果验证目标要求保持原生 burst、
多 ID 并发或 channel timing，应使用能够接受 `AddressBurst` 的 egress codec，或采用 channel-preserving 的
协议相关 backend。协议无关 operation 是优先复用方向，不是有损转换的理由。

## 9. 当前采用的 V1 边界

V1 选择一条受限的线性 plan：

```text
ingress codec
    → zero or more 1→1 prefix stages
    → zero or one 1→N expansion
    → zero or more 0/1 or 1→1 suffix stages
    → one serial egress scheduler
    → egress codec
```

这个边界由当前真实 bridge pressure 决定：它覆盖 AXI4→APB、AXI4→AHB-SINGLE、AXI4-Lite→APB 和
AHB→APB，同时避免先建立任意 stage DAG、reorder engine 和多出口 planner。

| 组合 | 复用路径 |
|---|---|
| AXI4→APB | `AddressBurst→AddressAccess[N]→address leaf stages→APB` |
| AXI4→AHB-SINGLE | 替换 egress codec，复用 burst split 与 serial executor |
| AXI4-Lite→APB | `AddressAccess→address leaf stages→APB` |
| AHB→APB | accepted beat 直接进入相同 address leaf stages |

源码职责、实施阶段和暂缓能力见 [V1 实施计划](translation-v1-plan.md)。

## 10. 常见误解

### Transform 就是 operation type 吗？

不是。Operation form 描述 token 是什么；TranslationStage 描述 token 如何变成另一种类型，并怎样折返
completion。

### 一笔 burst 会兑换成多个 credit 吗？

事务会打开多个 child obligation，但 credit/lease 只表示并发资源许可。串行执行 256 个 child 时，egress
lease 峰值仍可为 1。

### 两种协议都有 address attachment，就一定能自动 bridge 吗？

不一定。宽度、burst、attributes、atomic/exclusive、ordering、错误表达和容量仍需 plan 显式闭合。无法
无损转换时，需要调用方选择 reject、remap、serialize 或 emulate policy。

### Attachment 是 bridge 吗？

Attachment 只翻译一个端口。Bridge 需要同时拥有两侧 attachment、跨端口 stage、调度、资源和 completion
correlation，因此是完整 VirtualDut。

### Bridge 放在 integration，是否就不属于 VirtualDut？

Integration 是协议依赖汇合和装配位置；装配产物仍是 VirtualDut。源码放置与运行时对象的语义身份不是
同一个分类问题。
