# 当前实现状态

这份状态表描述 `protocol_model/` 当前已经落地的能力、明确边界与下一落点。条目使用三种状态语言：

| 标签 | 含义 | 后续动作 |
|---|---|---|
| 已进入主线 | 已有可导入实现及对应证据 | 维护已声明合同 |
| 当前边界／尚未实现 | 需要沿现有视图和职责新增切片 | 进入 roadmap 与独立验收 |
| 基线缺陷 | 自然路径违反已声明合同、错误输入失去原子拒绝，或实现与 claim 不一致 | 修复并增加最小回归 |

“当前边界”记录实现阶段，协议禁令只在有规范依据和明确 profile 时使用。

本页使用仓库当前 Python 名称：接口合同、运行账本和连接实例分别是 `InterfaceProtocol`、
`InterfaceSession` 和 `InterfaceConnection`，标准协议族位于 `protocol_model.protocols`。CHI 当前有受限的
Issue H direct-read/retry transaction profile，以及读取调用方拓扑的 transport-network slice。完整 RN-I
profile 的覆盖范围按下表各维度分别记录。三张视图及命名边界见
[通信建模的三张视图](communication-scope-and-transport.md)。

## 已进入主线

| 层级 | 当前能力 |
|---|---|
| 基础语义 | typed canonical event、value domain、event/transport/interface/VirtualDut/system constraint scope、resource/obligation、`ResourceDemand`/blocked transition、CausalGraph、可组合 fragment |
| observation | `AtomicFrame`、`AsynchronousSample`、ready-valid lowering、四相 REQ/ACK RTZ lowering、stall/data-window stability、reset epoch、quiet tied/stable policy |
| InterfaceProtocol | directed event kind、schema validation、profile refinement、event prohibition、bounded resource profile |
| 通用 pattern | keyed cardinality、burst assembly、FIFO join、completion ledger |
| AXI4 | 五通道、burst/narrow/unaligned、read interleave 判定、AW/W/B、exclusive、ordering 边界、状态驱动生成；AddressSpace endpoint 可选 bounded stepped R/B，并能按不同 RID round-robin 逐 beat 发射、按相同 RID 保持 batch 顺序 |
| AXI4-Lite | 原生五通道 schema、单 beat/in-order、多 outstanding、AXI4 embedding、ready-valid observation |
| AXI4-Stream | 单 T channel、byte qualifier、packet/interleave/order、Continuous_Packets profile、生成与 observation |
| AHB | AHB-Lite transaction/pipeline observer；AHB5 extended HPROT、secure、sparse strobe、exclusive signaling、User payload |
| APB3/APB4/APB5 | 独立 variant package、single outstanding、SETUP/ACCESS observation；APB5 user/wakeup/RME profile |
| ACE-Lite data | AXI4 五通道语义加 ACE-Lite domain/snoop/bar 组合检查；barrier/CMO 进入后续 profile |
| VirtualDut | 具名 module、typed InterfacePort/TransportPort、attachment SPI/binding/builder、APB/AHB/AXI AddressSpace endpoint、有限 FIFO/dynamic-delay address responder、有限 stepped-emission wrapper、Sensor FIFO、serialized memory-copy engine、edge interrupt collector/EOI target、Stream capture、单入口 AddressFabric、scheduled N×M address crossbar、AXI4 read-only AR/R 与 write-only AW/W/B N×M crossbar、read 1×M demux 特化、统一 AMBA serial bridge 构造 |
| SystemProtocol | 单一 topology registry 中的 InterfaceConnection/DirectedTransportConnection、typed ownership、elaboration、派生 ResolvedTransportPlan、同步 interface fixed-point 路由、显式 `DutAdvanceAction`、blocked step 原子回滚、系统 trace、递归封装，以及显式 address claim/router contract 的 direct-neighbor resolution |
| 产物与展示 | run store、manifest、记录投影、renderer/publisher、系统 topology/trace DOT、自动 VirtualDut 展开，以及 typed `TransactionTimeSpaceView` 到时空 DOT、显式因果 DOT 和离散 `model_step` 语义事件 WaveJSON 的投影。公开 witness 包括显式 single-ingress fabric 的 bus-strip、AXI4 AR/R 2×4 crossbar、逐案例四视图的 CHI Issue H flow gallery，以及与该 gallery 分开的 ring/star、4×4 mesh topology witness；flow gallery 五案都从 resolved `SystemProtocol` 构造并执行 participant→XP→participant route |

## 当前边界

CHI 覆盖按以下独立维度阅读：

| 维度 | 如何解释当前边界 |
|---|---|
| CHI lifecycle/profile 覆盖 | opcode 及 modifier、错误与并发组合尚未闭合，会限制可执行 transaction 集合 |
| representation 与 packetization | opcode/conditional-field **encoding inventory** 和 packed layout 属于表示；multi-packet DAT 还跨越分片表示与 transaction/session 聚合。single-packet profile 的网络运输能力按自身合同计入 |
| system construction | 若观察边界包含独立 SN，HN→SN downstream transaction/commit 是独立 participant/flow slice；SAM（System Address Map）和 dynamic multi-Home 表示 runtime 按地址区域选择或 remap Home；coherence-domain membership 属于 system authority |
| participant / VirtualDut policy | victim/LRU 与容量替换是 Cache policy。snoop filter 是 Home/ICN 维护的 cache-presence/选靶结构；当前 exact directory holder set 是 reference oracle，而带容量、更新和误判行为的 filter 才是可插拔 backend policy/state |
| coherence state/policy 扩展 | 当前 no-SD MESI slice 可独立成立；`SD`/Owned 作为可选状态/policy 扩展单独推进 |
| forwarding/DCT lifecycle | 首个 clean DCT 已让唯一 UC peer 直接向 requester 返回 `CompData_SC`，并以独立 `SnpRespFwded`/`CompAck` 在 Home 做乱序双输入 join；它是 clean ReadShared 的可选 modifier。dirty DCT、RetToSrc、动态多 peer 选择和一般 forwarding catalog 仍是后续 profile |
| verification property | waiter selection、公平性、wait-for analyzer 与 deadlock/livelock verdict 是系统/scenario 验证目标；被建模网络仍须满足适用的 CHI channel-dependency 与 forward-progress 合同 |
| observation / external integration | physical phit/lane、raw pin、RTL adapter/conformance 属于观察、接入和实现对照；CDC/异步采样按跨协议的通用时间/观察方法独立统计 |

### 通用能力与系统边界

