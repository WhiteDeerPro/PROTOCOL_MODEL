# 术语表

[返回架构地图](README.md) · [架构文档索引](../README.md)

本表先给白话含义，再说明工程中的准确边界。同一个词在硬件规范中可能有更窄的定义；协议专题会在需要
时补充具体 profile。

## 通信事实

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| event | 已经发生的一件通信事实 | 一次被模型接受的消息或动作；不等同于持续一段时间的信号电平 |
| canonical event | 不依赖具体 pin 名称的统一事件 | `CanonicalEvent`：带 kind、key、typed payload 和可选 trace index 的协议语义事件 |
| trace | 按观察顺序记录的一串事件 | session 接受的有限事件序列及其状态、fault、causal projection |
| channel | 一组方向和用途相同的消息 | LinkProtocol 中把 schema 绑定到发送 role 的逻辑通道，例如 AXI AR 或 APB READ |
| role | 端点在一份协议中的相对身份 | requester/completer、manager/subordinate、transmitter/receiver；不是设备类型 |
| beat | 多拍传输中的一个数据单位 | 一次可计数的传输或 completion 单元；具体字段和接受条件由协议定义 |
| burst | 一笔由多个 beat 组成的事务 | 共享 descriptor/identity，并带 beat 数量、地址几何和完成关系的 transaction |
| transaction | 从请求到承诺完成的一段通信生命周期 | 可以打开一个或多个 obligation，并占用 outstanding/correlation 资源 |
| completion | 对先前请求的协议可见结果 | response、acknowledgement 或 result beat；必须能关联并解除相应 obligation |
| token | 在生命周期中代表一笔工作或身份的记录 | 可携带 parent/child identity、来源、属性和 continuation；不等同于 capacity credit |

## 字段、规则与单链路协议

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
| LinkProtocol | 一条逻辑连接上允许使用的语言 | channels、roles、schemas、monitors、parameters 和 semantic fragments 的不可变声明 |
| profile / refine | 在基础协议上增加限制 | 不改变协议基本方向的前提下收窄合法行为，例如 read-only 或 bounded outstanding |
| LinkSession | 一条具体 link 的运行账本 | 独立保存该 link 的 monitor 状态、resource usage、trace 与 verdict |

## VirtualDut 与协议接缝

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| operation | 模块真正处理的协议无关工作 | `AddressAccess`、`AddressBurst`、`StreamTransfer` 等 typed semantic form |
| emission | 模块执行后向端口产生的输出 | `PortEmission` 或语义组件 emission；可以是 0..N 个，不预设等于 RTL cycle |
| effect | 操作对模块内部或相邻行为造成的影响 | `DutEffect` 等协议无关效果记录；不一定直接变成 link event |
| backend | 模块行为的权威来源 | 本地 constructed model，或 RTL、RPC、trace、Python oracle 等外部实现 |
| backend state | 为继续执行而保存的模块状态 | 功能状态、attachment 运输状态和跨端口 owner 等，由 backend snapshot 统一容纳 |
| boundary contract | 模块对外公开的假设和保证 | 端口、capability、资源和可观察行为投影；不暴露 backend 私有状态 |
| ProtocolPort | 具体 module 边界上的协议接口 | 指定 LinkProtocol、role、capability、clock/reset domain 的静态端口声明 |
| attachment / codec | 单端口的协议翻译器 | 在 CanonicalEvent 与某类 operation 之间转换，并声明单端口运输状态 |
| binding | 把某个 codec 装到某个端口 | `PortAttachmentBinding`：静态关联 ProtocolPort 与 attachment，不保存运行状态 |
| transport shape | 两个协议端口的线上传输外形 | event kind、字段、方向、role 和关键参数的兼容投影；不等于全部行为语义相同 |
| integration | 协议与模块操作的依赖汇合区 | 同时依赖 LinkProtocol 与 VirtualDut SPI 的 attachment、plan preset 和 recipe |
| recipe | 把已有构件装成具体对象的入口 | 选择 port、binding、backend、plan 和 profile；不重新定义各构件的运行语义 |
| VirtualDut | 系统图中的一个具体虚拟 module | 具名 ports、bindings、backend 和边界语义；不按 AXI/APB 建立设备继承树 |

