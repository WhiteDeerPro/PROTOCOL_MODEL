# Bridge 与类型化事务转译

[返回架构索引](README.md) · [构造方法的跨领域启示](bridge-construction-insights.md) ·
[Integration 与 binding](technical-route/04-integration-and-binding.md) ·
[SystemProtocol 组网](network-construction.md) ·
[实施状态与后续](translation-implementation.md)

Bridge 是一个具体、具名、多端口的 `VirtualDut`。它在两个协议边界之间保存 operation 的业务含义，并按明确
policy 改变线上编码、事务粒度、属性表示或执行顺序。类型化事务转译提供构造这种 VirtualDut 的共同方法。

本文维护 bridge/Transform 的 canonical 合同。源码接入范围、阶段限制、延期项和定向见证由
[事务转译实施状态](translation-implementation.md)与
[实现状态总表](implementation-status.md)维护。

主线分为四段：

```text
输入合同
  → 构造期闭合
  → 生命周期执行
  → bridge VirtualDut / SystemProtocol handoff
```

## 1. 主线对象与语义位置

一条 bridge path 在 request 方向执行 decode、lower 和 child issue，在 completion 方向执行 decode、
lift/fold 和 parent encode：

```text
source InterfaceProtocol
        │ canonical events
        ▼
ingress attachment / codec
        │ DecodedOperation + reply context
        ▼
TranslationPlan + executor
        │ typed child operation
        ▼
egress attachment / codec
        │ canonical events
        ▼
target InterfaceProtocol

completion: target → decode → reverse lift/fold → encode → source
```

| 对象 | 接收 | 产出与权威事实 | 相邻交接 |
|---|---|---|---|
| `InterfaceProtocol` / `InterfaceSession` | 一个完整接口上的 canonical events | event language、局部 correlation 与 verdict | attachment 消费已接纳 event |
| attachment / codec | 单端口 event 或 operation completion | event↔operation 编码、wire reply context 和接口侧状态 | 将 `DecodedOperation` 交给 executor |
| operation form / `OperationSignature` | 协议中立的工作含义 | typed request/result 与 semantic domain | stage 以 form 为类型边界 |
| `TranslationProfile` | source/target capability 与调用方 policy | applicability、effect、ordering、equivalence、failure/reset 合同 | plan compiler 执行闭合 |
| `TranslationStage` | 一个 typed parent operation 或 child result | lower、lift/fold、`SemanticEffect` 和 lineage rule | plan 按显式顺序组合 |
| `TranslationPlan` | profile、codecs 与 ordered stages | 双向 closure、effects、provenance 和 compiler witness | executor 读取 immutable plan |
| executor / bridge backend | plan、decoded parent、child completion 与资源 profile | queue、lease、owner、continuation、fold 和 emission candidate | attachment 编解码，VirtualDut 持有 backend |
| integration recipe | ports、attachments、plan、executor 与 capability policy | executable composition contract 和 constructed `VirtualDut` | System construction 注册 module |
| `SystemProtocol` | bridge boundary、connections 与系统合同 | topology、全局 authority、resolution、runtime 与 analysis | 执行已固定的 module graph |

装配产物属于 `VirtualDut`；协议依赖在 `integrations` 的 composition root 汇合。运行时身份与源码装配位置由这
两个事实分别描述。

### 1.1 端口路径与事务方向

典型 address bridge 在 ingress 侧作为 subordinate/completer 接受 parent，在 egress 侧作为
manager/requester 发出 child。两个 `InterfacePort` 是对等的 module boundaries，request 与 completion 则沿
相反方向流动。结构图以实线标 request、虚线标 completion，并保留真实的角色和 owner。

一个端口路径的 `1 ingress → 1 egress` 描述结构形状；单个 parent 仍可通过 `1→N` stage 产生多个 child。
例如 AXI burst→APB bridge 可以具有两个 ports，同时在内部展开 256 个 address accesses。

A、B 两侧都能主动开启 transaction 时，duplex recipe 组合两条 translation pipelines。每条 pipeline 分别
声明 ingress correlation、parent/child ownership、capacity 和 completion return；共享仲裁或存储由同一
VirtualDut backend 持有。

Opaque protocol payload 的成对封装/解封装采用 tunnel endpoint 与 system recipe；typed bridge path 则以
operation form 和 semantic effects 描述可观察语义。

### 1.2 三张图

Bridge construction 与 execution 同时产生三类关系：