| 能力 | 已实现与证据 | 当前边界／下一闭合条件 |
|---|---|---|
| raw RTL pin adapter | clocked `AtomicFrame` 与 edge-complete `AsynchronousSample` 边界已建立 | AXI 字段采集、VCD/UVM transaction adapter 和多 clock trace merge 后续位于协议 observation adapter；该项归入 observation/external integration |
| AXI WaveJSON | 通用显示 policy 已有 | 各 AXI variant 的 lane/field 投影由对应 interface protocol 子包提供 |
| bounded capacity | InterfaceProtocol profile 通过 offer/profile 限制 outstanding；forced 非法事件仍产生 interface fault。VirtualDut runtime 已区分 `BLOCK`、有序 deferred `ERROR_COMPLETION` 与 `FAULT`，queued responder、scheduled crossbar、AXI4 read/write crossbar、Sensor FIFO、interrupt collector 和 stepped output FIFO 使用显式有限资源。AXI4 read 按 ingress 限制 active RID 和每 RID pending burst；write 另行限制 pending AW、pre-AW W burst、buffered W beat、active BID 和每 BID accepted burst。ordered error marker 每 port/ingress 有一个应急槽，正常 FIFO 仍满且槽已占用时，再次 overflow 返回 `BLOCK`。`BLOCK` 由 SystemSession 整步回滚并交给 scenario 重试 | READY/HREADY/PREADY 的周期级投影尚待 observation/driver slice |
| blocked rollback granularity | 当前回滚边界是一项外部 `SystemAction`/`DutAdvanceAction`；单发射 backend 能保持精确接纳 | 一次 advance 同时发往多个 egress 时，任一 destination `BLOCK` 会回滚同批其他发射，形成保守的跨出口耦合。当前 Sensor→DMA 场景使用串行 requester，独立出口背压的下一条件是 emission-level admission 或可选择的单端口 service action |
| wait-for/deadlock | blocked reason 已能指出 resource、容量和位置。CHI family 可从 participant pending 与 transport endpoint head 只读投影 exact line holder、waiting `ResourceDemand`，并以 holder 消失形成 wakeup evidence | 当前投影的 scope 是 CHI family-local；packet acceptance 仍由 endpoint/session 状态确认，其他 blocker 继续独立检查。CHI channel-dependency/forward-progress 是被建模网络的适用合同；通用“发现后解锁”单元属于模型策略。response-path capacity、wait-for graph、escape transition 搜索与 deadlock verdict 尚待接入。watchdog 的证据范围是无进展诊断或场景级 recovery；deadlock 证明还需要可达性、enablement 与 obligation，错误响应只关闭对应 obligation |
| AMBA serial bridge | `build_amba_serial_bridge_vdut()` 按 ingress form 选择 single-access 或 AXI4 burst 路径；AXI4、AXI4-Lite、AHB、APB 的 4×4 family 组合共用一个 backend 与 egress requester factory。当前七个具体 variant 有 7×7 默认-profile 装配见证，执行覆盖代表性路径和 AXI→AHB→APB chain | 当前 profile 是单 ingress/egress、严格串行 child；width split/merge、burst-preserving egress、有限 ID remap pool 和并发 child 尚待实现 |
| typed transaction translation | signature/profile、unary/fanout stage、双向 plan closure、fan-out ledger、capacity pool/lease、attachment-aware operation backend、AddressAccess/AddressBurst route/shape/split stages 与统一 AMBA serial composition root 已落地 | 多层 fanout、并发 child 调度、完整 ordering/admission/fold metadata 和 blocked demand 仍待推进 |
| DUT 延后 emission | caller-owned `DutAdvanceAction` 已能推进 queued responder、scheduled crossbar 与通用 `SteppedEmissionBackend`。后者把 immediate output batch 放入有限 event FIFO，以动态 wait policy 在显式 service opportunity 间逐事件释放，并可按 batch ordering key round-robin；AXI4 Full AddressSpace endpoint 用 R/B channel+ID 保护同 ID 顺序并允许不同 RID 的 R beat 交织。非破坏式 prepare/current/accept offer 已保存未接纳 event 的所有权 | AXI RVALID/RREADY pin lowering、reset 清理、跨 connection lineage、自主 wakeup、clock domain、timeout 和异步调度进入后续 runtime/observation slice |
| protocol attachment | APB/AHB/AXI4-Lite address 两面已实现；AXI4 有 burst-aware subordinate 与 serialized requester；stateless canonical relay 可供 fabric 保留原始协议事件并复用方向/schema 检查；AXI4-Stream 有独立 StreamTransfer 两面；项目级 edge notification 有 notifier/handler 两面 | 新协议 attachment 按对应 operation SPI 和 binding 条件独立验收 |
| empty endpoint | APB/AHB/AXI idle source 与 blackhole sink 已可构造；请求—响应 blackhole 会保留 pending | 正常 error responder 尚待实现 |
| external backend | VirtualDut 的外部性已经确立 | opaque/RPC/RTL/trace backend binding 和不可枚举 state ownership 尚待进入代码 |
| constructed backend | 单入口 AddressFabric 已执行 Route/Correlate；协议无关 `ScheduledAddressCrossbarBackend` 已执行 per-ingress FIFO、per-egress round-robin、active owner 与 completion return，当前具体 recipe 为 AXI4-Lite。AXI4-specific read backend 接受任意非空 N×M port tuple，以 pending-burst ledger 派生 `(ingress, RID)` destination lock 和 `(egress, RID)` return-owner FIFO，执行 RLAST retire 与 ordered DECERR；1×M demux 是便捷特化。write backend 独立保存每 ingress AW/W assembly，AW 接纳时预留 BID destination/order slot，完整 burst 以 store-and-forward batch 发送，并从 `(egress, BID)` owner FIFO 返回 B；route miss 在消费匹配 W burst 后本地返回 DECERR。两者分别要求 read-only 或 write-only 五通道 `raw-ID-serialized` 普通事务 profile。`AddressOperationTranslationBridgeBackend` 承载 single-access 与 AXI burst→access 两条 AMBA serial 路径 | downstream ID remap、多 ingress exclusive、cut-through 和 Full AXI 五通道组合进入各自后续 profile；其余网络实验原件保持原有职责 |
| scenario traffic | `RandomTrafficController` 按 source role 与当前 EventOffer 生成可复现 canonical-event 流量，并可与 SystemSession interface state 同步 | raw pin/cycle driver 由 observation/driver adapter 闭合 |
| sensor/DMA scenario | AXI4-Lite serialized DMA 已经通过 1×2 scheduled crossbar 从固定地址 Sensor FIFO 搬运到递增 MemoryRegion，并覆盖快速 sensor 的 `DROP_NEWEST`/overrun；AMBA recipe 会在构造期检查 beat/address geometry。read-only/write-only 等 event prohibition profile 可在首次不兼容发射时报告 attachment fault | DMA 当前是 construction-time descriptor fixture；CSR 编程面和 completion-to-interrupt binding 尚待加入 |
| reference/RTL conformance | 当前 executor 与 scenario 生成 deterministic execution witness，可检查 operation effect、owner/lifetime 和结果映射 | 当前 witness 的证据范围是语义执行，逐周期 golden trace 需要通用 checker 按 stutter、identity、允许重排和必要偏序比较两侧 RTL observation；该 checker 归入模型—RTL 接入/验证 |
| boundary runtime/嵌套执行 | 可以封装 subsystem | 外部边界注入与内部 session 生命周期仍需统一 |
| address closure | `AddressClaim`、`AddressRouterContract`、`SystemProtocolBuilder` 和 `ResolvedAddressPlan` 已闭合显式 router route 到唯一 direct-neighbor claim，并按 ingress×route 形成路径 | router identity 由显式 contract 提供，endpoint private AddressSpace 继续由 endpoint 持有；multi-hop 搜索进入后续 construction slice |
| system boundary projection | bridge typed translation 已有 capacity、completion origin 和 attribute effect；generated crossbar 会从实际 backend 配置公开 `AddressRouterBoundaryProjection` 并在 construction 时与 router contract 核对 | external/opaque DUT assertion、capability、return、resource/wait-for projection 与 runtime monitor 尚缺 |
| ordering | 单 interface connection 的 beat、same-ID、AW/W/B 与同帧可见性可判定；AXI4 read crossbar 用 manager-local RID destination lock 和 subordinate-local raw-ID owner FIFO 恢复 R 归属，write crossbar 从 AW 接纳起用 BID destination lock，并在完整 AW/W 转发后用 `(egress, BID)` FIFO 恢复 B 归属 | 当前 raw-ID profile 会把同 egress/同 ID 并入一条 downstream ordering stream；通用的内存可见性和跨 connection ordering property 尚待建模 |

