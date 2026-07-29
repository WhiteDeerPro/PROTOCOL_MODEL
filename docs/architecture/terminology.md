# 术语体系与词典

[返回架构文档索引](README.md) · [技术路线](technical-route/README.md)

本页是当前工程术语的 canonical 注册表。这里的 canonical 表示“当前优先引用的定义入口”。规范依据、
实现边界或使用经验发生变化时，先审议本页定义，再同步代码映射、导读和教材。教程可以换一种讲法，
状态页记录实现进度，协议专题沿用标准原名；这些页面共同链接到本页的工程定义。

工程对象通过三条坐标定位：

| 坐标 | 回答的问题 | 典型关系 |
|---|---|---|
| 构造与所有权 | 代码由什么组成，状态由谁保存 | schema → protocol；port + attachment → binding；topology + contracts → system |
| 最小判定作用域 | 至少观察多大范围才能判断一条规则 | event、interface、transport hop、VirtualDut、system |
| 表示与观察 | 同一通信含义以什么形式传递或被采样 | operation；message → packet → flit；sample/frame → canonical event |

`transport hop` 与 `interface` 是两个并列观察面：前者关注相邻发送端和接收端之间的 flow control，
后者关注一份完整逻辑接口的消息与事务关系。构造箭头描述可用的组合关系，具体协议选择符合自身语义的
对象和路径。

## 亲缘关系总览

```text
观察：sample / AtomicFrame → observation adapter → event candidate
                                         → committed event → trace → run → artifact

接口：EventSchema + InterfaceEventKind + SemanticFragment
                                         → InterfaceProtocol
InterfaceProtocol → InterfacePort ─┐
InterfaceAttachment ────────────────┴→ InterfaceAttachmentBinding
InterfacePort references ────────────→ InterfaceConnection → InterfaceSession

模块：operation + attachment bindings + VirtualDutBackend → VirtualDut recipe
                                                       → concrete VirtualDut

表示：transaction lifecycle ──关联── message → packet → protocol flit
运输：TransportPort → DirectedTransportConnection → family hop/session

系统：topology + contracts → SystemProtocol → elaboration / resolved plans
                                      → runtime → monitor / read-only analysis
```

`AtomicFrame` 位于观察路径；message→packet→flit 位于表示路径；transaction 则表示关联请求、消息、
完成和状态变化的协议生命周期。三者沿不同坐标组合。

## 命名后缀

| 后缀 | 约定含义 |
|---|---|
| `Protocol` | 可复用的通信合法性合同，并注明其判定作用域 |
| `EventKind` | 把一个 EventSchema 绑定到接口内的方向；物理 channel 身份由具体协议编码声明 |
| `Port` | 一个具体 module 的静态边界端点 |
| `Connection` | topology 中对具体端点的连接声明 |
| `Attachment` | 单端口 canonical event ↔ operation 转换及接口侧状态规则 |
| `Binding` | 静态关联；执行状态归 session、attachment state 或 backend snapshot |
| `Backend` | VirtualDut 的本地可执行行为合同或其实现 |
| `Contract` | 必须满足的静态关系、假设与保证 |
| `Profile` | 某一对象上具名的一组配置或约束选择，使用 `Interface/Transport/Translation/Execution/...` 限定词 |
| `Policy` | 多种允许行为之间的显式选择 |
| `Plan` | 经闭合检查后供执行使用的不可变 lowering 结果 |
| `Session` / `State` | 可执行规则实例 / 该实例在某一时刻的状态快照 |
| `Trace` / `Run` / `Artifact` | 事件历史 / 一次执行结果 / 持久化证据 |
| `View` / `Projection` | 从权威对象只读派生的表示；执行决策继续引用权威对象 |

表格中的 CamelCase 和反引号表示当前代码符号；小写名称表示概念词汇。公共 Python API 以代码导出为准。
具体标准使用 `channel`、`Link`、`agent` 等词时保留相应规范原名，工程通用层通过显式映射说明对应关系。

## 同一层内部如何组织构件