| 图 | 时间 | 回答的问题 | 主要对象 |
|---|---|---|---|
| 构造期约束图 | elaboration | 两端能力、stage 顺序和转换 policy 怎样闭合 | port offer/requirement、codec、stage contract、plan |
| 运行期语义转译图 | 每笔 transaction | parent 怎样产生 child，completion 怎样 lift/fold | operation、envelope、lineage、semantic effect |
| 运行期等待图 | 每个执行状态 | token 持有什么、等待什么，资源何时释放 | executor、owner、queue、lease、demand |

Burst child count 属于语义转译图，active scheduling window 属于等待图，构造期约束图验证两者的 profile
相容性。三类图通过 token、lineage、resource projection 相互关联，并保持独立权威。

## 2. 输入合同

### 2.1 Operation form 与 reply context

Operation form 描述 module 实际处理的工作。`OperationSignature` 为它提供稳定的类型边界：

```text
OperationSignature
├── semantic domain / name / version
├── request runtime types
└── completion runtime types
```

有 request/completion 生命周期的 domain 同时声明两侧类型；单向 stream 使用对应的无 completion signature。
协议 wire identity、descriptor provenance 和返回编码上下文由 attachment 解码后存入 parent envelope：

```text
DecodedOperation                 ParentEnvelope
├── semantic operation ──────┐   ├── executor parent token
└── reply context（opaque）──┴──►├── semantic operation
                                 ├── reply context
                                 └── ingress binding
```

Stage 读取 semantic operation。Executor 保存 reply context，并在 parent result 形成后交回 ingress
attachment。AXI ARID/AWID、读写方向和 descriptor provenance 可以据此参与 R/B 编码；通用 address form 保持
协议字段中立。

Parent token 由 executor 为每次接纳分配。Wire ID 继续服务接口 correlation，同一 wire ID 可以对应多笔
outstanding parents；内部 token 为每笔 bridge lifecycle 提供唯一 owner key。

常见 form 包括：

| Form | 含义 | 典型边界 |
|---|---|---|
| `AddressBurst` | 带 beat geometry、attributes 和有序 result relation 的地址访问集合 | burst-aware ingress 或 egress |
| `AddressAccess` / `AccessResult` | 一次 byte-range read/write 及结果 | APB、AXI4-Lite、AHB accepted beat、single-beat AXI |
| `StreamTransfer` | 带 lane mask、packet boundary、ID/destination 的 stream beat | AXI4-Stream receiver/transmitter |

`AddressBurst` 保存 count、geometry、attributes 和必要的 beat-local payload；每个 beat 的 memory effect 继续按
协议与 backend policy 判定。Atomic、coherent message、cache maintenance 和 stream-to-memory 等语义使用各自
domain，显式 stage 或具名 VirtualDut 连接这些 domain。

### 2.2 `TranslationProfile`

`TranslationProfile` 是调用方选择的 semantic contract，至少声明：

- source 与 target `OperationSignature`；
- source offer、target requirement 和适用 capability；
- operation-level applicability 与 unsupported policy；
- preserve、recompute、split、aggregate、rebind、default、weaken、reject 等 `SemanticEffect`；
- request/completion correlation、cardinality 和 completion origin mapping；
- 必须保持的 happens-before、允许的 reorder 和 access mode；
- backpressure/admission policy、reset/cancel policy 与故障投影；
- conformance equivalence level；
- rule、policy 和规范裁决的 provenance。

Profile 描述允许的边界行为集合。Stage 与 codec 证明一条具体语义路径，execution profile 再选择 serial、
window、reorder、capacity、storage 和 service policy。

### 2.3 Executable composition contract

一个可执行 bridge 的 composition contract 由以下构造输入共同形成：

| 构造输入 | 合同内容 |
|---|---|
| ingress/egress port offers | protocol family、role、capability 和 event shape |
| attachment codecs | event↔operation relation、reply context 与接口侧 state owner |
| `TranslationProfile` + compiled plan | operation/result relation、effects、ordering 与双向 closure |
| executor profile | admission、capacity、scheduling、storage 和 service policy |
| boundary policy | reset/cancel、backpressure、error response 与 completion origin projection |
| recipe provenance | intent→codec→stage→policy→module 的选择依据 |

这些输入在 construction 阶段闭合并冻结。Runtime 只执行已选择的 plan、executor 和 bindings。

### 2.4 显式转译的复用单位