### CHI representation、transport 与 lifecycle

| 能力 | 已实现与证据 | 当前边界／下一闭合条件 |
|---|---|---|
| typed representation / codec | operation translation 已有；CHI Issue H 已把 typed protocol message、named logical-field record、`ChiNetworkPacket` 与 `ChiProtocolFlit` 分成显式对象。当前 profile 覆盖 33 个 protocol-message form：十五个 REQ、八个 RSP、四个 DAT 和六个 SNP；两个 operation-specific returning Atomic REQ 显式携带 `SnoopMe/Endian`，独立 `DBIDResp` RSP 将 `RespErr/Resp` 固定为零，首个 clean DCT 另显式分离 `SnpSharedFwd` 的 `FwdNID/FwdTxnID` 与 `SnpRespFwded` 的 `Resp/FwdState`。`ReadNoSnp/WriteNoSnp{Full,Ptl}` 已显式编码 5-bit LPID，`ChiRespErr` 类型化 `OK/EXOK/DERR/NDERR` 的两位编码。logical-field codec 已验证 ordinary/Exclusive `WriteNoSnpPtl`、`NonCopyBackWrData`、`CompData_I(NDERR/EXOK)`、clean `CompData_UC(CAH=1)`、AtomicSwap/AtomicLoad ADD/DBIDResp、CleanUnique、MakeUnique/`SnpMakeInvalid`、Evict/`Comp_I`、clean DCT forwarding pair、`WriteEvictFull(CAH={0,1})`、`WriteEvictOrEvict(CAH=0)` 双 outcome、正常 writeback 和零 data/byte-enable `CopyBackWrData_I` 的精确字段、常量/宽度/profile 诊断及双向 round-trip。`LCrdReturn` 是 hop-local link flit；network packet 单独持有 source/target route identity 与 packet index/count | opcode/conditional-field encoding inventory 与 packed bit layout 按表示覆盖统计；可执行 opcode 还需 lifecycle、capability/flow、状态效应和 witness。multi-packet DAT 的 fragment/DataID/字段一致性归入表示，split/reassembly、缺失/重复/乱序处理与 terminal retirement 归入 transaction/session；physical phit/lane、raw pin 与 RTL timing 归入 observation/external integration。当前 single-packet logical profile 按 resolved network 合同执行 |
| transport contract | CHI Issue H 的有向 link 共享四态 activation，REQ、RSP、SNP、DAT 分别持有独立 L-Credit；REQ 支持 1–8 个 dedicated Resource Plane，RSP/SNP/DAT 使用标量 credit。四类 channel-only 有限点对点路径覆盖 pre-state 接纳、receiver reservation、backpressure、capture/drain 和 deactivation credit return；protocol traffic 以携带 packet 的 flit 跨 hop，`LCrdReturn` 作为 link-local credit 返回并跳过 network packetization。一个 `AtomicFrame` 内的已启用 channel 统一提交或回滚 | shared credit、replicated channel、异步 activation race 和全网原子 tick 是 transport profile/runtime 扩展；FLITPEND/raw pin lowering 归入 observation/external integration |
| CHI network/router slice | `SystemProtocolBuilder.connect_transport()` 已将有向 CHI connection 放入 canonical topology，elaboration 形成 `ResolvedTransportPlan`。一条 connection 可同时启用 REQ/RSP/SNP/DAT，并以一个 activation state 配合各 channel 独立的 FIFO、receiver reservation 与 L-Credit；lineage 按 `connection + channel` 保存。`ChiTransportNetworkSession` 读取 plan 与调用方 router registry，原子提交 capture→router 和 router service→downstream enqueue。有限 store-and-forward router 按 packet 的 `channel + target_id` 精确路由并保持 protocol message 原值；RN→router→Home、ring 或 mesh 由调用方 topology 提供。SNP protocol-message schema 省略 `TgtID`，目标身份由 per-target packet route 表达；coherent Home 按 clean Shared/Unique、CleanUnique/MakeUnique invalidate、dirty unique 和 no-SD ReadNotSharedDirty profile 从目录选择目标并建立 packet copy。`ChiBehaviorFacet` 已区分 transaction/forwarding behavior；NodeID identity plan、flow projector 与 feature capability resolver 可形成构造期闭合证据。`ChiCoherenceAuthorityContract` 将通用 `AddressClaim` 绑定到 scalar Home 与可选 coherence domain；resolver 派生 finite Snoopee set，并逐成员闭合 SNP 去程、RSP/DAT 回程和 capability。clean Shared/Unique、CleanUnique、dirty WriteBack、WriteEvictFull base 与 CopyAtHome modifier 可绑定有限 requester set，Snoopee authority 取各 requester eligible-peer 的并集；同一 RN 可在不同 transaction 中分别承担 requester 与 Snoopee。CopyAtHome 依赖 clean ReadUnique acquisition 与 WEF base，并增加 no-data 所需的 `Comp` 与 `CompAck` RSP flow；WEOE 要求 REQ、Home→Requester RSP、Requester→Home DAT 与 CompAck RSP 四条 flow，单笔 conditional CopyBack 按 Home outcome 使用 DAT 或 CompAck 终态 | 通用 multicast switch 与 topology-wide fanout scheduler 尚待实现。当前 resolved witness 使用同构 requester set；异构 per-feature scope 和一般 multi-Requester construction 进入后续 resolver slice。`WriteEvictFull(CAH=0/1)` 与 `WriteEvictOrEvict(CAH=0)` 的已闭合 profile 发射零 SNP；clean-residency 边界仍要求选择 coherence domain。resolved system 的 authority 来自 contract 派生结果，手工 Home/Snoopee role 仅作 unresolved construction input。当前每个 feature scope 选择一个 claim/scalar Home，authority window 按 claim 的 system-visible 地址解释；multi-Home runtime、SAM remap/translated authority 与通用 participant/identity API 尚待实现 |
| CHI Immediate Write lifecycle | Full/Ptl sibling profile 已闭合 `WriteNoSnp{Full,Ptl} REQ→CompDBIDResp RSP→NonCopyBackWrData DAT`：REQ 保存 Requester original TxnID，DAT 以 Home DBID 作为 TxnID。Full 使用整条 512-bit line；Ptl 以 rounded-down `Addr/Size` window 约束 BE，支持 masked merge 与 zero-BE retirement。两者共享 requester TxnID→DBID lifecycle、Home DBID/same-line reservation、backing version guard 与 exact packet evidence；direct/XP witness 均闭合三条 flow。2026-07-29 复核发现的 Ptl `CCID=original Addr[5:4]` 与 `CompDBIDResp.TraceTag→DAT` 缺陷已修复，Home/session 会原子拒绝伪造字段，最小负例已锁定该合同 | 当前 resolved session 选择 Full 或 Ptl 一种 requester profile；Retry、DWT、Device-memory、multi-packet DAT、错误终态、共同 coherent Home aggregate 和 topology-visible HN→SN transaction 尚待实现 |
| CHI returning Atomic lifecycle | built-in feature catalog 现有 24 项，其中 `AtomicSwap` 与 `AtomicLoad ADD` 两项 operation-specific profile 均闭合 Size=0..3（1/2/4/8-byte）、自然对齐、little-endian、`PAS=0`、Normal Non-cacheable、`SnpAttr=0/SnoopMe=0` 的 `REQ→DBIDResp RSP→NonCopyBackWrData DAT→CompData_I DAT` 四包生命周期。Requester-line-I 是每次 issue/submit 的显式外部 admission 证据。Requester 按 Addr/Size 生成自然 lane、动态 byte enable 与 `CCID=original Addr[5:4]`，以 Home DBID 发送 operand，继续以 original TxnID 接收旧值 completion。Home 在 captured backing version 与 same-line reservation 下执行一次 immutable RMW：Swap 做 selected-width masked replacement，Load ADD 做 fixed-width `(old + operand) & mask`，二者都提交新值并返回旧值。两项 feature 共享 requester/Home、backing、DBID 和 same-line runtime，可在同一 runtime 组合。direct 与单 XP witness 对每项 operation 闭合四条 flow，两向 DAT 路径逐 hop 要求 512-bit capability | `SnpAttr=0/SnoopMe=0` 是当前窄 profile；Home snoop profile、big-endian、Retry/error、early CompData、其他 Atomic operation、其他 PAS、HN→SN 与组件级 `Atomic_Transactions` 仍待闭合。与其他 backing-owning lifecycle 组合前需建立共同 Home state owner |
| CHI non-snoop Exclusive lifecycle | 首个 aligned Ptl profile 已闭合显式 `SrcID+LPID` 的 `ReadNoSnp(Excl)→CompData_EXOK→WriteNoSnpPtl(Excl)→CompDBIDResp_{EXOK,OK}→NonCopyBackWrData_OK`。Requester 用跨 Read/Write 的单 LP outstanding gate；aggregate Home 共同拥有 backing、64-byte conservative System monitor 与 DBID。另一 LP 的实际 nonzero masked commit 命中 granule 才失效；EXOK 才提交，普通 OK 消费 DAT 并保持 backing 原值。独立 feature 闭合五条 flow 与 direct/XP witness。2026-07-29 复核发现的 read/write DAT `CCID`、response→DAT `TraceTag` 和 Home pass/fail↔`EXOK/OK` checkpoint 三项缺陷均已修复并有伪造状态负例 | 当前 profile 选择一个 configured LP；monitor overflow/unsupported endpoint、多 LP 并行、Full/coherent Exclusive、Retry/DMT/DWT、Device/error 与 Atomic 尚待闭合。与其他 lifecycle 组合前需建立共同 backing/System-monitor owner |
| CHI read/coherence lifecycle | participant、packet-delivery 与 topology-backed session 已闭合 `ReadNoSnp`/NDERR/Retry、clean Shared/Unique、dirty-owner transfer、no-SD MESI `ReadNotSharedDirty`、CleanUnique、MakeUnique、clean Evict/Retry、WriteBackFull、`WriteEvictFull(CAH=0/1)`、`WriteEvictOrEvict(CAH=0)` 及其具名 response 前 Snoop 组合。首个 clean ReadShared DCT modifier 闭合 `SnpSharedFwd(B,FwdTxnID=A)→peer CompData_SC(A,DBID=B)+SnpResp_SC_Fwded_SC(B)→CompAck(B)`：resolved scalar forwarding peer 属于 authority domain 且区别于 requester；peer `UC→SC`、requester `I→SC`，Home 对 forwarded response/CompAck 做乱序双输入 join，join 前 directory/backing 保持原值，join 后一次提交两名 sharer。base Home→requester DAT 路径保留为 fallback | 当前 DCT profile 固定 clean、单 peer、`RetToSrc=0`。DERR/post-Snoop error、MakeUnique Retry/error/MTE/partial-write、CopyBack 其余 Retry/error phase、一般 transient/Retry cancel、dirty/一般 forwarding 仍待扩展。Home 发出 `Comp`/`CompDBIDResp` 后，同址 Snoop 接纳门分别在 `CompAck`/DAT 后重新开放。victim/LRU 与容量 outcome 归入 Cache/Home VirtualDut policy；Owned/SD、snoop filter、HN→SN、multi-Home/SAM、multi-packet DAT 和 deadlock/fairness 分别由 coherence state、system construction、representation/session 与 verification 维度管理 |
| requirement catalog | 协议语义已有声明 | 官方章节、执行 monitor 和覆盖状态的逐条目录仍待建立 |