层级回答“谁有权判断或保存这项事实”；同一层内部再用一条较轻的分类轴区分声明、算法、状态和装配入口。
各包根据实际密度选择这些角色，子目录结构按职责形成：

| 构件角色 | 回答的问题 | 典型例子 |
|---|---|---|
| declaration / config | 允许什么、容量或边界是多少 | schema、profile、route、resource declaration |
| pure policy | 多个合法候选中怎样选择 | `round_robin_grant()`、admission policy |
| runtime state / storage | 为后续转移实际保存什么 | ingress FIFO、partial burst、pending owner |
| lifecycle / controller | 何时 acquire、join、forward、retire | AW/W join、B owner return、translation executor |
| projection / recipe | 怎样只读展示或最终装配 | boundary projection、VirtualDut builder recipe |

源码先以一条行为的 vertical slice 共置：一个小型 monitor、observer 或 backend 的 token、state 和转移逻辑
可以留在同一文件。文件密度增加，或同一构件出现第二个真实消费者后，再按上表拆包。权威运行状态跟随
拥有其 acquire/release 生命周期的 controller；controller 所在职责包是状态的维护入口。

公共构件的提取条件包括：共享同一语义和不变量；已有两个独立消费者；依赖从协议族指向通用构件；
acquire/release/reset 条件可以独立说明；提取后保留一份权威状态。`virtual_dut/arbitration.py` 中的
round-robin 已满足这些条件。InterfaceProtocol 的 `CompletionLedger`、crossbar 的 completion-owner
ledger、bridge 的 child-owner ledger 与 system resolved map 具有不同的 key、释放条件和判定作用域，
继续由各自 owner 管理。

Valid-ready 状态归 observation，负责解释一次 pin handshake；backend FIFO 状态归 VirtualDut，负责保存
已经接纳的数据。后续 driver/admission lowering 连接两段生命周期，并保留各自的状态类型。

## 注册表如何演进

本页在一个版本内提供单一的工程定义入口，定义随工程演进。出现以下情况时，应重新审议相关词族：标准
原文与工程解释冲突；对象的所有权或最小判定范围已经改变；同一误解在代码评审、文档或示例中反复出现；
现有名称迫使实现维护两套重叠事实。

一次术语迁移至少记录旧称、新称、适用范围和改变理由，并依次同步本页、公共代码符号、canonical 架构文档
与生成源。历史 release 可以保留当时用语并标明版本语境；教材和展示材料链接或转述当前定义。兼容别名
根据发布阶段、迁移成本和用户合同单独评估。

## 通信事实

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| event candidate | 等待合同判定的一次离散动作 | observation、generator 或调用方构造的 `CanonicalEvent`；session acceptance 仍处于待定状态 |
| committed event | 已被 session 接受并编号的通信事实 | 带 `trace_index` 的 `CanonicalEvent`；monitor 状态和因果边已与它一起提交 |
| canonical event | 与具体 pin 名称解耦的统一事件值 | `CanonicalEvent`：带 kind、key、typed payload 和可选 trace index；执行上下文标记 candidate 或 committed 状态 |
| trace | 已接受事件的有限历史 | event 序列及 causal edges；run result 继续记录终态、fault、blocked 和 verdict |
| run | 一次有限执行的结果 | trace 加终态、emission、violation、blocked/quiescent 与 verdict 等运行信息 |
| channel | 某一标准明确定义的有向通信通道 | 例如 AXI AW 或 CHI REQ；APB `READ` 在通用模型中保持 event kind，wire channel 身份以 APB 规范为准 |
| InterfaceEventKind | 接口内一种有方向的规范化事件声明 | 将一个 `EventSchema` 绑定到 source/destination role；map key 是接口局部名称 |
| role | 端点在一份协议中的相对身份 | requester/completer、manager/subordinate、transmitter/receiver；VirtualDut 的 module 边界定义设备身份 |
| beat | 多拍传输中的一个数据单位 | 一次可计数的传输或 completion 单元；具体字段和接受条件由协议定义 |
| burst | 一笔由多个 beat 组成的事务 | 共享 descriptor/identity，并带 beat 数量、地址几何和完成关系的 transaction |
| transaction | 把相关请求、消息、完成和状态变化关联起来的一段协议生命周期 | 可以打开一个或多个 obligation，并占用 outstanding/correlation 资源；message/packet/flit 形式由协议表示链选择 |
| completion | 对先前请求的协议可见结果 | response、acknowledgement 或 result beat；必须能关联并解除相应 obligation |
| token | 在生命周期中代表一笔工作或身份的记录 | 可携带 parent/child identity、来源、属性和 continuation；capacity credit 使用独立的许可生命周期 |

