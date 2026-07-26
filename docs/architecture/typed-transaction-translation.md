# Bridge 与类型化事务转译

[返回架构索引](README.md) · [构造方法的跨领域启示](bridge-construction-insights.md) ·
[Integration 与 binding](technical-route/04-integration-and-binding.md) ·
[SystemProtocol 组网](network-construction.md) · [当前状态](implementation-status.md)

Bridge 是一个具体、具名、多端口的 `VirtualDut`。它在两侧 InterfaceProtocol 之间保存一笔通信的业务含义，
同时改变线上编码、事务粒度、属性表示或执行顺序。类型化事务转译是构造这种 VirtualDut 的方法，不是
位于 VirtualDut 与 SystemProtocol 之间的新语义层。

本文是 bridge/Transform 的 canonical 架构说明。当前代码接入状态和验收边界单独记录在
[事务转译 V1 实施状态与后续](translation-implementation.md)。

| 状态 | 本文中的含义 |
|---|---|
| AMBA serial bridge | `build_amba_serial_bridge_vdut()` 按 ingress operation form 选择 single-access 或 AXI4 burst 路径；AXI4、AXI4-Lite、AHB、APB 的 4×4 address-family 组合不需要协议对 backend |
| 已实现的公共内核 | `OperationSignature`、`TranslationProfile`、typed unary/fanout stage、双向 plan closure、fanout ledger、capacity lease、serial executor 与 attachment-aware operation backend |
| 已接入的 address 路径 | `AddressAccess`/`AddressBurst` route、shape、protection、burst fanout，以及 AXI4/APB/AHB/AXI4-Lite 两侧 codec |
| Later | blocked/deferred demand、pin-level backpressure、并行 child、width merge、crossbar executor 和自动多跳搜索 |

公共 executor 位于 `protocol_model.virtual_dut.translation`，接收已经 decode 的 operation，不直接接收
`CanonicalEvent`。Attachment-aware backend 保存两侧 codec 状态并把 event decode/encode 与 executor
候选状态作为一次原子 transition 提交；integration recipe 再把它们装配成具体 bridge VirtualDut。

## 1. Bridge 的语义位置

一条 bridge 路径包含两种不同方向的工作：request 向下游翻译，completion 向原请求方折返。

```text
source InterfaceProtocol
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
target InterfaceProtocol

completion 沿相反方向 decode、lift/fold、encode
```

各对象的职责如下：

| 对象 | 描述的事实 | 不负责 |
|---|---|---|
| `InterfaceProtocol` | 一个 interface connection 上允许出现的 event、角色和先后关系 | 跨端口事务转换 |
| attachment/codec | 单端口 event 与 operation 之间的编码 | 跨端口调度、共享 owner |
| operation form | 一笔协议无关工作的类型和数据 | 何时发行、占多少容量 |
| `TranslationStage` | 两种 operation form 间的 lower/lift 关系 | parent 队列和调度算法 |
| `TranslationProfile` | 本次转换承诺的适用范围、语义效果、ordering、等价层级和失败政策 | 保存运行中的 owner/queue |
| `TranslationPlan` | 已闭合的 stage、双向能力、语义效果和 provenance | 调度/容量选择与具体运行状态 |
| executable binding | plan、executor profile、两侧 codec/port binding 的一次构造选择 | 定义协议本身或隐藏 topology |
| plan executor/backend | 执行 plan，保存队列、lease、owner 和 continuation | 定义两侧 InterfaceProtocol |
| integration recipe | 选择端口、attachment、plan 和 backend 并装配 VirtualDut | 创造另一套运行语义 |
| `SystemProtocol` | 把 bridge 端口接入 topology，检查端到端闭合 | 反射 backend 私有状态 |

这个分法保留了一个重要事实：装配完成的产物是 VirtualDut，而协议相关依赖的汇合位置是 integration。
“产物属于哪一层”和“装配代码放在哪个包”因而可以有不同答案。