MakeUnique 的组合边界还包括一个双向 transient 缺口：当前 construction 分开选择 MakeUnique 与
MESI ReadNotSharedDirty；下一闭合条件是 pending MakeUnique 接收 `SnpNotSharedDirty`、pending
ReadNotSharedDirty 接收 `SnpMakeInvalid` 的 same-line 双向路径。

packet-delivery composition 对 coherent read、CleanUnique、MakeUnique、Evict、WriteBack、WriteEvictFull
与 WriteEvictOrEvict 的 Home→Requester completion/`CompDBIDResp` 保存并一次性消费完整 packet evidence。
三类 CopyBack 现由 typed `ChiCopyBackPhaseLedger` 统一保存 operation、identity 与
`HOME_RESPONSE/REQUESTER_DATA/REQUESTER_ACK` 下一阶段；旧的 operation-specific mappings 只作为构造兼容输入
和只读投影，canonical ledger 持有唯一运行权威。RN 成功接收 `CompDBIDResp` 后，再为其实际产生的
`CopyBackWrData` 保存 RN→Home exact evidence，Home 成功消费后一次性退休；WEOE 和 WEF(CAH=1) 的
no-data outcome 则保存并消费 Home-selected `Comp` 与 RN-produced `CompAck` evidence。CopyBack response
phase 以 original TxnID、data/ack phase 以 Home DBID 分别关联；
RN 发出 DAT 或 Ack 后可以复用 original TxnID，新 response 与旧 DBID reservation 保持独立。只复用
transaction identity 而替换 data、byte enable、Resp、DBID、RespErr、端点或 packet metadata，以及
replay，均保持 RN/Home 状态原值并形成拒绝证据。该 evidence 属于 system correlation，CHI wire
representation 保持原状。

