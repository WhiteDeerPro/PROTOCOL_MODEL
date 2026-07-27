# 当前实现状态

这份状态表描述 `protocol_model/` 当前已经落地的能力、明确边界与下一落点。“尚未实现”表示该能力
仍需按照现有视图和职责设计，不代表协议本身禁止或架构永久排除。

本页使用仓库当前 Python 名称：接口合同、运行账本和连接实例分别是 `InterfaceProtocol`、
`InterfaceSession` 和 `InterfaceConnection`，标准协议族位于 `protocol_model.protocols`。CHI 当前有受限的
Issue H direct-read/retry transaction profile，以及读取调用方拓扑的 transport-network slice；这不代表完整
RN-I profile 已经实现。三张视图及命名边界见
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
| ACE-Lite data | AXI4 五通道语义加 ACE-Lite domain/snoop/bar 组合检查；不含 barrier/CMO |
| VirtualDut | 具名 module、typed InterfacePort/TransportPort、attachment SPI/binding/builder、APB/AHB/AXI AddressSpace endpoint、有限 FIFO/dynamic-delay address responder、有限 stepped-emission wrapper、Sensor FIFO、serialized memory-copy engine、edge interrupt collector/EOI target、Stream capture、单入口 AddressFabric、scheduled N×M address crossbar、AXI4 read-only AR/R 与 write-only AW/W/B N×M crossbar、read 1×M demux 特化、统一 AMBA serial bridge 构造 |
| SystemProtocol | 单一 topology registry 中的 InterfaceConnection/DirectedTransportConnection、typed ownership、elaboration、派生 ResolvedTransportPlan、同步 interface fixed-point 路由、显式 `DutAdvanceAction`、blocked step 原子回滚、系统 trace、递归封装，以及显式 address claim/router contract 的 direct-neighbor resolution |
| 产物与展示 | run store、manifest、记录投影、renderer/publisher、系统 topology/trace DOT、自动 VirtualDut 展开、显式 single-ingress fabric 的 bus-strip 折叠投影，以及 AXI4 AR/R 2×4 crossbar 可执行 witness |

## 当前边界