从协议角色看，Bridge 更接近一个两侧 gateway：它终结 ingress InterfaceSession，在 egress 侧以另一角色发起
新的 InterfaceSession。两侧 attachment 解码为相同 operation 时，可以使用 Identity semantic translation；operation 粒度、属性或
completion 关系变化时，才需要 semantic stage。若原协议作为 opaque payload 被成对封装/解封装，则更接近
tunnel endpoint 和 SystemProtocol recipe，不应与单个 Bridge 混称。

### 1.1 两个协议边界与一条请求方向

Bridge 图中的两个 InterfacePort 是对等的模块边界对象，但它们承担的事务角色并不对称。典型 address bridge
在 ingress 侧作为 subordinate/completer 接受请求，在 egress 侧作为 manager/requester 发起 child；completion
沿 owner table 保存的反向路径返回。因此，结构图应把两侧都画成“port + attachment + operation boundary”，
同时用实线 request 和虚线 completion 保留真实方向，不能为了版面对称补出一条不存在的反向请求路径。

如果 A、B 两侧都能主动开启事务，它在执行上是两条 translation pipeline：各自需要 ingress correlation、
parent/child ownership、capacity 和 completion return。二者可以位于同一个 VirtualDut 并共享仲裁或存储，但
应由显式 duplex recipe 组合；它不是把单向 `A→B` plan 的箭头改成双向即可得到的能力。

### 1.2 三张相互关联的图

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
| AXI4 subordinate | `AddressBurst` | — | attachment 保留 AW/W assembly 与 reply context，burst form 进入公共 executor |
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
`VirtualDutBackend` 的 fault/READY 映射属于 attachment-aware 外壳。
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
| `InterfaceProtocol.refine()` | 同一 interface language | 单调收窄合法行为 |
| protocol embedding/variant | 协议 schema/event | 补默认字段或构造协议变体 |
| observation lowering | pin/sample → interface event | pin/frame 解释成 `CanonicalEvent` |
| attachment codec | interface event ↔ operation | 单端口协议编码 |
| transaction translation | operation ↔ operation | 跨端口 split/rewrite/fold |
| representation codec | message ↔ packet/flit | 保持声明 projection 的 pack/unpack、split/merge 与 lineage |
| transport scheduling | packet/flit → hop/resource usage | 选择 route、VC/RP、buffer 和 arbitration lease |
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
| `CardinalityToken` | InterfaceProtocol monitor | 检查本接口声明的 beat/completion 数量 |
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
| AXI read interface completion | 256 个 R event | ingress attachment 把一个 read burst result 编码成逐 beat R |
| AXI write interface completion | 1 个 B event | ingress attachment 把聚合 write result 编码成 B |

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

CHI L-Credit 由 transport-hop contract/session 维护；P-Credit 与 Retry lifecycle 由 CHI protocol contract
维护。二者以后都可以投影到系统资源图，但不与本地 FIFO slot 共用一套运行规则，也不能因为作用域局部
就归入 InterfaceProtocol。

## 6. TranslationPlan 与执行 backend

`TranslationPlan` 是构造期校验并由 compiler witness 封住的无运行状态结果。它会冻结 closure/report 并在
执行前核对 stage metadata；stage 实现本身仍须遵守无跨事务可变状态合同。V1 的有序 stage 结构允许
fanout 前后的 1→1 转换，但至多包含一个 fanout：

```text
TranslationPlan
├── source / target OperationSignature
├── TranslationProfile / equivalence level
├── zero or more 1→1 prefix stages
├── zero or one 1→N expansion
├── zero or more 0/1 or 1→1 suffix stages
├── bidirectional capability closure / semantic effects
└── provenance and rejection diagnostics
```

调度、容量与端口绑定不是 semantic plan 的字段。当前 `SerialExecutorProfile` 单独选择 parent capacity 和
serial egress slot；integration recipe 使用两侧 `InterfaceAttachmentBinding` 和
`AddressOperationTranslationBridgeBackend` 完成 executable binding。完整、独立 DTO 形式的 construction
report 尚未落地，但 plan、profile、attachment 与 port 选择已经是显式构造输入。这样同一个语义 plan 可以
更换 scheduler，而不会让 plan 报告它尚未证明的运行资源性质。

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
source/target port offers + requested TranslationProfile
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