### 通信事实的区分依据

| 相邻概念 | 区分依据 | 状态 owner |
|---|---|---|
| event candidate / committed event | session acceptance 与 `trace_index` 分配 | candidate 归产生方；committed state 归 session |
| trace / run | event history 与完整执行结果 | trace store / run result |
| transaction / message | 协议生命周期与一次 typed exchange | transaction monitor / protocol representation |
| token / credit | 工作身份与接纳许可 | lifecycle controller / resource 或 credit contract |

### 标准角色对照

| 协议语境 | 边界角色 | 说明 |
|---|---|---|
| AXI / AHB | manager / subordinate | 用于 `InterfacePort.role` 和有向 event kind；VirtualDut 设备身份由 module 边界定义 |
| APB | requester / completer | 保留 APB 标准角色名，并在通用接口中映射相对方向 |
| AXI4-Stream | transmitter / receiver | 描述单向 stream interface 的两端 |
| CHI protocol nodes | RN / HN / SN / MN 及其 profile | transaction participant；transparent router/XP 是 network forwarding module |
| CHI Link | transmitter / receiver | 一条单向 flit link 的两端；一个 node interface 通常组合多条 link |
| TileLink | agent；master/slave interface | 保留规范术语，通过显式映射接入通用 role |

## 字段、规则与接口局部合同

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| value domain | 一个字段允许取哪些值 | 位向量、枚举、自然数等可验证且可采样的字段集合 |
| event schema | 一类消息的格式 | 事件名、key domain、payload 字段和事件局部约束 |
| constraint | 什么情况算违规 | 带作用域、目标和来源的规则声明；可由 monitor 或构造检查执行 |
| monitor | 会根据历史持续检查规则的组件 | `SemanticComponent` 的常见用途，保存 correlation、cardinality、ordering 等状态 |
| resource declaration | 模型中什么会被有限占用 | outstanding slot、pending descriptor、FIFO capacity 等生命周期的声明投影 |
| obligation | 发生请求后还欠什么 | 由事件或 transition 打开、由后续 completion/cancel 解除的进度承诺 |
| semantic fragment | 一组可组合、可追踪的规则 | constraints、resources、obligations 和 dependencies 的具名组合单元 |
| pattern | 多种协议都会重复的行为骨架 | cardinality、correlation、FIFO join、in-order completion、quiet 等可复用组件 |
| InterfaceProtocol | 一条完整逻辑接口上允许使用的语言 | roles、`InterfaceEventKind`、monitors、parameters、`interface_family` 和 semantic fragments 的不可变声明 |
| profile | 一个对象的具名配置或约束选择 | 例如 bounded interface profile 或 CHI transport profile；profile 既可描述基础配置，也可记录一次收紧的结果 |
| refine | 单调收窄已有合同的构造操作 | 增加约束、降低容量或禁用事件，并保持 `L(refined) ⊆ L(base)` |
| InterfaceSession | 一条具体 interface connection 的运行账本 | 独立保存该连接的 monitor 状态、resource usage、trace 与 verdict |

### 合同概念的区分依据

`InterfaceProtocol` 的最小判定作用域是一条完整逻辑接口；CHI Link layer 的最小判定作用域是一条
transport hop。`profile` 是具名配置或约束集合，`refine` 是产生收窄合同的构造操作。一个 profile 可以
引用 refine 结果，也可以描述基础配置。