本页的 “post-snoop error” 专指**同一笔已接纳 request 已经发出 Snoop 后**形成的错误路径。另一笔
transaction 使同一 RN cache line 失效、随后 credited reissue 在自身发 Snoop 前返回 NDERR 的情形属于
已闭合的 pre-Snoop 窄组合。

## 已识别的术语与对象边界债务

这些项目已经有较明确的修正方向，但涉及数据形状或公共职责；表中修正条件决定何时迁移：

| 当前对象 | 审核判断 | 后续修正条件 |
|---|---|---|
| `ConstraintKind` | 同时混入 safety/progress 的性质分类与 relation/resource 的约束对象分类 | requirement catalog 开始消费性质分类时，拆成 property class 与 constraint subject，并迁移报告 schema |
| CHI packetization cardinality | message、network packet、protocol flit 已是独立对象；当前 executable profile 保持一份 message content。Snoop fanout 可为同一语义消息生成 per-target copies，每份 copy 的 fragment index/count 固定为 `0/1` | 首个 multi-packet DAT 场景引入 splitter/reassembler、fragment lineage 与缺包/重复包检查；fanout copy identity 与分片序号分别保存 |
| CHI participant / VirtualDut composition | cache/Home `attach` 分别从 `CacheCore`/`FullLineBackingCore` 创建第一个 VirtualDut；两种 binder 都接收既有 canonical declaration 与 port-channel map，并让 assembly/facet 保持同一 object identity。binder 输出 participant/facet，网络连接由 system composition 完成；resolver 以只读方式核对 object identity、NodeID、channel flow 与 authority。Home binder 的当前 profile 要求 declaration 尚未绑定 executable backend，因为 CHI participant runtime 与通用 backend runtime 尚无共享 module-state 容器 | 独立 Memory/SN-F 场景需要一个共享动态状态 owner，并显式构造 HN→SN flow、SN participant 和 topology-visible downstream commit witness。第二种同 module 多 runtime facet 场景出现后，再提取通用 binder/state composition API |
| CHI CopyBack legacy evidence projection | `ChiCopyBackPhaseLedger` 已成为 WriteBackFull、WriteEvictFull 与 WriteEvictOrEvict 的唯一 exact-evidence 权威，统一 TxnID→DBID phase split、Home DBID namespace 和 DAT/ack terminal；原 operation-specific mappings 仍保留为 constructor 兼容输入及只读投影 | 下游调用者全部迁移到 canonical ledger 输入后删除兼容入口；opcode-specific permission、directory、backing 与 residency effect 继续留在 participant transition |
| `participants/router.py` | store-and-forward router 属于 forwarding facet；RN/HN/SN/MN 属于 transaction participant。语义区分已由 `ChiFacetKind` 建立，但源码仍与 participant 实现同包 | 第二种 forwarding module 或独立 routing policy 出现时移入 `network/routing`，以真实复用需求作为迁移依据 |
| `chi/issue_h/interface/` | 当前主要保存跨多条消息的 transaction ledger，目录名容易与通用 `InterfaceProtocol` 混淆 | 引入更多 opcode/message 时迁入 `transactions/` 或 `protocol/`，再由 participant/system slice 组合 |
| AXI/AHB attachment 的 requester/completer 类名 | `InterfacePort.role` 已使用标准 manager/subordinate；部分类名沿用 address-operation SPI 的请求/完成方向 | operation SPI 与标准 role 需要同时公开时，改成 manager/subordinate 的协议类名或显式 `AddressOperationEmitter/Consumer`，一次完成两套公开命名的收束 |
| artifacts / visualization composition | `RunBundle` 同时组合 store 与 publisher，包级依赖尚未完全单向 | reporting/publication 成为独立用户流程时提取 composition root，renderer 与 store 分别由 composition root 装配 |

AXI4 protocol-bound execution 已从 recipe 目录归位到
`integrations/backends/amba/axi/axi4/{address_space,read,write}.py`。1×M read demux 现在是通用 N×M read
backend 的 recipe 配置；Full AXI composite 按功能缺口归档。
AMBA protection decode/encode stage 也已从 bridge recipe 目录移入 `integrations/translations/amba/`；bridge
目录中的 `_address_recipe.py` 只保留 attachment 选择、route-width 与 target-shape 等装配期 helper。

根 `protocol_model` 已收为延迟加载的架构入口，只公开 `CanonicalEvent`、`InterfaceProtocol`、`VirtualDut`、
`SystemProtocol` 四个概念锚点和版本号。协议、构造 recipe、运行状态及辅助类型由所属 facade/叶包公开；仓内代码
从宽根入口读取版本号，其余依赖均指向所属 facade/叶包。