| 能力 | 状态与下一落点 |
|---|---|
| raw RTL pin adapter | clocked `AtomicFrame` 与 edge-complete `AsynchronousSample` 边界已建立；AXI 字段采集、VCD/UVM transaction adapter 和多 clock trace merge 后续位于协议 observation adapter |
| AXI WaveJSON | 通用显示 policy 已有；各 AXI variant 的 lane/field 投影应留在对应 interface protocol 子包 |
| bounded capacity | InterfaceProtocol profile 通过 offer/profile 限制 outstanding；forced 非法事件仍产生 interface fault。VirtualDut runtime 已区分 `BLOCK`、有序 deferred `ERROR_COMPLETION` 与 `FAULT`，queued responder、scheduled crossbar、AXI4 read/write crossbar、Sensor FIFO、interrupt collector 和 stepped output FIFO 使用显式有限资源。AXI4 read 按 ingress 限制 active RID 和每 RID pending burst；write 另行限制 pending AW、pre-AW W burst、buffered W beat、active BID 和每 BID accepted burst。ordered error marker 每 port/ingress 有一个应急槽，正常 FIFO 仍满且槽已占用时，再次 overflow 返回 `BLOCK`。`BLOCK` 由 SystemSession 整步回滚并交给 scenario 重试；向 READY/HREADY/PREADY 的周期级投影尚未实现 |
| blocked rollback granularity | 当前回滚边界是一项外部 `SystemAction`/`DutAdvanceAction`。单发射 backend 能保持精确接纳；一次 advance 同时发往多个 egress 时，任一 destination `BLOCK` 会回滚同批其他发射，形成保守的跨出口耦合。当前 Sensor→DMA 场景使用串行 requester 不触发该边界；独立出口背压需要 emission-level admission 或可选择的单端口 service action |
| wait-for/deadlock | blocked reason 已能指出 resource、容量和位置；held-resource edge、response-path capacity、wait-for graph 与 deadlock verdict 尚未接入。错误响应只能结束特定 obligation，不单独构成无死锁保证 |
| AMBA serial bridge | `build_amba_serial_bridge_vdut()` 按 ingress form 选择 single-access 或 AXI4 burst 路径；AXI4、AXI4-Lite、AHB、APB 的 4×4 family 组合共用一个 backend 与 egress requester factory。当前七个具体 variant 有 7×7 默认-profile 装配见证，执行覆盖选择代表性路径和 AXI→AHB→APB chain。当前 profile 是单 ingress/egress、严格串行 child；width split/merge、burst-preserving egress、有限 ID remap pool 和并发 child 尚未实现 |
| typed transaction translation | signature/profile、unary/fanout stage、双向 plan closure、fan-out ledger、capacity pool/lease、attachment-aware operation backend、AddressAccess/AddressBurst route/shape/split stages 与统一 AMBA serial composition root 已落地；多层 fanout、并发 child 调度、完整 ordering/admission/fold metadata 和 blocked demand 仍待推进 |
| DUT 延后 emission | caller-owned `DutAdvanceAction` 已能推进 queued responder、scheduled crossbar 与通用 `SteppedEmissionBackend`。后者把 immediate output batch 放入有限 event FIFO，以动态 wait policy 在显式 service opportunity 间逐事件释放，并可按 batch ordering key round-robin；AXI4 Full AddressSpace endpoint 用 R/B channel+ID 保护同 ID 顺序并允许不同 RID 的 R beat 交织。非破坏式 prepare/current/accept offer 已保存未接纳 event 的所有权；AXI RVALID/RREADY pin lowering、reset 清理、跨 connection lineage、自主 wakeup、clock domain、timeout 和异步调度仍暂缓 |
| protocol attachment | APB/AHB/AXI4-Lite address 两面已实现；AXI4 有 burst-aware subordinate 与 serialized requester；stateless canonical relay 可供 fabric 保留原始协议事件并复用方向/schema 检查；AXI4-Stream 有独立 StreamTransfer 两面；项目级 edge notification 有 notifier/handler 两面 |
| empty endpoint | APB/AHB/AXI idle source 与 blackhole sink 已可构造；请求—响应 blackhole 会保留 pending，正常 error responder 尚未实现 |
| external backend | VirtualDut 的外部性已经确立；opaque/RPC/RTL/trace backend binding 和不可枚举 state ownership 尚未进入代码 |
| constructed backend | 单入口 AddressFabric 已执行 Route/Correlate；协议无关 `ScheduledAddressCrossbarBackend` 已执行 per-ingress FIFO、per-egress round-robin、active owner 与 completion return，当前具体 recipe 为 AXI4-Lite。AXI4-specific read backend 接受任意非空 N×M port tuple，以 pending-burst ledger 派生 `(ingress, RID)` destination lock 和 `(egress, RID)` return-owner FIFO，执行 RLAST retire 与 ordered DECERR；1×M demux 是便捷特化。write backend 独立保存每 ingress AW/W assembly，AW 接纳时预留 BID destination/order slot，完整 burst 以 store-and-forward batch 发送，并从 `(egress, BID)` owner FIFO返回 B；route miss 在消费匹配 W burst 后本地返回 DECERR。两者分别要求 read-only 或 write-only 五通道 profile，当前均为 `raw-ID-serialized` 普通事务，不含 downstream ID remap、多 ingress exclusive、cut-through 或 Full AXI 五通道组合。`AddressOperationTranslationBridgeBackend` 承载 single-access 与 AXI burst→access 两条 AMBA serial 路径；其余网络实验原件保持原有职责 |
| scenario traffic | `RandomTrafficController` 按 source role 与当前 EventOffer 生成可复现 canonical-event 流量，并可与 SystemSession interface state 同步；raw pin/cycle driver 仍需 observation/driver adapter |
| sensor/DMA scenario | AXI4-Lite serialized DMA 已经通过 1×2 scheduled crossbar 从固定地址 Sensor FIFO 搬运到递增 MemoryRegion，并覆盖快速 sensor 的 `DROP_NEWEST`/overrun；AMBA recipe 会在构造期检查 beat/address geometry，但 read-only/write-only 等 event prohibition profile 仍可能在首次不兼容发射时报告 attachment fault。DMA 仍是 construction-time descriptor fixture，尚无 CSR 编程面和 completion-to-interrupt 绑定 |
| reference/RTL conformance | 当前 executor 与 scenario 生成 deterministic execution witness，可检查 operation effect、owner/lifetime 和结果映射；尚无把两侧 RTL observation 按 stutter、identity、允许重排和必要偏序与 contract 比较的通用 checker，因而 witness 不作为逐周期 golden trace |
| boundary runtime/嵌套执行 | 可以封装 subsystem；外部边界注入与内部 session 生命周期仍需统一 |
| address closure | `AddressClaim`、`AddressRouterContract`、`SystemProtocolBuilder` 和 `ResolvedAddressPlan` 已闭合显式 router route 到唯一 direct-neighbor claim，并按 ingress×route 形成路径；不从 topology 推断 router、不搜索多跳、不读取 endpoint 私有 AddressSpace |
| system boundary projection | bridge typed translation 已有 capacity、completion origin 和 attribute effect；generated crossbar 会从实际 backend 配置公开 `AddressRouterBoundaryProjection` 并在 construction 时与 router contract 核对。external/opaque DUT assertion、capability、return、resource/wait-for projection 与 runtime monitor 尚缺 |
| ordering | 单 interface connection 的 beat、same-ID、AW/W/B 与同帧可见性可判定；AXI4 read crossbar 用 manager-local RID destination lock 和 subordinate-local raw-ID owner FIFO 恢复 R 归属，write crossbar 从 AW 接纳起用 BID destination lock，并在完整 AW/W 转发后用 `(egress, BID)` FIFO 恢复 B 归属。当前 raw-ID profile 会把同 egress/同 ID 并入一条 downstream ordering stream；通用的内存可见性和跨 connection ordering property 仍未建模 |
| typed representation / codec | operation translation 已有；CHI Issue H 已把 typed protocol message、named logical-field record、`ChiNetworkPacket` 与 `ChiProtocolFlit` 分成显式对象。当前 profile 覆盖 20 个 protocol-message form：七个 REQ、六个 RSP、三个 DAT 和四个 SNP；`ChiRespErr` 类型化 `OK/EXOK/DERR/NDERR` 的两位编码，logical-field codec 已验证 `CompData_I(NDERR)`、CleanUnique 与 writeback forms 的精确字段、常量/宽度/profile 诊断及双向 round-trip。各 channel 的 `LCrdReturn` 保持为不进入 message codec/packet 的 hop-local link flit；Network packet 单独持有 source/target route identity 与 packet index/count。当前尚未实现 phit/raw pin、packed bit layout、完整 opcode/conditional-field catalog 和实际 multi-packet DAT splitter/reassembler |
| transport contract | CHI Issue H 的有向 link 共享四态 activation，REQ、RSP、SNP、DAT 分别持有独立 L-Credit；REQ 支持 1–8 个 dedicated Resource Plane，RSP/SNP/DAT 使用标量 credit。四类 channel-only 有限点对点路径覆盖 pre-state 接纳、receiver reservation、backpressure、capture/drain 和 deactivation credit return；protocol traffic 以携带 packet 的 flit 跨 hop，`LCrdReturn` 不进入 network packet。一个 `AtomicFrame` 内的已启用 channel 统一提交或回滚。shared credit、replicated channel、FLITPEND/raw pin lowering、异步 activation race 和全网原子 tick 尚未实现 |
| CHI network/router slice | `SystemProtocolBuilder.connect_transport()` 已将有向 CHI connection 放入 canonical topology，elaboration 形成 `ResolvedTransportPlan`。一条 connection 可同时启用 REQ/RSP/SNP/DAT，并以一个 activation state 配合各 channel 独立的 FIFO、receiver reservation 与 L-Credit；lineage 按 `connection + channel` 保存。`ChiTransportNetworkSession` 读取这份 plan 及调用方 router registry，原子提交 capture→router 和 router service→downstream enqueue。有限 store-and-forward router 按 network packet 的 `channel + target_id` 精确路由且不改写 protocol message；Session 不内置 RN→router→Home、ring 或 mesh。SNP message 不拥有协议 `TgtID`；coherent Home 可按 clean Shared/Unique、dirty unique 和 no-SD ReadNotSharedDirty profile 从目录选择目标，并为每个 Snoopee 建立显式 packet copy。通用 multicast switch 与 topology-wide fanout scheduler 尚未实现。`ChiBehaviorFacet` 已区分 transaction/forwarding behavior，NodeID identity plan、flow projector 与 feature capability resolver 可形成 CHI-family 构造期闭合证据。`ChiCoherenceAuthorityContract` 引用通用 `AddressClaim`，将 claim 绑定到 scalar Home 与可选 coherence domain；resolver 从 domain 派生 finite Snoopee set，并按每个成员闭合 SNP 去程、RSP/DAT 回程和 participant capability。手工 Home/Snoopee role 不再是 resolved system 的并行权威源。当前每个 feature scope 仍只选择一个 claim/scalar Home，authority window 按 claim 的 system-visible 地址解释；multi-Home runtime、SAM remap/translated authority 与通用 participant/identity API 尚未实现 |
| CHI read/coherence lifecycle | direct-Home `ReadNoSnp`、clean Shared/Unique read、clean ReadUnique Retry、pre-snoop ReadUnique NDERR、dirty-owner transfer、MESI no-SD `ReadNotSharedDirty`、显式 `UD` WriteBackFull 和两种受限 CleanUnique 已在 participant、packet-delivery 与 topology-backed session 中闭合。direct `ChiAddressHomeNode` 已将 authority 内 `AccessStatus.DECODE_ERROR/ACCESS_ERROR` 映射为 `CompData_I(NDERR)`，沿原 DAT flow 保留 TxnID/HomeNID/DataID 并退休 outstanding；Requester 结果以 `succeeded=False/data=None` 拒绝把线上零占位当有效数据。resolved session 只有在 feature closure 选中相应 NDERR modifier 时才开放错误完成：direct base-only construction 在 Home 状态提交前报告 profile fault；coherent session 在构造期拒绝 policy/feature 不配对，并在 packet-delivery 边界拒绝伪造 NDERR。coherent modifier 在 admission 后、Snoop 前由显式 Home policy 选择：只分配 DBID，直接返回 `CompData_I(NDERR)`，Requester 保持原 `I` 或 `SC` cache/payload 并返回 `CompAck`；Home 到 Ack 前维持 pending/同址 reservation，Ack 后只退休 DBID，directory、backing 与 Snoop TxnID 均不变。协议中立 `CacheLineStore/CacheCore` 持有 RN payload；`FullLineBackingCore/LineBackingState` 以 fixed-resident full-line、pure prepare 和 line-local version CAS 持有 Home reference payload，directory 只保存 holder authority。coherent Retry 在拒绝阶段不分配 Snoop/DBID、不建 pending、不改 directory/backing，credited reissue 才进入原 ReadUnique lifecycle；shared-dirty CleanUnique、dirty ReadNotSharedDirty 与 CopyBack write 均在声明的原子边界提交 backing/directory。canonical binder 不创建 port/connection，并拒绝第二份 executable Home payload authority；reference commit 仍不是独立 Memory/SN-F physical commit。九个 coherence feature 和 direct NDERR modifier 均有构造期 claim，Home/Snoopee 继续从 selected address claim、Home authority 与 coherence domain 派生。缺口包括 DERR 数据损坏来源、post-snoop/组合错误路径、`MakeUnique`、clean `Evict`、自动 victim/writeback scheduling、Retry/error/Snoop 并发、Retry cancel/multi-waiter、same-line transient/hazard、多 pending emission batch、一般 `SD`/Owned lifecycle、forwarding snoop、真实 snoop filter、独立 Memory/SN protocol commit、narrow/multi-packet completion 和 multi-Home/SAM runtime；有界运行耗尽仍为 inconclusive，不是 deadlock proof |
| requirement catalog | 协议语义已有声明；官方章节、执行 monitor 和覆盖状态的逐条目录仍待建立 |