Plan 还声明保持的等价层级：operation/effect trace、interface transaction/order 或 pin/cycle。Buffer、register
slice 或 CDC lowering 通常属于运输实现；只有在相应 stallability、reset 和等价条件闭合后才能加入，不能由
semantic stage 隐式产生。

### 6.2 Executor 的运行状态

Plan 本身不保存运行状态。已实现的 operation executor 保存：

- pending parent queue；
- 每个 parent 的 translation frame、`FanoutLedger` 和 continuation；
- active child 与 egress owner；
- 已获取的 resource leases；
- result fold state。

已经实现的 attachment-aware backend 另外保存两侧接口关联状态和 emission 编码候选，并把 attachment 与
executor 的候选状态作为一个整体提交。二者没有在公共 executor 中混成万能协议 payload 接口。

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
| APB sole pending 等单端口接口关联状态 | egress attachment state | 该协议 completion 被 decode |
| child→parent lineage | executor `FanoutLedger` | child obligation 解除 |
| result tuple/fold accumulator | translation frame | parent result 形成 |
| interface outstanding | 各自 `InterfaceSession` | 对应 interface completion 被接受 |

同一个 runtime 资源只由一个 owner 更新；`ResourceDecl`、boundary capability 和可视化 usage 从该 owner
投影，不再维护另一份可修改计数。

一个严格串行 executor 的生命周期是：

```text
accept request fragments
  → ingress attachment owns partial transaction state

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
  → ingress attachment uses reply context to encode interface completion event(s)
  → successful encoding releases parent lease and envelope
```

Route miss 等 local completion 直接推进 ledger，不获取 egress lease。Normal completion 与模型故障保持
分离，便于 bridge 正确表达目标地址不存在、只读写入等设备结果。

AXI read 中，bridge 的一个 semantic parent result 与 AXI interface 上的多个 R event 是两个作用域。Parent envelope
在 codec 成功形成全部 emissions 后释放；`InterfaceSession` 的 AR→R cardinality obligation 随各个 R event 被接受
而逐项解除，不与 `FanoutLedger` 共用 remaining count。V1 parent scheduler 按“完整 parent operation 形成顺序”
严格 FIFO；它能保持同 ID 返回顺序，也会对不同 ID 施加比 AXI 基础规则更强的串行限制。

### 6.3 Contract、execution profile、witness 与 RTL conformance

可执行 reference model 会产生一条具体轨迹，bridge contract 描述的则是一组允许的边界行为。两者需要分开，
否则 executor 为方便实现而选择的严格 FIFO、单 child 调度和 service 时机，会被误当成协议义务，进而否决
具有合法 buffering、pipeline 或跨 ID 重排的 RTL。

| 对象 | 说明 | 支持的结论 |
|---|---|---|
| bridge contract / `TranslationProfile` | operation/result relation、effect、correlation、必须保持的偏序、允许弱化和可选时间约束 | 哪些边界行为属于所选 profile |
| `TranslationPlan` | 证明 codec/stage 能双向闭合 contract；不保存调度状态 | 这条语义转换路径可以构造 |
| execution profile | 选择 serial/window/reorder、capacity、storage 和 service policy | reference VirtualDut 怎样执行其中一种实现 |
| execution witness | plan、execution profile 与 scenario 形成的一条有限轨迹 | 至少有一条行为可执行，可用于示例和定向回归 |
| RTL conformance | 将两侧 RTL observation 投影后检查 relation、identity、偏序和可选时间约束 | 被观察行为是否落在 contract 允许集合内 |

关系可以写成：

```text
Bridge contract C ──compile──► TranslationPlan
       │                              │
       │                      + execution profile
       │                              ▼
       │                       witness w ∈ Behaviors(C)
       │
RTL pins ─► protocol observation ─► projected behavior r
       └──────────────────── conformance: r ∈ Behaviors(C)
```

普通 conformance 判断使用 `r ∈ Behaviors(C)`，不要求 `r == w`。只有 contract 明确选择精确调度或
`PIN_CYCLE` 约束时，reference schedule 的相应部分才可能成为逐周期判定依据。