## 事务转译与互连

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| operation form/signature | 一类工作及其结果的类型 | request form、可选 completion form 和稳定 semantic domain 名称 |
| decoded operation / parent envelope | 把业务操作与返回身份一起交给 executor | attachment 产出 operation + opaque reply context；executor 再分配 parent token，直到结果编码完成 |
| lowering | 从较外部或较丰富的表示得到内部表示 | 可指 pin/frame→event，也可指 parent operation→child operation；必须注明作用域 |
| TranslationStage | 两种 operation form 之间的带类型箭头 | 同时声明 lower、completion lift/fold、cardinality、capability 和属性处理 |
| TranslationPlan | 一条经过闭合检查的事务转译方案 | stage、scheduler、resource/storage policy 和 provenance 的不可变构造结果 |
| translation frame | 一笔 parent 转译的语义上下文 | 保存 stage context、expansion cursor 和 result fold；不复制 fanout ledger 的计数 |
| fanout ledger | parent 拆成 child 后的生命周期账本 | 保存 total、issued、completed、inflight 与 lineage，不承担结果聚合本身 |
| lineage | parent 与 child 的来源关系 | 记录某个 child operation/result 属于哪一个 parent token 及位置 |
| local completion | 不访问下游即可形成的正常结果 | route miss→decode error 等由本模块直接解除 obligation 的 completion |
| result fold | 把一个或多个 child result 还原为 parent result | 保持 beat 顺序、重组数据或聚合最坏错误状态 |
| conversion policy | 允许怎样改变业务语义 | preserve、default、remap、split、reject、emulate 等静态选择 |
| scheduling policy | 已确定的 child 何时发行 | serial、window-K、仲裁顺序等执行选择 |
| storage profile | executor 可保存多少运行上下文 | parent queue、payload beat、result accumulator、owner table 等容量 |
| route | 请求应该去哪个出口 | 地址/目的标识到 egress 和可选 remap 的局部选择关系 |
| owner | completion 应该归还给谁 | egress/ID/child 与原 ingress/parent 之间保存的动态关系 |
| correlation | 把分离事件重新认作同一生命周期 | AW/W join、request/response、parent/child result 等 FIFO 或 keyed 关系 |
| bridge | 在两个端口语义之间转换的 VirtualDut | 常见端口形状为 1→1；内部一笔 parent 可以产生多个 child |
| crossbar | 多入口、多出口的互连 VirtualDut | 组合 route、arbitration、owner/ID mapping、capacity 和 ordering |

## SystemProtocol 与组网

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| ProtocolLink | 一份 LinkProtocol 的具体使用 | 把协议各 role 绑定到具体 `VirtualDutPortRef`，拥有独立 LinkSession |
| topology | 哪些具体端口通过哪些 link 相连 | SystemProtocol 中的显式 module/link 图，不等于全部系统语义 |
| capability | 一个端口或模块能承诺什么 | width、burst、ID、ordering、byte enable、capacity 等边界投影 |
| address claim | 一个 endpoint 声称负责的地址范围 | 用于与 route window 校验，不等同于 fabric 本地 decode table |
| address closure | route、claim 和转换在系统中是否闭合 | 检查可达性、唯一归属、remap 和目标 capability 的 elaboration/property |
| SystemProtocol | 多个 module 和 link 的整体通信协议 | 拥有 topology、boundary、全局 semantics 和 elaboration；点到点是退化形式 |
| elaboration | 运行前把已声明系统解析清楚 | 校验引用、唯一占用、role/protocol、namespace 和已生成结构；不在 runtime 猜测拓扑 |
| construction lowering | 把便捷声明展开成显式系统对象 | Builder 在授权 policy 下生成 bridge VirtualDut/links，再交给 core elaboration |

## 执行、资源与证据

| 术语 | 白话解释 | 在本工程中的准确含义 |
|---|---|---|
| outstanding | 已接受但尚未完成的事务 | 持有 identity/obligation，通常占用 pending transaction 或 owner 资源 |
| capacity slot / lease | 当前允许占用的一份有限资源 | 本地 pool 中由 token acquire/release 的执行、buffer、correlation 或 outstanding 容量 |
| protocol credit | 在线上传递的流控许可 | 例如 CHI Link Credit；属于相应 LinkProtocol，不与本地 lease 共用运行规则 |
| blocked reason / demand | 当前 transition 为什么不能继续 | 指向所需资源或外部条件的 typed 等待原因，供调度和 wait-for 分析 |
| wait-for | 谁持有资源并等待谁 | token/resource/demand 形成的等待边；环只是 deadlock 分析的一个条件 |
| fixed point | 当前立即反应已经传播完 | SystemSession 队列为空的同步边界；不等同于 RTL cycle 或 deadlock 证明 |
| quiescent | 当前没有未完成的内部事务 | 相关 monitor/backend 无 pending obligation；不表示未来不会再收到输入 |
| AtomicFrame | 同一观察边界内一起成立的采样集合 | pin/cycle adapter 的原子 lowering 输入，不默认等同于完整 transaction 或全局 cycle |
| verdict | 对当前有限运行前缀的判断 | PASS、FAIL、INCONCLUSIVE；未完成 obligation 通常使前缀 inconclusive |
| causality | 哪个事件促成了哪个事件 | trace 中的 happens-before/lineage 边，与单纯文件顺序不同 |
| provenance | 一个结论或构造选择从哪里来 | 输入、event、constraint、stage、policy、fault 和生成对象之间的来源链 |
| artifact | 一次运行留下的结构化证据 | 调用方所选 run root 中的 manifest、trace、graph 和 report；不会由测试隐式发布到 docs/showcase |