## 已识别的术语与对象边界债务

这些项目已经有较明确的修正方向，但涉及数据形状或公共职责，当前不靠表面改名掩盖：

| 当前对象 | 审核判断 | 后续修正条件 |
|---|---|---|
| `ConstraintKind` | 同时混入 safety/progress 的性质分类与 relation/resource 的约束对象分类 | requirement catalog 开始消费性质分类时，拆成 property class 与 constraint subject，并迁移报告 schema |
| CHI packetization cardinality | message、network packet、protocol flit 已是独立对象；当前 executable profile 不拆分 message 内容。Snoop fanout 可为同一语义消息生成 per-target copies，但每份 copy 的 fragment index/count 仍为 `0/1` | 首个 multi-packet DAT 场景引入 splitter/reassembler、fragment lineage 与缺包/重复包检查；不把 fanout copy identity 混入分片序号 |
| CHI participant / VirtualDut composition | cache/Home `attach` 分别从 `CacheCore`/`FullLineBackingCore` 创建第一个 VirtualDut；两种 binder 都接收既有 canonical declaration 与 port-channel map，并让 assembly/facet 保持同一 object identity。binder 只形成 participant/facet，不连接网络；resolver 核对 object identity、NodeID、channel flow 与 authority，不创建、复制或修改 VirtualDut。Home binder 当前拒绝已有 executable backend，因为 CHI participant runtime 与通用 backend runtime 尚无共享 module-state 容器 | 若验证目标需要独立 Memory/SN-F，共享动态状态不能靠同时驱动两个 backend；应显式构造 HN→SN flow、SN participant 和 physical commit witness。第二种需要同 module 多 runtime facet 的真实场景出现后，再提取通用 binder/state composition API |
| `participants/router.py` | store-and-forward router 是 forwarding facet，不是 RN/HN/SN/MN transaction participant；语义区分已由 `ChiFacetKind` 建立，但源码仍与 participant 实现同包 | 第二种 forwarding module 或独立 routing policy 出现时移入 `network/routing`，避免只为目录整齐搬移 |
| `chi/issue_h/interface/` | 当前主要保存跨多条消息的 transaction ledger，目录名容易与通用 `InterfaceProtocol` 混淆 | 引入更多 opcode/message 时迁入 `transactions/` 或 `protocol/`，再由 participant/system slice 组合 |
| AXI/AHB attachment 的 requester/completer 类名 | `InterfacePort.role` 已使用标准 manager/subordinate；部分类名沿用 address-operation SPI 的请求/完成方向 | operation SPI 与标准 role 显示需要同时公开时，改成 manager/subordinate 的协议类名或显式 `AddressOperationEmitter/Consumer`，避免半套迁移 |
| artifacts / visualization composition | `RunBundle` 同时组合 store 与 publisher，包级依赖尚未完全单向 | reporting/publication 成为独立用户流程时提取 composition root，不让 renderer 或 store 互相拥有 |