`DutBehaviorTag` 已收束为非权威的发现/显示标签；设备能力由 backend 或 boundary contract 投影，
复合性由 `subsystem` 直接派生。路由、容量、attachment 状态与 capability 继续由各自 owner 提供。

## 协议与 profile 状态详录

### AMBA family

- AXI4 继续作为 memory-mapped InterfaceProtocol 的主要推进对象，优先补 requirement catalog、optional fields 和
  协议本地可视化；AXI4-Lite 已作为原生 schema variant 落地。
- AXI4-Stream 是独立 InterfaceProtocol；后续 width conversion/packing 由 stream bridge VirtualDut
  组合，AXI4 memory-mapped 保持独立继承链。
- APB3/APB4/APB5 由私有 SETUP/ACCESS phase engine 构造，对外暴露独立版本 API。APB4 的
  PPROT/PSTRB 相互独立；APB5 已有 user/wakeup/RME，parity 在当前 profile 中关闭。
- AHB-Lite 是共享 transaction core；AHB5 已派生 Issue C interface properties。普通 address profile 的
  AHB→APB/AXI 路径可由统一 serial builder 构造；多-manager arbitration、decoder/response mux 和
  exclusive conflict monitor 仍由相应 interconnect/memory VirtualDut 组合。
- 当前 ACE-Lite 入口明确命名为 `build_ace_lite_data_interface()`；barrier、CMO 和 full ACE snoop
  channel 需要专用 monitor 后再扩大公开名称范围。

### CHI Issue H

#### 表示与 transport

CHI Issue H 已完成构造依赖、判定作用域与表示/运输三张视图的边界审计，并有受限 direct-Home
  `ReadNoSnp→CompData` 与 `RetryAck→PCrdGrant→AllowRetry=0 重发→CompData` 纵向见证，以及拓扑无关的
  CHI transport-network session。typed message→network packet→protocol flit 边界已经显式化；SNP 当前覆盖
  `SnpShared`/`SnpUnique`/`SnpNotSharedDirty`/`SnpCleanInvalid`/`SnpMakeInvalid` representation、
  独立 channel L-Credit、共享 Link
  activation、FIFO/reservation、背压与 capture/drain。

Snoop 的选定目标由每份 packet 的 network route identity 表达。

#### Participant lifecycle

clean `ReadShared` 与 `ReadUnique` profile 已加入目录选靶、显式 per-target packet、clean SnpResp 聚合、
  `I/SC/UC` cache state、CompData/CompAck correlation 与稳定点一致性检查。clean-peer CleanUnique
  另以零 DAT 的 `SnpCleanInvalid→SnpResp_I→Comp_UC→CompAck` 完成 `SC→UC`；`I` 发起或 pending
  CleanUnique 被同址失效后，`Comp_UC` 形成 payload-invalid 的 `UCE`。独立 MakeUnique 以
  `MakeUnique→SnpMakeInvalid→SnpResp_I→Comp_UC→CompAck` 完成无 DAT 的 full-line overwrite：
  submit API 保存 RN-local store intent，`Comp_UC` 原子安装为 `UD`；Home 到 Ack 才提交 unique
  directory authority，backing payload/version 保持原值。规范 expected initial requester state 为
  `I/SC/SD`；当前模型另允许 `UC/UCE` 并拒绝 `UD`。因为该路径可产生 `UD`，与 clean ReadUnique
  组合时当前 construction 要求 dirty-unique-transfer modifier，与 clean-peer CleanUnique 组合时要求
  shared-dirty modifier；与 MESI ReadNotSharedDirty 的双向 same-line transient 尚未闭合，当前
  construction 分别选择两项 feature；双向 transient 闭合后再开放共同选择。

#### Dirty ownership、Retry 与 role closure

dirty-unique 扩展再加入
  `UD`、本地 full-line write、`SnpRespData_I_PD` 和 `CompData_UD_PD` responsibility transfer；MESI
  `ReadNotSharedDirty` 扩展通过 `SnpNotSharedDirty(DoNotGoToSD=1)`、`SnpRespData_SC_PD`、
  Home pending 接管、`CompData_SC`、`CompAck` 后 backing/directory commit，把 dirty unique line 转成
  两个 clean shared copy。`CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER` 再允许一个预置
  `SD`/`shared_dirty_owner` 经 `SnpCleanInvalid→SnpRespData_I_PD→I` 把最新数据交给 Home pending，
  Home 在 completion 前 prepare 协议中立 backing write，并在 `CompAck` 后以 line-version CAS 与 unique
  directory 一次提交。该 slice 的 scope 止于 Home reference backing，独立 Memory/SN downstream
  transaction/commit 与完整 MOESI/Owned 进入后续切片。clean ReadUnique 的 Retry modifier 另将 shared Request-Retry/P-Credit
  contract 组合进同一 RN/Home participant：`RetryAck` 保留原请求，`PCrdGrant` 按
  `(Home, PCrdType)` 池化并在 Home 预留真实槽，自动 credited reissue 后才进入既有 SnpUnique lifecycle；
  clean Evict 的独立 Retry modifier 复用该 ledger，但采用单独 feature/policy gate：
  `Evict→RetryAck→PCrdGrant→AllowRetry=0 重发→Comp_I`。拒绝阶段保持 directory/backing 和
  Home allocator 原值，system composition 对 RetryAck 与 P-Credit 保存并一次性消费 exact packet evidence。
  当前 coherent modifier 覆盖一次 Retry 后成功；取消和公平选择进入后续 Retry/runtime slice。这些 lifecycle 分别登记为
  构造期 feature；dirty-unique 依赖 clean ReadUnique，而独立
  ReadNotSharedDirty feature 无此依赖。no-SD policy preset 组合二者。dirty-data 扩展增加
  Snoopee→Home DAT flow。flow projector 只投影
  当前合同及依赖，gap 计算因而限定在所选 feature scope。Snoopee role 已支持
  显式有限 peer set，成员 capability、SNP 去程和 RSP 回程逐一闭合；空 peer set 是有效显式声明，漏绑仍报告
  role gap。`ChiCoherenceSession.from_resolved()` 已把 closed role set、component singleton NodeID、
  requester/Snoopee authority 与启用 feature 带入 packet-level runtime registry；
  packet-delivery composition 保存并一次性消费 Home-produced exact SNP delivery evidence；同一
  transaction identity 被换成另一 opcode/message，或在 completion 后重放的 SNP，会在进入 RN 前被拒绝。

#### Network delivery 与 progress projection