#### Event projection 与 stutter

RTL 样本先由协议 observer 检查 handshake、stall stability、reset 和其他 pin-local 规则，再投影为 accepted
`CanonicalEvent`、typed operation 和 externally visible effect。对 operation/effect 或允许变延迟的
interface-transaction profile，两个相关 transfer/effect 之间的无关采样帧可以在语义比较时折叠：

```text
pin frames ──protocol checks──► accepted events ──codec──► operation/effect trace
```

stutter-insensitive 不表示所有空周期都能忽略。timeout、progress、latency window、不可回压边界、reset 和
采样期 sideband 会让周期本身成为可观察事实；这些 property 必须在折叠前检查。没有声明 latency upper bound
只表示当前 contract 不据此判错，不表示实现必须零延迟。

#### Partial order 与 allowed reorder

Serial executor 会把事件排成 total order。Contract 只应保留真正必要的 happens-before edge，例如 fragment
形成完整 request、parent→child、同一 burst 的 beat 顺序、同 ID completion 顺序和 request→response。
没有依赖的事件可以由 profile 声明为可重排。

RTL trace 若是该偏序的合法线性展开，并满足 correlation/cardinality，就不应仅因列表位置与 serial witness
不同而失败。匹配依靠 wire ID、reply context、owner/lineage 等稳定 identity，而不是 reference 数组下标。
实现选择更强的顺序通常仍可符合较弱 contract；吞吐、最大等待和公平性由另外声明的 property 判断。

#### Equivalence level 的当前边界

| level | 参与比较的投影 | 通常可忽略或允许 | 还需要的证据 |
|---|---|---|---|
| `OPERATION_EFFECT` | typed request/result 与 externally visible effect | 内部 child 调度、无关 stutter、未约束的 boundary ordering | interface event 顺序、transport 与 pin timing |
| `INTERFACE_TRANSACTION_ORDER` | accepted canonical event、correlation 与 contract partial order | 已声明的 stutter、buffering 和 allowed reorder | 未接受的 pin toggle 与 cycle-exact waveform |
| `PIN_CYCLE` | normalized pin/`AtomicFrame`、clock/reset 与 handshake | profile 明确列出的 don't-care、retiming 或 latency tolerance | 不能由 operation plan 自动推出 |

当前 V1 compiler 只接受 `OPERATION_EFFECT`、空 ordering claim 和 sequential access mode。
`INTERFACE_TRANSACTION_ORDER`、`PIN_CYCLE`、通用 partial-order conformance、stutter projection 与 latency window
仍未形成 executable checker。现有 `SerialTranslationExecutor` 因而是具体 execution profile 和 witness
生成器；它能够检查 owner/lifetime/error fold，但不定义外部 RTL 的唯一 golden cycle trace。

## 7. 从 Plan 装配 Bridge VirtualDut

Integration recipe 是 composition root：它可以同时依赖协议 attachment、通用 stage、executor 和
VirtualDut boundary。装配过程如下：

```text
ingress InterfacePort + ingress attachment
                     │
                     ├─ validated TranslationPlan
                     │
egress InterfacePort  + egress attachment
                     ▼
          plan executor backend
                     ▼
             bridge VirtualDut
```

`build_amba_serial_bridge_vdut()` 是统一 composition root：full AXI4 ingress 选择 burst assembly/fanout，
AXI4-Lite、AHB 和 APB ingress 选择 single-access plan；egress attachment 再按目标 family 选择。
`build_axi4_to_apb_bridge_vdut()` 等具名函数保留为易读、附加限制经过审计的 preset。以 AXI4→APB preset
为例，它只选择：

- AXI4 ingress codec；
- `AddressBurst→AddressAccess` 与 address leaf stages；
- 明确适用范围、ordering、SemanticEffect、unsupported policy 和 equivalence level 的 `TranslationProfile`；
- serial scheduler、访问/物化方式和 storage profile；
- APB egress codec；
- completion/error origin、reset/cancel、两侧端口与 route policy。