AXI4 protocol-bound execution 已从 recipe 目录归位到
`integrations/backends/amba/axi/axi4/{address_space,read,write}.py`。1×M read demux 现在只是通用 N×M read
backend 的 recipe 配置，不再维护无独立行为的 subclass；Full AXI composite 仍是功能缺口，而不是目录迁移债务。
AMBA protection decode/encode stage 也已从 bridge recipe 目录移入 `integrations/translations/amba/`；bridge
目录中的 `_address_recipe.py` 只保留 attachment 选择、route-width 与 target-shape 等装配期 helper。

根 `protocol_model` 已收为延迟加载的架构入口，只公开 `CanonicalEvent`、`InterfaceProtocol`、`VirtualDut`、
`SystemProtocol` 四个概念锚点和版本号。协议、构造 recipe、运行状态及辅助类型由所属 facade/叶包公开；仓内代码
除读取版本号外不再依赖宽根入口。

`DutBehaviorTag` 已收束为非权威的发现/显示标签；`STORING` 不再作为设备能力，复合性由 `subsystem`
直接派生。路由、容量、attachment 状态与 capability 仍从 backend 或 boundary contract 获取。

## 协议策略

- AXI4 继续作为 memory-mapped InterfaceProtocol 的主要推进对象，优先补 requirement catalog、optional fields 和
  协议本地可视化；AXI4-Lite 已作为原生 schema variant 落地。