## VirtualDut 与协议接缝

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| operation | 模块真正处理的协议无关工作 | `AddressAccess`、`AddressBurst`、`StreamTransfer` 等 typed semantic form |
| AddressTarget | 执行完整地址操作的协议无关状态核 | 定义 `initial_state()` 与 `access(state, AddressAccess) → AddressStep`；`AddressSpace`/Memory region 可由 AMBA attachment 或 CHI participant adapter 复用 |
| emission | 模块执行后向端口产生的输出 | `PortEmission` 或语义组件 emission；一次 transition 可以产生 0..N 个，cycle 映射由执行 profile 声明 |
| effect | 操作对模块内部或相邻行为造成的影响 | `DutEffect` 等协议无关效果记录；attachment/runtime 决定其 interface event 映射 |
| backend | 模块行为的执行边界 | `VirtualDutBackend` 定义本地接纳、推进和 emission 合同；具体实现可以包装 constructed state，也可接到 RTL、RPC、trace 或 Python oracle |
| backend state | 为继续执行而保存的模块状态 | 功能状态、attachment 接口侧状态和跨端口 owner 等，由 backend snapshot 统一容纳 |
| boundary contract | 模块对外公开的假设和保证 | 端口、capability、资源和可观察行为投影；backend 继续持有私有状态 |
| DutBehaviorTag | 便于发现和显示的行为标签 | addressable、initiating、transforming、routing、signaling；权威行为声明来自 capability、resource 和 backend contract |
| InterfacePort | 具体 module 边界上的协议接口 | 指定 InterfaceProtocol、role、capability、clock/reset domain 的静态端口声明 |
| InterfaceAttachment | 单端口的接口翻译器 | 在 CanonicalEvent 与某类 operation 之间转换，并声明 attachment-local partial transaction state |
| observation adapter | 把采样解释为事件的边界 | sample/AtomicFrame → CanonicalEvent；处理 pin、reset、ready/valid 或异步握手观察 |
| representation codec | typed 表示之间的编码器 | message/packet/flit 之间的 pack、split、merge、unpack 和重组 |
| binding | 把 attachment 装到端口 | `InterfaceAttachmentBinding`：静态关联 `InterfacePort` 与 attachment；运行状态归 attachment state 或 backend snapshot |
| interface shape | 两个协议端口的接口外形 | event kind、字段、方向、role 和关键参数的兼容投影；完整行为语义由合同与 session 判定 |
| integration | 协议与模块操作的依赖汇合区 | 同时依赖 InterfaceProtocol 与 VirtualDut SPI 的 attachment、protocol-bound translation/backend 和 recipe |
| recipe | 把已有构件装成具体对象的入口 | 选择 port、binding、backend、plan 和 profile；运行语义继续由所选构件持有 |
| VirtualDut | 系统图中的一个具体虚拟 module | 具名 ports、bindings、backend 和边界语义；module 身份与所绑定的 AXI/APB 等协议族正交 |

### 接缝对象的 owner

| 对象 | 输入与输出 | 状态 owner / 区分依据 |
|---|---|---|
| observation adapter | sample/frame → canonical event | 采样状态；协议 pin encoding |
| InterfaceAttachment | canonical event ↔ operation | 单端口 partial transaction state |
| representation codec | message ↔ packet ↔ flit | 表示 lineage 与重组状态 |
| AddressTarget | AddressAccess → AddressStep | 地址功能状态；接口队列、flit 和 event 状态归相邻接缝 |
| interface shape | port compatibility projection | 静态配置投影；CHI TransportLink 使用独立 transport contract |