协议数量增长时，协议对 backend 容易重复 burst split、address remap、attribute projection、schedule 和 error
fold。类型化转译把变化拆成两个复用单位：

- 每种协议提供到少量 operation forms 的 codec；
- 每种真实语义差异提供可组合的 stage。

新增一个能够编码 `AddressAccess` 的协议时，可以复用 address stages 和 executor。Atomic、coherence、
message ordering 等新语义压力则引入新的 form、stage 或 protocol-bound backend。具名协议对 builder 作为
审计过的 preset，复用共同执行核心。

具有 request/completion lifecycle 的 form 成对描述两侧。以 burst fanout 为例，合同同时记录
child→parent lineage、result fold、read beat placement、error mapping、parent release 和
reset/cancel obligation。

## 3. 构造期闭合

### 3.1 Typed `TranslationStage`

Operation form 是类型化语义节点，`TranslationStage` 是节点之间的双向关系。共同元数据包括：

- source/target request 与 completion signatures；
- `1→1`、`0/1`、`1→N` 等 cardinality；
- request lower/split/rewrite；
- child completion lift 或 incremental fold；
- request offer 的 forward projection 与 completion requirement 的 backward projection；
- static precondition/postcondition 和 per-operation applicability；
- `StageContract`、`SemanticEffect`、completion rule 和 preservation obligations；
- parent→child lineage、本地完成条件和 provenance。

单值 stage 可以使用以下形状：

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

Fanout stage 使用 indexed child generation 与 incremental fold：

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

`FanoutStart` 保存 child count、stage context 和 initial fold state。`FanoutLedger` 持有 issued、completed 和
inflight lifecycle 账目；stage contract 持有 immutable conversion relation；executor 持有跨 transaction
mutable state。

Lowering 产生三类 semantic outcome：

| Outcome | 含义 | 例子 |
|---|---|---|
| child expansion | 产生一个或多个下游 child | burst→`AddressAccess[N]` |
| local completion | 在 bridge 内形成正常 parent result | route miss→`DECODE_ERROR` |
| rejection | 当前 conversion policy 拒绝这笔 operation | target shape/attribute 超出 profile |

Executor 的 resource admission 另行产生 `BLOCK`、deferred error completion 或 fault projection，使
conversion semantics 与临时容量状态保持分离。

### 3.2 Capability relation 与 `SemanticEffect`

类型相连提供 signature compatibility；`StageContract` 继续闭合 capability 与语义：

```text
source offer ──forward projection──► target offer
source requirement ◄──backward projection── target requirement

source operation ──applicability──► child / local result / rejection
source property  ──SemanticEffect─► target property + completion rule
```

| Effect | 合同含义 |
|---|---|
| preserve | 两侧表达同一性质 |
| recompute | 按 target shape 重新计算 |
| split / aggregate | request fanout 或 completion fold |
| rebind | identity/metadata 由 reply context、owner 或新 namespace 保存 |
| synthesize / default | 按显式 policy 产生 target 所需信息 |
| weaken / drop | 保证或信息变弱，并进入 construction report |
| reject | profile 为超出适用范围的 operation 选择 rejection |

`CapabilityRelation` 判断完整 path 的 offer/requirement closure，`SemanticEffect` 记录闭合过程的变化。
Signature 相同时，planner 仍保留中间的 loss、ordering、identity 和 completion policies。

常见 address stages 可组合为：

| Stage | Request 方向 | Completion 方向 |
|---|---|---|
| `BurstToAccess` | `AddressBurst → AddressAccess[N]` | N 个 `AccessResult` fold 为 burst result |
| `AddressWindow` | route check 与 address remap | result 保持；miss 可 local-complete |
| `AttributePolicy` | preserve/default/project/reject attributes | 恢复 parent-facing 表达 |
| `TransferShapeGuard` | width、alignment 与 byte-enable applicability | result 保持 |
| `Identity` | 1→1 operation relation | 1→1 result relation |
| `WidthSplit/Merge` | 按 byte/lane 拆分 | 重组 data、byte enable 与 error |

具体已实现 stages 与 profile 范围由
[事务转译实施状态](translation-implementation.md)维护。

### 3.3 `TranslationPlan`

`TranslationPlan` 是 compiler 生成并封住的 construction result。它冻结：