- AXI4-Stream 是独立 InterfaceProtocol；后续 width conversion/packing 属于 stream bridge VirtualDut，不放进
  AXI4 memory-mapped 的继承链。
- APB3/APB4/APB5 由私有 SETUP/ACCESS phase engine 构造，对外暴露独立版本 API。APB4 的
  PPROT/PSTRB 相互独立；APB5 已有 user/wakeup/RME，parity 在当前 profile 中关闭。
- AHB-Lite 是共享 transaction core；AHB5 已派生 Issue C interface properties。普通 address profile 的
  AHB→APB/AXI 路径可由统一 serial builder 构造；多-manager arbitration、decoder/response mux 和
  exclusive conflict monitor 仍由相应 interconnect/memory VirtualDut 组合。
- 当前 ACE-Lite 入口明确命名为 `build_ace_lite_data_interface()`；barrier、CMO 和 full ACE snoop
  channel 需要专用 monitor 后再扩大公开名称范围。
- CHI Issue H 已完成构造依赖、判定作用域与表示/运输三张视图的边界审计，并有受限 direct-Home
  `ReadNoSnp→CompData` 与 `RetryAck→PCrdGrant→AllowRetry=0 重发→CompData` 纵向见证，以及拓扑无关的
  CHI transport-network session。typed message→network packet→protocol flit 边界已经显式化；SNP 当前覆盖
  `SnpShared`/`SnpUnique`/`SnpNotSharedDirty` representation、独立 channel L-Credit、共享 Link
  activation、FIFO/reservation、背压与 capture/drain。
  Snoop request 不在 message 中携带 `TgtID`，选定 Snoopee 由每份 packet 的 network route identity 表达；
  clean `ReadShared` 与 `ReadUnique` profile 已加入目录选靶、显式 per-target packet、clean SnpResp 聚合、
  `I/UC/SC` cache state、CompData/CompAck correlation 与稳定点一致性检查。clean-peer CleanUnique
  另以 `SnpCleanInvalid→SnpResp_I→Comp_UC→CompAck` 完成不搬运数据的 `SC→UC`。dirty-unique 扩展再加入
  `UD`、本地 full-line write、`SnpRespData_I_PD` 和 `CompData_UD_PD` responsibility transfer；MESI
  `ReadNotSharedDirty` 扩展通过 `SnpNotSharedDirty(DoNotGoToSD=1)`、`SnpRespData_SC_PD`、
  Home pending 接管、`CompData_SC`、`CompAck` 后 backing/directory commit，把 dirty unique line 转成
  两个 clean shared copy。`CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER` 再允许一个预置
  `SD`/`shared_dirty_owner` 经 `SnpCleanInvalid→SnpRespData_I_PD→I` 把最新数据交给 Home pending，
  Home 在 completion 前 prepare 协议中立 backing write，并在 `CompAck` 后以 line-version CAS 与 unique
  directory 一次提交；它不包含独立 Memory/SN physical commit，
  也不声称完整 MOESI/Owned。clean ReadUnique 的 Retry modifier 另将 shared Request-Retry/P-Credit
  contract 组合进同一 RN/Home participant：`RetryAck` 保留原请求，`PCrdGrant` 按
  `(Home, PCrdType)` 池化并在 Home 预留真实槽，自动 credited reissue 后才进入既有 SnpUnique lifecycle；
  当前 coherent modifier 只覆盖一次 Retry 后成功，不包含取消或公平选择。这些 lifecycle 分别登记为构造期 feature；dirty-unique 依赖 clean ReadUnique，而独立
  ReadNotSharedDirty feature 无此依赖。no-SD policy preset 组合二者。dirty-data 扩展增加
  Snoopee→Home DAT flow。flow projector 只投影
  当前合同及依赖，新增 feature 不会给旧网络制造无关 gap。Snoopee role 已支持
  显式有限 peer set，成员 capability、SNP 去程和 RSP 回程逐一闭合；空 peer set 是有效显式声明，漏绑仍报告
  role gap。`ChiCoherenceSession.from_resolved()` 已把 closed role set、component singleton NodeID、
  requester/Snoopee authority 与启用 feature 带入 packet-level runtime registry；
  `ChiCoherenceNetworkSession` 已让这些 participant emission 经 resolved network 自动运输和交付，并以
  显式 pending batch 保存受背压的 fanout。`SC→ReadUnique→UC→local write→UD` 与
  clean/shared-dirty-peer `SC→CleanUnique→UC` 已进入 participant lifecycle；集合从 coherence domain 自动
  派生。Home attach/canonical binder 已用独立 `FullLineBackingCore` 落地；`MakeUnique`、clean `Evict`、
  自动 victim/writeback scheduling、一般 `SD` 生成与 MOESI
  Owned lifecycle、真实 snoop filter、独立 HN→SN protocol commit 及更一般的 transient/hazard 仍未进入该
  slice。两级 XP 的公开
  happy-path 场景验证六条 REQ/DAT hop、L-Credit、有限 router FIFO、TgtID route 和跨组件原子 admission；
  另有四 XP 的 2×2 square-mesh 公开场景让 clean `ReadUnique` 的 REQ/SNP/RSP/DAT/CompAck 覆盖
  方环四边，并展示 `I/SC/UC` 与 Home directory 的稳定状态闭合；
  clean ReadUnique Retry 已在同一个 XP witness 中让两次 REQ、RetryAck、PCrdGrant、SNP/RSP、
  CompData/CompAck 全部经 resolved route 自动推进；direct ReadNoSnp retry/cancel witness 继续验证
  `PCrdReturn`。aligned full-DAT-width direct read 已通过 `ChiAddressHomeNode` 委派给协议无关
  `AddressTarget`；authority 内 decode/access failure 已沿同一 resolved XP topology 返回
  `CompData_I(NDERR)` 并闭合无有效数据的 transaction result。coherent `ReadUnique` 的独立 NDERR
  modifier 也已用三 packet XP witness 闭合预侦听错误完成：无 SNP，Requester 原 cache、peer、directory
  与 backing 不变，DBID/同址 reservation 由 `CompAck` 退休。coherent Home 则使用支持延迟 line commit 的
  `FullLineBackingCore`，不把
  `AddressTarget` 扩张成 prepare/commit API。功能缺口
  仍包括同 Home/type 多 waiter 的具名选择/公平性合同、multi-packet DAT、narrow completion、coherent
  DERR、post-snoop/组合错误路径、可推进的
  Sensor target、动态 address→Home 选择与更完整的多节点 coherence；NodeID ownership 和所需 feature 的
  route/capability closure 已在 CHI family resolver 中落地。这里的 opcode/field 与 transaction-local
  correlation、participant cache/directory/backing，以及跨节点 authority/invariant 分别属于表示/完整逻辑
  接口、VirtualDut 与 SystemProtocol 三种投影；`TransportLink` 仍只负责单向 hop 的运输。