## 事务转译与互连

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| operation form/signature | 一类工作及其结果的类型 | request form、可选 completion form 和稳定 semantic domain 名称 |
| decoded operation / parent envelope | 把业务操作与返回身份一起交给 executor | attachment 产出 operation + opaque reply context；executor 再分配 parent token，直到结果编码完成 |
| lowering | 从较外部或较丰富的表示得到内部表示 | 可指 pin/frame→event，也可指 parent operation→child operation；必须注明作用域 |
| TranslationProfile | 一次转译所选择的适用范围与政策 | 声明 source/target signature、capability、ordering、允许弱化、equivalence、unsupported/reset policy |
| TranslationStage | 两种 operation form 之间的带类型箭头 | 同时声明 lower、completion lift/fold、cardinality、capability 和属性处理 |
| TranslationPlan | 一条经过闭合检查的事务转译方案 | stage、scheduler、resource/storage policy 和 provenance 的不可变构造结果 |
| translation frame | 一笔 parent 转译的语义上下文 | 保存 stage context、expansion cursor 和 result fold；fanout 计数归 ledger |
| fanout ledger | parent 拆成 child 后的生命周期账本 | 保存 total、issued、completed、inflight 与 lineage；result fold 负责结果聚合 |
| lineage | parent 与 child 的来源关系 | 记录某个 child operation/result 属于哪一个 parent token 及位置 |
| local completion | 由当前模块直接形成的正常结果 | route miss→decode error 等在本模块解除 obligation 的 completion |
| result fold | 把一个或多个 child result 还原为 parent result | 保持 beat 顺序、重组数据或聚合最坏错误状态 |
| conversion policy | 允许怎样改变业务语义 | preserve、default、remap、split、reject、emulate 等静态选择 |
| scheduling policy | 已确定的 child 何时发行 | serial、window-K、仲裁顺序等执行选择 |
| storage profile | executor 可保存多少运行上下文 | parent queue、payload beat、result accumulator、owner table 等容量 |
| route | 请求应该去哪个出口 | 地址/目的标识到 egress 和可选 remap 的局部选择关系 |
| completion owner | completion 应该归还给谁 | egress/ID/child 与原 ingress/parent 之间保存的动态关系；区别于静态 port owner 和资源 lease owner |
| correlation | 把分离事件重新认作同一生命周期 | AW/W join、request/response、parent/child result 等 FIFO 或 keyed 关系 |
| bridge | 在两个端口语义之间转换的 VirtualDut | 常见端口形状为 1→1；内部一笔 parent 可以产生多个 child |
| crossbar | 多入口、多出口的互连 VirtualDut | 组合 route、arbitration、owner/ID mapping、capacity 和 ordering |

### 关系词与所有权限定

| 术语 | 连接的对象 | 区分依据 | 状态 owner |
|---|---|---|---|
| correlation | 同一 transaction lifecycle 内分离的请求、数据和 completion | FIFO/keyed matching；happens-before 需要 causal edge | transaction/interface monitor |
| lineage | parent/child 或输入/派生对象之间的构造来源 | construction identity；运行接纳需要 committed record | translation/representation context |
| causality | 已提交事件之间的 happens-before 或语义依赖 | causal edge；文件位置由 trace index 单独记录 | causal graph |
| provenance | 声明、判断、生成物和证据的来源 | source chain；协议 correlation key 由对应合同声明 | declaration、run 或 artifact metadata |

`owner` 使用具名限定：静态连接占用称 `port owner`，返回身份称 `completion owner`，本地容量占用称
`resource lease owner`，地址或一致性裁决称 `address/home authority`。分析可以关联这些关系，各类 owner
仍由自己的生命周期与权威表维护。

## 表示、运输与协议参与者

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| message | 协议参与者之间一次有类型的交换 | 一笔 transaction 可以关联多个 messages；具体 cardinality 由协议 profile 决定 |
| packet | 带网络身份、可独立路由的表示 | 例如带 SrcID/TgtID 的 CHI packet；协议 profile 根据路由语义选择显式 packet 表示 |
| flit | hop flow control 接纳和释放的传输单位 | 例如 CHI protocol flit 或 link-maintenance flit |
| representation codec | typed 表示之间的保持关系 | message/packet/flit 的 pack、split、merge、unpack、lineage 与重组完成条件；当前公共 API 位于协议族具体类型 |
| transport link | 一次单向 TX→RX hop 的协议族合同 | 例如 `ChiTransportLink` 持有 flit flow-control、L-Credit 与 activation；完整逻辑接口由 `InterfaceConnection` 表示 |
| protocol participant | 协议中的逻辑参与者 | role/profile、身份 namespace、接口集合和 progress coupling；当前公共实现是 CHI participant binding，通用层保留概念词汇 |
| DirectedTransportConnection | topology 中的一条有向运输边 | 将 transmitter `TransportPort` 指向 receiver；profile 由具体 transport family 解释 |
| ResolvedTransportPlan | canonical topology 的只读运输投影 | 提供具名 hop 与按端口的 incoming/outgoing 查询；SystemProtocol topology 保持权威来源 |
| transport-network execution view | 从 SystemProtocol 派生的运输执行/分析视图 | family session 消费 resolved hop，并按需加入 router、buffer、VC/RP、route function 与 resource dependency |