```text
TranslationPlan
├── source / target OperationSignature
├── TranslationProfile / equivalence level
├── explicit stage topology and ordering
├── bidirectional capability closure
├── accumulated SemanticEffects
├── completion/error mapping
├── provenance and rejection diagnostics
└── compiler witness
```

每条 request path 按 stage order lower，每条 completion path 逆序 lift/fold。常见 fanout path 的顺序为：

```text
request:    prefix.lower → expansion.child_at → suffix.lower → egress
completion: egress → suffix.lift → expansion.fold_one/finish → prefix.lift → ingress
```

Suffix child result 先 lift 回 expansion target，prefix contexts 保留到 parent 完成后逆序 lift。Compiler 同时
检查正向 request types 与反向 completion types。

Canonical plan 是有限、显式的 typed structure。具体 compiler profile 声明其支持的 topology；每个 branch、
fanout 和 merge 都提供 lineage、completion rule 和 owner。实施所支持的线性、fanout 或 graph 范围记录在
实施状态页。

### 3.4 Compiler closure 与 diagnostics

构造期按以下顺序闭合：

```text
source/target port offers + requested TranslationProfile
    → choose ingress/egress codecs
    → propagate request capabilities forward
    → propagate completion requirements backward
    → validate ordered stage pre/postconditions
    → accumulate SemanticEffects and unsupported policies
    → choose executor/storage/resource profile
    → freeze plan + executable composition report
```

Stage order 由 fragment、width、attribute、identity、ordering repair 的 pre/postconditions 决定。Validator
定位第一个未闭合的 intermediate invariant，并报告：

- source/target signature mismatch；
- missing offer 或 unsatisfied requirement；
- stage order/precondition failure；
- unsupported attribute、shape、cardinality 或 ordering；
- semantic weakening 所需的调用方授权；
- completion mapping、reset/cancel 或 backpressure policy 缺口；
- provenance chain。

Plan 声明 operation/effect、interface transaction/order 或 pin/cycle 等 equivalence level。Buffer、register
slice 与 CDC lowering 在自身 stallability、reset 和 timing equivalence contract 闭合后进入 composition。

## 4. 生命周期执行

### 4.1 Runtime state ownership

Plan 冻结构造事实，executor 与 attachments 持有运行状态：

| 状态或资源 | Runtime owner | 释放或转移边界 |
|---|---|---|
| partial request、AW/W join、wire reply context | ingress attachment | 完整 parent 形成、cancel 或 reset |
| parent envelope、queue 与 continuation | executor | parent result 成功交给 ingress encode |
| payload storage | attachment 或 translation frame 中的唯一 owner | child 消费、cancel/reset 或 parent 完成 |
| child scheduling window | executor capacity pool | child completion/cancel |
| 单端口 pending/completion context | egress attachment | protocol completion decode |
| child→parent lineage | executor `FanoutLedger` | child obligation 解除 |
| result tuple/fold accumulator | translation frame | semantic parent result 形成 |
| interface outstanding/cardinality | 各侧 `InterfaceSession` | 对应 interface completion 被接受 |

`ResourceDecl`、boundary capability、wait-for input 和 visualization usage 从唯一 runtime owner 投影。Protocol
monitor 继续持有自己的 verdict ledger，并通过 canonical events 与 execution state 对照。

Attachment-aware backend 将 decode、executor 和 encode candidates 组成一次原子 transition：

```text
ingress decode candidate
    → plan/executor candidate
    → egress issue or local result
    → ingress/egress encode candidates
    → admission succeeds
    → commit all candidate state and emissions
```

候选被阻塞或拒绝时，已提交状态保持在上一个稳定点；诊断携带 producer、resource、operation token 和 policy。

### 4.2 Parent lifecycle

一个 fanout parent 的通用生命周期为：

```text
accept request fragments
  → ingress attachment owns partial transaction

form complete parent
  → attachment emits DecodedOperation
  → executor assigns parent token and owns ParentEnvelope
  → acquire parent lease
  → create work obligation(total=N)

issue child[i]
  → acquire egress execution lease
  → save parent/child lineage

complete child[i]
  → lift/fold result
  → release egress lease
  → retire one child obligation

all child obligations retire
  → form semantic parent result
  → ingress attachment encodes interface completion event(s)
  → release parent envelope and lease
```

Local completion 直接形成 parent result，并保留 `LOCAL_POLICY` 等 origin。下游 decode miss、只读写入等正常
device results 沿 completion mapping 返回；模型合同破坏进入独立 fault path。