`ChiCoherenceNetworkSession` 已让这些 participant emission 经 resolved network 自动运输和交付，并以
  显式 pending batch 保存受背压的 fanout。endpoint delivery 遇到 Home 同址 reservation 时保留 packet
  与网络状态；`CompAck` 释放 reservation 后，family scheduler 会重新尝试该 endpoint head。只读
  `project_progress()` 可把 Home/RN pending 投影为 held line，并把当前 blocked endpoint head 投影为
  waiting demand；`project_wakeups()` 报告 exact holder 释放，一般 wait-for/deadlock 分析另由 system
  verification property 闭合。

#### Same-line transient 与 CopyBack

`SC→ReadUnique→UC→local write→UD` 与
  clean/shared-dirty-peer `SC→CleanUnique→UC` 已进入 participant lifecycle；集合从 coherence domain 自动
  派生。pending `ReadUnique` 与同址 `SnpUnique` 的 RN transient 已允许 `I/SC→I`，按
  `RetToSrc` 与原 payload 返回 `SnpResp_I` 或 `SnpRespData_I`，同时保留 pending/Retry correlation，
  随后由 `CompData_UC` 重新安装 line；pending `CleanUnique` 同样接纳
  `SnpUnique`/`SnpCleanInvalid`，按相同数据规则响应并保留 correlation，后续 `Comp_UC` 在无 payload 时
  形成 `UCE`，full-line local write 再完成 `UCE→UD`。pending MakeUnique 也可在同址 invalidating Snoop
  后保留 store intent，并由自己的 `Comp_UC` 安装为 `UD`。direct 双 Requester witness 已闭合同址 CleanUnique
  串行化。pending WriteBack 也已闭合 `LIVE_UD→CANCELED_I`、`CopyBackWrData_I(Data=0, BE=0)` 和
  Home snapshot/version guard；另一条 direct 双 Requester witness 证明 CleanUnique 先转移 dirty data、
  迟到 WriteBack 再由 system-derived stale-owner evidence 安全退休。该 evidence 的 scope 是 system；
  CHI wire representation 保持原状，独立 Home 需要 system 提供该 admission。同时启用 CleanUnique 与
  dirty WriteBack 的同构 requester set 已形成 resolved XP witness；等待者
  合并/优先级、异构 per-feature requester scope 和一般多 Requester topology 仍未闭合。
  MakeUnique 的 dirty-peer resolved witness 恰好运输 REQ、SNP、SnpResp、Comp、CompAck 五个 packet，
  并确认零 DAT、dirty discard、Ack 前 reservation 与 backing invariance。`WriteEvictOrEvict(CAH=0)` 也已用
  `UC/SC × data/no-data` 四个三包 resolved witness 闭合：Home 显式选择
  `CompDBIDResp→CopyBackWrData_{UC,SC}` 或 `Comp_I→CompAck`，两者都只移除 requester authority 并保持
  reference backing 原值。response 前的同址 invalidating Snoop 另以 direct 双 Requester witness 覆盖
  `UC/SC × data/no-data`：RN 保留原 REQ/`LikelyShared` 并进入 `CANCELED_I`，迟到
  `CompDBIDResp`/`Comp` 分别以零 data/BE 的 `CopyBackWrData_I`/`CompAck_I` 退休；system-derived
  stale-holder admission 与 Home snapshot/version guard 保持新 owner、backing 和 clean residency 原值。
  当前 scalar-requester resolver 覆盖四个正常 outcome 的 topology/flow；双 Requester cancel 的
  resolved witness 等待 requester-cardinality 扩展。`WriteEvictFull(CAH=1)` modifier 另让 RN 只从 clean
  `ReadUnique` 返回的 `CompData_UC(CAH=1)` 缓存 unchanged-line provenance；本地写、失效或 line removal
  会清除该证据，缺失证据的 CAH=1 REQ 在 RN admission 原子失败。CAH=1 只说明 RN 自 Home 给出标记后没有
  修改该行；Home 当前 copy 由 `clean_residency` 另行证明。首个 Home profile 因此要求
  `read_unique_copy_at_home_policy` 与 `write_evict_full_current_copy_policy`：前者只在已有匹配
  Snoop-domain clean residency 时产生 CAH=1；后者的 `CHECK_CURRENT_COPY` profile 可继续请求 data，只有当前
  residency 仍存在时才允许 no-data `Comp→CompAck_UC`，否则使用
  `CompDBIDResp→CopyBackWrData_UC`。这项 current-copy 检查是当前模型的窄化策略；通用 CHI 语义仍按
  CAH 与 CopyBack 规范条款解释；
  参数化 resolved witness 已通过真实 resolver/capability/flow closure 和
  `ChiCoherenceNetworkSession` 分别执行两个正常终态。随后闭合的 response 前 invalidating-Snoop 窄组合
  覆盖 `SnpUnique`、`SnpCleanInvalid` 与 `SnpMakeInvalid`：Snoop 清除当前 line/payload 和 cached
  provenance，但 pending 中冻结的原 REQ/TxnID/`CAH=1` 仍作为历史 correlation；后续
  `CompDBIDResp` 产生 `CopyBackWrData_I(Data=0, BE=0)`，`Comp` 产生 `CompAck_I`。
  system-derived `SNOOP_CANCELED` 退休旧 reservation，并保留期间形成的新 owner、reference
  backing 和 clean residency。response 前 `SnpShared` 的非失效分支也已闭合：RN 从 `UC→SC`、返回
  `SnpResp_SC`、清除当前 CAH provenance，并保留 frozen WEF 为 `LIVE_SC`。随后
  `CAH={0,1}` 的 data outcome 都要求 `CopyBackWrData_SC`；CAH=1 的 no-data outcome 要求
  `CompAck_SC`。system 只在 RN outcome、Home clean-sharer directory 和 backing payload 一致时派生
  `CURRENT_SHARED_HOLDER` admission；该证据的 scope 是 system，CHI wire representation 保持原状。
  2RN+HN+XP resolved witness 在旧 RN
  接收 `SnpShared` 并进入 `LIVE_SC` 后即把 WEF 送向 Home；因 ReadShared 的 directory transition
  尚未提交，WEF 先在 Home line resource 阻塞。五包
  `ReadShared/SnpShared/SnpResp_SC/CompData_SC/CompAck` 完成后，runtime replay WEF，并分别以
  `WriteEvictFull/CompDBIDResp/CopyBackWrData_SC` 或 `WriteEvictFull/Comp/CompAck_SC` 退休；
  每种共八个 endpoint packet。Home 已发 `Comp` 后须等
  `CompAck`、已发 `CompDBIDResp` 后须等 DAT，post-response 同址 Snoop 仍作为 ordering 负例而非正向
  lifecycle。Retry/error 与容量驱动 outcome 仍分别等待 protocol modifier 和 Home/Cache VirtualDut policy。
  Home attach/canonical binder 已用独立
  `FullLineBackingCore` 落地，并可保持调用方 clean-residency core 的对象身份。该 slice 的 CHI
  lifecycle/profile 尚未加入 deliberate dirty invalidate、WriteEvictFull 的 post-response Snoop 与
  Retry/error 组合，以及 WriteEvictOrEvict post-response/其他 Snoop phase、Retry/error 与容量驱动 outcome policy。自动
  victim/writeback scheduling 是可选 Cache VirtualDut policy；一般 `SD` 生成与 Owned 是当前 MESI slice
  之上的 coherence-state/policy 扩展；首个 clean ReadShared forwarding/DCT 已独立闭合，dirty、
  `RetToSrc=1`、动态多 peer 与一般 forwarding catalog 仍是后续 CHI lifecycle/capability。
  stateful snoop filter 是 Home/interconnect backend policy：假阳性只增加 Snoop，若用它抑制必要 Snoop，
  假阴性则会破坏一致性；当前 exact directory holder set 的 scope 固定为无容量、无误判 reference oracle。