## SystemProtocol 与组网

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| InterfaceConnection | 一份 InterfaceProtocol 的具体使用 | 把协议各 role 绑定到具体 `VirtualDutPortRef`，拥有独立 InterfaceSession |
| topology | 哪些具体端口通过哪些 connection/hop 相连 | SystemProtocol 中的显式 module/connection 图；boundary 与 system contracts 补充行为事实 |
| capability | 一个端口或模块能承诺什么 | width、burst、ID、ordering、byte enable、capacity 等边界投影 |
| address claim | 一个 endpoint 声称负责的地址范围 | 用于与 route window 校验；fabric backend 持有本地 decode table |
| address closure | route、claim 和转换在系统中是否闭合 | 检查可达性、唯一归属、remap 和目标 capability 的 elaboration/property |
| SystemProtocol | 多个 module 与连接形成的整体通信合同 | 拥有 topology、boundary、system contracts 和 elaboration；点到点是退化形式 |
| elaboration | 运行前把已声明系统解析清楚 | 校验引用、唯一占用、role/protocol、namespace 和已生成结构；runtime 消费闭合后的 plan |
| construction lowering | 把便捷声明展开成显式系统对象 | Builder 在授权 policy 下生成 bridge VirtualDut/connections，再交给 core elaboration |

## 执行、资源与证据

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| outstanding | 已接受但尚未完成的事务 | 持有 identity/obligation，通常占用 pending transaction 或 owner 资源 |
| capacity slot / lease | 当前允许占用的一份有限资源 | 本地 pool 中由 token acquire/release 的执行、buffer、correlation 或 outstanding 容量 |
| protocol credit | transaction-level 接纳许可 | CHI P-Credit 与 Retry lifecycle 关联，保证相应 completer 接纳重发 transaction |
| link credit | 相邻 transport 端点间的 flit 接纳许可 | CHI L-Credit 由 `ChiTransportLink` contract 管理；P-Credit 和本地 FIFO lease 各有独立生命周期 |
| blocked reason / demand | 当前 transition 继续执行还需要什么 | 指向所需资源或外部条件的 typed 等待原因，供调度和 wait-for 分析 |
| wait-for | 谁持有资源并等待谁 | token/resource/demand 形成的等待边；环只是 deadlock 分析的一个条件 |
| fixed point | 当前立即反应已经传播完 | SystemSession 队列为空的同步边界；RTL cycle 与 deadlock 结论使用各自模型 |
| quiescent | 当前没有未完成的内部事务 | 相关 monitor/backend 无 pending obligation；结论适用于当前运行前缀，后续输入可继续扩展 run |
| AtomicFrame | 同一观察边界内一起成立的采样集合 | pin/cycle adapter 的原子 lowering 输入；transaction 与全局 cycle 语义由对应合同声明 |
| verdict | 对当前有限运行前缀的判断 | PASS、FAIL、INCONCLUSIVE；未完成 obligation 通常使前缀 inconclusive |
| causality | 哪个事件促成了哪个事件 | trace 中的 happens-before/lineage 边，与单纯文件顺序不同 |
| provenance | 一个结论或构造选择从哪里来 | 输入、event、constraint、stage、policy、fault 和生成对象之间的来源链 |
| artifact | 一次运行留下的结构化证据 | 调用方所选 run root 中的 manifest、trace、graph 和 report；docs/showcase 发布由具名发布脚本显式执行 |