一个 semantic parent result 可以编码为多个 interface events。AXI read burst result 可形成逐 beat R events；
`FanoutLedger` 负责 child obligations，`InterfaceSession` 负责 AR→R cardinality，两份账本在各自作用域退休。

### 4.3 Token、obligation、lease 与 storage

Bridge runtime 分别记录四种量：

| 概念 | 回答的问题 | 典型状态 |
|---|---|---|
| transaction token | 这是谁的一笔工作 | executor-unique parent token |
| work obligation | 还欠多少 child/completion | total、issued、completed、inflight |
| capacity lease | 当前谁占用有限资源 | pool、amount、owner、acquire/release |
| stored state | 为继续执行保存什么 | descriptor、cursor、payload、fold accumulator |

`FanoutLedger` 表达工作量，`CapacityPool/Lease` 表达并发资源，`ResourceDecl` 提供声明与分析投影。Concrete pool
是 capacity authority，其他视图从它派生 usage。

状态按用途声明 owner、key、lifetime、release、reset/cancel effect 与 reconstruction policy：

| 状态类 | 例子 | 生命周期 |
|---|---|---|
| static configuration | route、attribute policy | module/plan replacement |
| transport assembly | AW/W join、partial request | decode complete、cancel/reset |
| shared binding | ID remap、return owner table | 最后相关 transaction 完成 |
| per-parent semantic | fanout ledger、fold accumulator | parent completion/cancel |
| capacity | queue slot、egress lease | completion/cancel |
| performance policy | optional buffer/cache | eviction/reset，保持业务 contract |
| diagnostic evidence | lineage、fault/completion provenance | evidence retention policy |

### 4.4 Fanout 的资源账目

以 256-beat parent 经 strict-serial target 为例：

| 量 | 数量 | 原因 |
|---|---:|---|
| parent transaction identity | 1 | 一笔 parent operation |
| parent slot peak | 1 | completion 前保存 context |
| child work obligations | 256 | 需要执行 256 笔 child operations |
| active child lease peak | 1 | serial scheduler 每次发行一个 child |
| child lease acquire/release | 256 次 | 同一个 execution slot 循环复用 |
| semantic parent result | 1 | child results fold 为一个 result |
| interface completion events | 由 ingress codec 决定 | 例如 read 的逐 beat result 或 write 的单 response |

并发资源上界为：

```text
peak child lease = min(child count, scheduling window, downstream capacity)
```

Lazy descriptor+cursor 可以让 request expansion 保持 O(1) descriptor storage。Aggregate read result 可以选择
O(N) ordered storage，streaming fold 可以把 storage 约束到 configured window；write status 在可增量 fold 的
profile 中可以保持 O(1)。这些 storage policies 保持相同的 cardinality 和 completion contract。

### 4.5 Admission、backpressure 与 completion origin

语义转换和运行资源分别产生结果：

| 结果 | Producer | 状态与边界语义 |
|---|---|---|
| child / local completion / rejection | stage + translation policy | 描述一笔 operation 的语义结果 |
| admitted | executor/backend | ownership 与 lease 原子转移，candidate state 提交 |
| `BLOCK` / `ResourceDemand` | capacity/admission policy | 保存原 owner，等待 resource 或 service opportunity |
| ordered error completion | boundary policy | 预留 ordering position，形成协议可表达的 completion |
| `FAULT` | model contract/runtime | 记录 invariant、owner 和 provenance 诊断 |

Backpressure-capable boundary 将 `BLOCK` 投影为协议 admission 信号；event-level runtime 通过 blocked transition 与
scenario retry 表达同一事实。Pin/cycle projection 由 observation/driver adapter 负责，并保持 payload stability、
reset 和 handshake 合同。

Completion 同时保存 wire-visible result 和内部 origin。常用 origin 包括：

- `DOWNSTREAM`：target device 或下游协议 completion；
- `LOCAL_POLICY`：route miss、shape policy 或本地正常结果；
- `LOCAL_RESOURCE_FAULT`：资源 policy 选择的错误完成；
- `RESET_OR_CANCEL`：lifecycle 被边界 control 终止。

多个 origin 可以映射为同一个 protocol response code；origin 继续用于 provenance、debug、system evidence 与
conformance。

### 4.6 Ordering 与 correlation

`TranslationProfile` 声明业务必需的 partial order，例如：