- 协议定义不拥有 `attach(vdut)`。VirtualDut 定义 attachment SPI 和本地 binding，具体 AMBA 转换位于
  `protocol_model.integrations.attachments.amba`；对应模块构造位于
  `protocol_model.integrations.recipes.amba`。完整逻辑接口由 SystemProtocol 连接 `InterfacePort`；展开单向
  transport hop 时则连接 `TransportPort`。
- ready-valid 是 observation encoding；需要一个点到点数据协议时，由具体 EventSchema 和
  InterfaceEventKind 组合，不恢复旧的顶层 ready-valid 包。
- four-phase REQ/ACK 同样是 observation encoding；当前提供独立 token InterfaceProtocol 作为最小承载，也可将
  observer 绑定到已有 event schema。two-phase toggle、独立 reset recovery 和 system CDC closure 尚待场景驱动。
- `protocol_model.protocols.tilelink` 已建立家族命名空间，但尚无具体 builder/observer。未来 TL-UL/TL-UH/TL-C
  用于检验 multibeat、source/sink ID、denied/corrupt 和 coherence 作用域。

## 文档与运行产物

- 稳定概念、视图和职责边界维护在 `docs/architecture/`，入口是
  [架构说明索引](README.md)。
- [技术路线](technical-route/README.md)按构造依赖、判定作用域和表示/运输解释概念，不单独维护第二套定义。
- 本页维护当前实现状态；[根路线图](../../ROADMAP.md)维护长期能力方向，具体施工边界放在对应实施案中。
- 一次运行的 trace、图和报告进入调用方选择的 run root；省略路径时仍可使用临时默认 `out/`。
- 从 protocol record 生成的临时参考文档进入 scratch 或临时目录，不固定依赖仓库内的 `out/doc-build/`。
- 长期示例需要由具名脚本显式发布到 `docs/examples/` 或 `showcase/generated/`；普通测试不写入发布树。