这些 preset 不拥有专属的 split/schedule/correlate backend。

目标 `SystemProtocolBuilder` 的 construction lowering 在调用方授权后选择同样的 plan，并把结果展开为：

```text
source ─ source connection ─ bridge VirtualDut ─ target connection ─ target
```

展开后的节点和 connections 才交给 core SystemProtocol elaboration 做普通结构闭合检查。目标 construction report
将保存 intent→codec→stage→policy→module 的 provenance；运行期不会因为遇到协议不匹配而临时插入
不可见 adapter。

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
| 单 interface channel/schema/order | `InterfaceProtocol` / `InterfaceSession` |
| 单端口 fragment join、wire ID context | attachment state |
| 1→N 转译与 result fold | stage + bridge executor |
| 单 bridge queue、child owner | bridge VirtualDut backend |
| 多入口仲裁、共享 egress lease、返回 owner | crossbar/fabric VirtualDut backend |
| 多节点可达性、端到端 return closure | `SystemProtocol` |
| 跨节点 held/waited resource 与 deadlock | SystemProtocol analysis |

这些局部状态属于 interconnect VirtualDut。SystemProtocol 负责 bridge/crossbar 外部端口接到谁、地址和
capability 是否端到端闭合，以及多个节点资源是否形成 wait-for 环。只有验证目标需要观察互连内部 module/
connections/hops 时，才把它展开为内部 SystemProtocol。

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

这个边界由当前真实 bridge pressure 决定。统一 builder 的 family-level 构造矩阵如下；每个格子表示能够
装配成一个两端口 serial bridge，不表示所有可选 sideband 或性能性质都能保持。

| ingress form / family | AXI4 egress | AXI4-Lite egress | AHB egress | APB egress |
|---|---|---|---|---|
| AXI4 `AddressBurst` | burst→ordered single AXI access | burst→ordered Lite access | burst→AHB SINGLE | burst→APB transfer |
| AXI4-Lite `AddressAccess` | single AXI access | single Lite access | AHB SINGLE | APB transfer |
| AHB accepted beat | single AXI access | single Lite access | AHB SINGLE | APB transfer |
| APB transfer | single AXI access | single Lite access | AHB SINGLE | APB transfer |

因此四个 address family 形成 4×4 共 16 种构造组合；AHB-Lite/AHB5 与 APB3/APB4/APB5 通过各自 family
attachment 复用这张矩阵。当前七个具体 variant 在默认 32-bit profile 下形成 7×7 装配见证；它验证
composition root 没有按协议对扩张，不等同于 49 个方向的完整执行或规范覆盖。具体 revision/profile 还必须
满足 attachment 和 stage 的能力边界：

这些 serial trace 证明当前 execution profile 能够装配和执行，不把该 profile 的调度选择定义成所有
conforming RTL 的唯一轨迹。

- executor 每次只保持一个 active child；下游 AXI 使用一个配置的 wire ID，不提供 ID remap/reorder；
- full AXI burst 当前拆成有序 single access，不保持下游原生 burst 形态；
- single-access 路径当前要求两侧数据宽度相等；generic full-AXI burst 路径允许不同总线宽度构造，但不执行
  beat split/merge，只有每个 beat 都能被目标直接表示时才会发行；
- AXI4-Lite/APB egress 只接受其隐式整总线宽度，AHB/AXI egress 接受对齐且不超过总线宽度的二次幂访问；
- AMBA protection 已有 decode/encode；cache、QoS、region、memory attributes、lock/exclusive、RME/User 等
  扩展尚无通用保持策略，当前 profile 对非默认值拒绝或使用目标默认值；
- AHB5 Exclusive interface profile 不使用普通 `AddressAccess` attachment，需要专用 exclusive/atomic 语义路径。

这张矩阵描述地址事务构造能力。具名 preset 可以进一步收窄范围，例如要求同宽、PPROT/PSTRB 或
AHB-Lite revision；它们不是新增一套运行核心。

源码职责、实施阶段和暂缓能力见 [V1 实施状态与后续](translation-implementation.md)。

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