- fragments→complete parent；
- parent→child；
- 一个 burst 内的 beat order；
- same-ID completion order；
- request→response；
- side effect→successful completion。

Execution profile 可以选择更强的 total order。Strict-serial executor 是 contract 的一个合法 linearization；
window/reorder executor 通过 stable wire identity、reply context 和 parent/child lineage 恢复 correlation。
匹配以这些 identity 为准。

吞吐、最大等待、公平性和 QoS 由 system/scenario properties 声明。Execution 选择的额外串行化进入 witness 和
performance analysis，semantic contract 保持必要 ordering edges。

### 4.7 Resource projection 与 wait-for

Wait-for analysis 消费“token 持有的 leases”和“尚待满足的 demands”：

```text
token
├── holds: parent slot, child slot, owner entry
└── waits: downstream completion, output capacity, ordering release
```

Fanout count 表达总工作量，动态 wait-for edge 来自 held lease 与 pending demand。Window、shared pool、
crossbar 和多 bridge chain 可以把 owner/resource projection 交给 `SystemProtocol` analysis，形成跨 module
wait-for graph。

协议专用 credit 保留自身 scope：CHI L-Credit 由 transport-hop session 管理，P-Credit/Retry 由 CHI protocol
transaction contract 管理，本地 bridge FIFO slot 由 VirtualDut backend 管理。共同 resource vocabulary 支持
统一投影，各 owner 继续执行自己的 acquire/release rules。

## 5. Bridge VirtualDut 与 System handoff

### 5.1 Integration composition root

Integration recipe 可以同时依赖具体协议 attachment、通用或 protocol-bound stages、executor 和 VirtualDut
boundary：

```text
ingress InterfacePort + attachment
                     │
                     ├─ validated TranslationPlan
                     │
egress InterfacePort  + attachment
                     ▼
       executor / translation backend
                     ▼
             bridge VirtualDut
```

Recipe 完成：

- ingress/egress protocol 与 role 选择；
- attachment bindings 和 reply-context ownership；
- `TranslationProfile`、ordered stages 与 compiler invocation；
- executor/storage/resource profile；
- completion/error origin、reset/cancel 和 backpressure policy；
- ports、capabilities、route 与 boundary projection；
- construction provenance。

具名 builders 可以收窄 profile 并提供易读入口；共同 stages、executor 和 owner lifecycle 保持单一实现来源。

### 5.2 Bridge、crossbar 与 interconnect owner

Bridge 的内部 fanout 与 crossbar 的多入口共享是两种关系：

| 判断或状态 | Owner |
|---|---|
| 单 interface schema、channel order 与 event legality | `InterfaceProtocol` / `InterfaceSession` |
| 单端口 fragment join 与 wire reply context | attachment |
| parent→child translation 与 result fold | stage + bridge executor |
| 单 bridge queue、lease 与 child owner | bridge VirtualDut backend |
| 多入口 admission/arbitration、shared egress lease 与 return owner | crossbar/fabric VirtualDut backend |
| module reachability、global address/capability 与 end-to-end return | `SystemProtocol` |
| 跨 module held/waited resources 与 deadlock property | SystemProtocol analysis |

Crossbar 可以复用 codecs、route stages、storage、correlation 和 completion mapping。多个 ingresses 共享 egress
时，一个 fabric backend 统一持有 arbitration grant lifetime、ID namespace/remap、response owner 和 ordering。

保持 native burst、多 ID concurrency 或 channel timing 的 interconnect 可以选择 `AddressBurst` egress codec 或
channel-preserving protocol-bound backend。Operation lowering 的目标由验证范围与 profile 决定。

### 5.3 System construction

Construction lowering 将 bridge materialize 为显式 module、ports 和 connections：

```text
source
  ─ source InterfaceConnection
  ─ bridge VirtualDut
  ─ target InterfaceConnection
  ─ target
```

随后 core SystemProtocol elaboration 执行：

- module/port/connection ownership；
- capability compatibility；
- global address、identity 和 route authority；
- generated boundary projection 与 system contract 核对；
- end-to-end return closure；
- resolved runtime 与 monitor plan。

Bridge backend 的 queue、lease、owner 和 fold state 保持 module-private；SystemProtocol 读取 typed boundary/
resource projections。具名 interconnect 默认作为一个多端口 VirtualDut；验证目标需要观察内部 module、
connection 或 hop 时，construction 可以展开一个内部 SystemProtocol。