#### System witness 与展示证据

HN→SN protocol commit 是需要独立 SN participant、flow 与 system witness 的下游集成 slice；当前 CHI
网络可用性由已闭合的 participant/flow scope 判定。公开 CHI Issue H flow gallery 为每个案例分别执行模型，并从该案例
  自身的一次执行投影 resolved topology、transaction time-space、explicit causality 和 semantic
  event timeline。五案都构造一个 `ChiStoreForwardRouterNode` XP abstraction，并让每个 endpoint packet
  经 participant→XP→participant 两段 route；WriteBackFull 同址干涉案通过公开 scheduler candidate
  暂停 WBF REQ 的 router capture，CleanUnique 退休后再释放。该选择声明语义顺序；周期和物理延迟由
  timing profile 另行提供。与 flow gallery
  分开的 ring/star 和 4×4 mesh topology witness 各执行一条受限 `ReadNoSnp → CompData`，用于观察调用方
  显式构造的多跳 store-and-forward route、exact NodeID route、L-Credit 与最终 quiescence；其 coverage
  scope 固定为 route/credit/quiescence。展示把 `ChiStoreForwardRouterNode` 标为 XP abstraction，只声明有限
  ingress、exact route、egress 与逐 hop credit；完整 XP 微架构进入独立实现 profile。flow 时空投影会过滤
  coherence state 保持原值的 transport `MOVE`；`model_step` 表达语义顺序，XP 周期或物理延迟需要 timing model。
  clean ReadUnique Retry 已由 resolved scheduler 让两次
  REQ、RetryAck、PCrdGrant、SNP/RSP、CompData/CompAck 自动推进；direct ReadNoSnp retry/cancel witness 继续验证
  `PCrdReturn`。clean Evict Retry 的 direct resolved witness 则恰好运输两份 Evict REQ、RetryAck、
  PCrdGrant 与 `Comp_I` 五个 packet，并验证零 SNP/DAT/CompAck。aligned full-DAT-width direct read
  已通过 `ChiAddressHomeNode` 委派给协议无关
  `AddressTarget`；authority 内 decode/access failure 已沿同一 resolved XP topology 返回
  `CompData_I(NDERR)` 并闭合无有效数据的 transaction result。coherent `ReadUnique` 的独立 NDERR
  modifier 也已用三 packet XP witness 闭合预侦听错误完成：无 SNP，Requester 原 cache、peer、directory
  与 backing 保持原值，DBID/同址 reservation 由 `CompAck` 退休。coherent Home 则使用支持延迟 line commit 的
  `FullLineBackingCore`；`AddressTarget` 继续保持同步 address operation API。当前 CHI lifecycle/profile 覆盖尚缺 coherent
  DERR、post-snoop/组合错误路径和 MakeUnique Retry/error/MTE Update/partial-write 扩展。
  multi-packet DAT 与 narrow completion 需要同时扩展分片表示和 transaction/session 聚合；同 Home/type waiter 的具名选择/公平性是
  runtime 验证 property；动态 address→Home/multi-Home/SAM 属于 system authority/runtime；可推进的
  Sensor target 是通用 runtime 的相邻需求。NodeID ownership 和当前 feature 所需的
  route/capability closure 已在 CHI family resolver 中落地。这里的 opcode/field 与 transaction-local
  correlation、participant cache/directory/backing，以及跨节点 authority/invariant 分别属于表示/完整逻辑
  接口、VirtualDut 与 SystemProtocol 三种投影；`TransportLink` 仍只负责单向 hop 的运输。

### Integration ownership 与其他 family

- VirtualDut 定义 attachment SPI 和本地 binding，具体 AMBA 转换位于
  `protocol_model.integrations.attachments.amba`；对应模块构造位于
  `protocol_model.integrations.recipes.amba`。完整逻辑接口由 SystemProtocol 连接 `InterfacePort`；展开单向
  transport hop 时连接 `TransportPort`。协议定义提供合同，由 integration 完成 `attach(vdut)`。
- ready-valid 是 observation encoding；需要一个点到点数据协议时，由具体 EventSchema 和
  InterfaceEventKind 组合；当前顶层入口保持收束。
- four-phase REQ/ACK 同样是 observation encoding；当前提供独立 token InterfaceProtocol 作为最小承载，也可将
  observer 绑定到已有 event schema。two-phase toggle、独立 reset recovery 和 system CDC closure 尚待场景驱动；
  它们归入通用 observation/control-topology coverage。
- `protocol_model.protocols.tilelink` 已建立家族命名空间，但尚无具体 builder/observer。未来 TL-UL/TL-UH/TL-C
  用于检验 multibeat、source/sink ID、denied/corrupt 和 coherence 作用域。

## 文档与运行产物

- 稳定概念、视图和职责边界维护在 `docs/architecture/`，入口是
  [架构说明索引](README.md)。
- [技术路线](technical-route/README.md)按构造依赖、判定作用域和表示/运输解释概念，定义继续由 canonical
  架构页维护。
- 本页维护当前实现状态；[根路线图](../../ROADMAP.md)维护长期能力方向，具体施工边界放在对应实施案中。
- 一次运行的 trace、图和报告进入调用方选择的 run root；省略路径时仍可使用临时默认 `out/`。
- 从 protocol record 生成的临时参考文档进入 scratch 或临时目录；仓内 `out/doc-build/` 只按显式任务使用。
- 长期示例由具名脚本显式发布到 `docs/examples/` 或 `showcase/generated/`；普通测试写入临时 run root。