Generated fabric 从 system contract 派生或核对 route。External/opaque RTL bridge 通过 boundary contract 声明
其本地 decode、capability 和 return properties，由 system construction 闭合。

## 6. Conformance profile 与证据

### 6.1 Equivalence level

Profile 选择观察层级：

| Level | 参与比较的投影 | Profile 可声明的自由度 | 所需证据 |
|---|---|---|---|
| `OPERATION_EFFECT` | typed request/result 与 externally visible effect | profile 声明的 child scheduling、stutter、boundary reorder | operation correlation 与 effect oracle |
| `INTERFACE_TRANSACTION_ORDER` | accepted canonical events、correlation 与 partial order | profile 声明的 buffering、allowed reorder、variable latency | protocol observation 与 event identity |
| `PIN_CYCLE` | normalized pin/`AtomicFrame`、clock/reset 与 handshake | declared don’t-care、retiming、latency tolerance | pin adapter、clock/reset 和 stability checks |

细粒度 evidence 可以投影到较粗粒度的 comparison level；反向提升需要补充相应 observation。每项 timing、
stallability 和 reset claim 由选择它的 profile 与 evidence 闭合。

### 6.2 Event projection、stutter 与 partial order

RTL 样本先经过协议 observer，再进入 bridge comparison：

```text
pin frames
  → handshake / stability / reset checks
  → accepted CanonicalEvents
  → attachment codec
  → operation/effect trace
```

Operation/effect 或 variable-latency profile 可以折叠两个相关 transfers 之间的无关 sampling frames。
Timeout、progress、latency window、non-backpressurable boundary、reset 和 sample-time sideband 在折叠前作为
cycle-visible properties 检查。

Contract 保存真正必要的 happens-before edges，并把其他 pairs 标为 concurrent 或 allowed reorder。RTL trace
只要是该 partial order 的合法 linearization，并满足 identity、cardinality 和 effect relation，就属于允许行为。
Reference executor 的更强 ordering 形成其中一个 witness。

### 6.3 Contract、execution profile、witness 与 RTL conformance

Bridge contract 描述允许行为集合；execution profile 选择其中一种 reference implementation：

| 对象 | 内容 | 支持的结论 |
|---|---|---|
| bridge contract / `TranslationProfile` | operation/result relation、effect、correlation、partial order、semantic weakening 与 optional timing | 哪些边界行为属于所选 profile |
| `TranslationPlan` | codec/stage 的双向 closure 与 compiler witness | semantic path 可以构造 |
| execution profile | scheduler、capacity、storage、service 和 backpressure policy | reference VirtualDut 怎样执行一种合法实现 |
| execution witness | plan、execution profile 与 scenario 形成的有限 trace | 至少一条行为可执行 |
| RTL conformance profile | observation projection、identity、partial order、stutter、effect 与 timing policy | 被观察行为是否属于 contract |

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

Conformance 使用 membership `r ∈ Behaviors(C)`。当 contract 明确选择 exact schedule 或 `PIN_CYCLE`
constraints 时，对应 reference timing 才进入 exact comparison。Execution witness 支持 existential claim；
完整 profile coverage 继续需要 requirement catalog、positive/negative evidence 和 conformance checks。

## 7. Canonical 与实施资料分工

| 资料 | 维护内容 |
|---|---|
| 本文 | operation form、stage、plan、executor、resource、composition 和 conformance 的稳定合同 |
| [事务转译实施状态](translation-implementation.md) | 当前源码对象、已接入 profiles、V1 限制、阶段验收与延期项 |
| [实现状态总表](implementation-status.md) | 跨包完成度、当前边界与证据 claim |
| [实施路线](technical-route/08-roadmap.md) | 当前工作顺序与下一 slice |
| [Bridge 构造启示](bridge-construction-insights.md) | compiler、network、workflow 等领域方法的适用启示 |

源码入口：

- 通用 forms、stages、plan、resources 与 executor：
  [`protocol_model/virtual_dut/translation`](../../protocol_model/virtual_dut/translation/)
- protocol-bound typed stages：
  [`protocol_model/integrations/translations`](../../protocol_model/integrations/translations/README.md)
- protocol attachments：
  [`protocol_model/integrations/attachments`](../../protocol_model/integrations/attachments/)
- bridge composition roots：
  [`protocol_model/integrations/recipes/amba/bridges`](../../protocol_model/integrations/recipes/amba/bridges/README.md)
