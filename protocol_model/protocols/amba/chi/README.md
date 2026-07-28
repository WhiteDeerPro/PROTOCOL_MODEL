# CHI family boundary

CHI 是一个跨越多张工程视图的协议体系。这个目录是 CHI 具体资产的家族入口，不宣称整个 CHI 属于
`InterfaceProtocol`，也不把 flit、Link Credit、NodeID 和 coherence ledger 塞入同一个 session。

## 目标归属

首个 Issue H 场景需要哪些切面，就逐步建立哪些子包：

```text
chi/
└── issue_h/
    ├── representation/   typed protocol message、named logical-field record、
    │                     NetworkPacket 与 ProtocolFlit；packed bit layout 后续扩展，
    │                     physical phit/pin lowering 归 observation/external integration
    ├── transport/        单向 TX→RX TransportLink、共享 activation、分 channel L-Credit/FIFO
    ├── interface/        transaction-local TxnID/DBID/Retry/P-Credit lifecycle
    ├── participants/     RN/Home 的本地状态与行为、router forwarding facet
    └── system/           resolved topology runtime、NodeID/flow/capability closure、
                          read/retry/coherence composition 与跨 participant monitor
```

| CHI 事实 | 工程职责 |
|---|---|
| operation 由一组相关 protocol messages 完成 | transaction lifecycle / correlation |
| message 被加上网络身份并 packetize | representation codec |
| packet 通过 flit 占用相邻设备间的单向连接 | transport contract / `TransportLink` |
| RN-I、HN、SN 等逻辑角色及其本地行为 | participant profile + VirtualDut backend |
| NodeID 唯一性、address→home、跨节点 coherence/progress | SystemProtocol contracts 与 monitors |

P-Credit/Retry 表示 completer 对 protocol transaction resource 的接纳保证；L-Credit 表示相邻 receiver
允许 transmitter 发送一个 flit。两者都可以复用 resource/lease 语义，但拥有不同的获得、消费和释放条件。

## 第一个可执行边界

当前首个闭合实例是受限的 direct-Home `ReadNoSnp` 路径。它将几个可分别检查的对象组合起来：

1. `representation` 提供 `ReadNoSnp`、`CompData`、typed `RespErr` 与当前 REQ/RSP/DAT `LCrdReturn` form；
2. `transport` 提供整条有向 link 共享的 activation state、REQ/DAT 各自的 L-Credit，以及有限 TX/RX
   参考端点；
3. `interface` 的 direct ledger 以 `(Requester NodeID, TxnID)` 关联请求和完成；
4. `participants` 的 direct Home 使用有限请求 FIFO 和显式 service 动作生成一个 `CompData`；
5. `ChiBehaviorFacet` 把 transaction participant 与 forwarding behavior 组合到具体 VirtualDut，并通过
   NodeID、flow 和 capability closure 形成 `ResolvedChiSystem`；
6. `ChiReadNoSnpSystemSession` 从这份构造期证据打开运行态，再组合 transaction、participant 与 transport
   状态。

一个执行见证使用 RN→Home 的 REQ link 和 Home→RN 的独立 DAT link，覆盖 activation、下一帧生效的
L-Credit、receiver reservation、capture/drain、Home service 和 outstanding 释放。两条 link 可以使用同一个
参考时钟推进，但各自拥有方向独立的 activation 与 credit 状态。这是点对点 fixture，
不是 CHI network 的固定拓扑。

在此基础上，`SystemProtocol.connections` 已可在同一 canonical topology 中声明
`DirectedTransportConnection`。Elaboration 校验 `TransportPort` 的方向、family 与唯一所有权，再派生
`ResolvedTransportPlan`。`ChiTransportNetworkSession` 消费这份 plan 和调用方注册的有限
store-and-forward routers，因此不内置 RN→router→Home、ring 或 mesh 形状。当前公开 read witness
由调用方放置两级 XP，正向 REQ 与反向 DAT 各经过三条 hop；它证明 topology 可以扩展，但不把该形状
固化为核心网络。

network session 统一持有 connection、router 与按 `connection + channel` 记录的 lineage 状态。一条
directed connection 可以同时承载 REQ/RSP/DAT，却只拥有一个 Link activation authority；各 channel
保留独立 FIFO、receiver reservation 和 L-Credit。它把 capture→router 和 router
service→downstream enqueue 各作为一项原子候选提交；下游拒绝时保留上游 capture 或 router FIFO
原状态。有限 router 仍按 `channel + TgtID` 选择精确 NodeID route，不解读 opcode 或改写 typed
payload；Resource Plane 与运行 lineage 保留在 hop/router runtime，不写入 Network packet。

受限的 `ChiReadNoSnpSystemSession` 在这层显式 transport runtime 之上提供一个参考调度器。外部只提交
`ChiSubmitRead`；session 根据 participant 绑定的端口从 `ResolvedTransportPlan` 解析首末 hop，并沿
router 的 `channel + TgtID` route 闭合 requester→Home 和 Home→requester 路径。每次 advance 只提交一个
轮转选择的 microstep。Requester issue+REQ enqueue、REQ drain+Home accept、Home service+DAT enqueue、
DAT drain+Requester completion 都作为跨组件原子候选；被背压的候选不阻止其他路径继续推进。Home 接收的
request lineage 按 transaction identity 保留到 CompData 成功入网，因此不再依赖场景局部变量保存因果关系。

这个 profile 固定 `Order=00`、`ExpCompAck=0`，接受初始 `AllowRetry=1/PCrdType=0` 请求，并要求读取落在一个
DAT payload chunk 内。address-backed Home 会把 authority 内的 decode/access failure 映射为
`CompData_I(NDERR)`；transaction 正常结束，但结果不把线上零占位当作有效 read data。该 modifier 复用
原 REQ/DAT flow。RSP transport 现已覆盖 `RetryAck`、`PCrdGrant` 和 hop-local `RspLCrdReturn`；一个 sibling
retry lifecycle 可执行 `RetryAck → P-Credit → AllowRetry=0 重发 → CompData`，并允许 Requester 先收到
`PCrdGrant`。P-Credit 按 Home 与 `PCrdType` 进入可分配池，不绑定 `PCrdGrant.TxnID`；Home 发送 Grant 时预留
一个真实接纳槽。当前 retry profile 复用原 TxnID、使用 RP0；收到 RetryAck 和匹配 P-Credit 后，也可取消请求，
让 `PCrdReturn` 作为 REQ packet 沿 Requester→Home 路径归还 credit，并释放 Home 的预留槽。多个 waiter 当前
仍按插入顺序选择，尚未形成具名、可配置的选择/公平性合同。

当前 `ChiCoherenceNetworkSession` 已把 participant lifecycle 与 resolved topology runtime 组合起来。
clean `ReadShared`、clean `ReadUnique`、dirty unique responsibility transfer，以及受限的 MESI
`ReadNotSharedDirty` 路径都能沿调用方构造的 XP/Link topology 自动运输和交付。clean ReadUnique 另有
独立 Retry modifier，可自动执行
`ReadUnique→RetryAck→PCrdGrant→AllowRetry=0 重发→SnpUnique→CompData→CompAck`。它与 direct
ReadNoSnp retry 共用 family-local Request-Retry/P-Credit 合同；Home 拒绝阶段不建立 coherence pending、
不分配 Snoop/DBID、不改 directory/backing，Grant 才按 `(Requester, PCrdType)` 预留真实 transaction
slot。当前 coherent modifier 只覆盖一次 Retry 后成功，不包含取消或多 waiter fairness。no-SD 路径为：

```text
ReadNotSharedDirty
  → SnpNotSharedDirty(DoNotGoToSD=1)
  → SnpRespData_SC_PD
  → Home pending 接管 dirty data / responsibility
  → CompData_SC
  → CompAck
  → Home 提交 backing data 与 directory
```

这条 no-SD 路径使原 dirty unique holder 与 requester 最终都成为 clean shared holder；它没有引入
MOESI 的 `SD`/Owned 状态。该 MESI slice 可以独立验收；未加入 Owned 只限制 shared-dirty 状态范围，
不撤销这条 lifecycle 的 closure。DCT（Direct Cache Transfer）是另一条可选 forwarding lifecycle：
peer RN 直接向 requester 返回数据并另行与 Home 完成 correlation，clean-state path 也可采用，不要求
先有 Owned。这里需要同时保留三种投影：typed message 与 transaction correlation 属于
协议表示及完整逻辑接口范围，RN cache/Home directory/pending 属于 participant VirtualDut，NodeID/Home
authority、feature/flow closure 与稳定点 invariant 属于 SystemProtocol。`TransportLink` 只搬运一条
transmitter→receiver hop 上的 flit，不解释 coherence opcode；`InterfaceProtocol` 则是项目中“完整逻辑
接口合同”的作用域名称，不是 CHI 规范 Link layer 的别名。

clean ReadUnique 还有一个独立的 pre-snoop NDERR modifier：
`ReadUnique→CompData_I(NDERR)→CompAck` 只分配 DBID，不发 SNP；Requester 保持原 `I`/`SC` 和 payload，
Home 在 Ack 后只释放 pending/同址 reservation，directory/backing 不变。它已有经单 XP 的三 packet
witness。Retry 与 NDERR feature 现可同时选择：被拒绝的初始 request 不产生 Snoop；direct 双 Requester
witness 证明 Requester 在 `WAIT_RETRY_CREDIT` 期间可被另一笔同址 `SnpUnique` 失效而保留 retry
correlation，等该 transaction 退休后再以 P-Credit 重发，并由上述 pre-Snoop policy 返回
`CompData_I(NDERR)`。单 XP 另闭合不含实际 Snoop packet 的
`RetryAck/PCrdGrant→credited reissue→CompData_I(NDERR)` transport 路径。这里没有把 Snoop 归因给
被拒绝的 request，也不声称同一 accepted request 已发出 Snoop 后的 error 或 DERR。

当前 Home 固定选择“吸收 PassDirty、返回 `CompData_SC`、在 `CompAck` 后提交 backing/directory”这一种
规范允许的 no-SD 结果；它没有覆盖所有可选 Home policy。`SC` holder 已可通过
`CleanUnique→UC→local write→UD` 保留本地数据完成权限升级，也可通过
`ReadUnique→UC→local write→UD` 走需要返回数据的路径。clean `Evict` 已闭合
`UC/UCE/SC→I→Evict→Comp_I` 的 REQ/RSP-only lifecycle、条件 directory removal 和最小 topology
witness。它的独立 Retry modifier 复用同一 Request-Retry/P-Credit ledger，并闭合
`Evict→RetryAck→PCrdGrant→AllowRetry=0 重发→Comp_I` 的五 packet resolved witness。初始拒绝不改变
directory/backing、不分配 DBID/Snoop；system composition 对 RetryAck 与 P-Credit 使用一次性 exact packet
evidence，避免伪造或 replay response 驱动 RN 状态。独立的 `MakeUnique(0x0C)` 切片也已闭合：REQ
不携带写数据，submit API 将 RN-local
512-bit store intent 保存在 requester pending state；Home 用 `SnpMakeInvalid(0x0A)` 使任意当前已表示的
peer state 进入 `I`，只接收 `SnpResp_I` 且不接收 DAT。`Comp_UC` 到达 requester 时原子覆盖/安装 intent
为 `UD` 并产生 `CompAck`；Home 到 Ack 才提交 unique owner，backing payload/version 保持不变。规范描述
`I/SC/SD` 为 expected initial requester state；当前模型还允许 `UC/UCE`，拒绝 `UD`。该 feature 独立于
CleanUnique，已由 dirty-peer 五 packet resolved witness 闭合 REQ/SNP/SnpResp/Comp/CompAck 与零 DAT。
由于它可产生 `UD`，与 clean ReadUnique/CleanUnique base 组合时当前 profile 分别要求相应
dirty-unique/shared-dirty modifier；与 MESI ReadNotSharedDirty 的双向 same-line transient 尚未闭合，
当前 construction 拒绝同时选择两者。这些都是阶段 closure，不是协议永久禁配。
clean `WriteEvictFull(0x15)` 的首个切片也已闭合
`UC→WriteEvictFull(CAH=0)→CompDBIDResp→CopyBackWrData_UC→I`：Home 将 full-line clean data
保存在独立 Snoop-domain residency，directory 只在 DAT 到达后释放 owner，reference backing
payload/version 不变。该三包 REQ/RSP/DAT 路径没有 SNP 或显式 CompAck，并使用独立 exact packet
evidence 区分原 TxnID 与 Home DBID。pre-DBID invalidating Snoop 已可把 pending outcome 从
`LIVE_UC` 转为 `CANCELED_I`，保留 correlation 后以零 data/BE 的 `CopyBackWrData_I` 退休；Home 不
覆盖新 directory owner、backing 或 clean residency。当前 retain policy 是 fixed-resident sparse
cache；容量、替换与自动 victim 是可选 Home/Cache VirtualDut policy。`CAH=1`、post-DBID Snoop、
Retry/error 与级联 eviction 则是独立 CHI lifecycle/profile 扩展。
`WriteEvictOrEvict(0x42, CAH=0)` 的双 outcome base 也已闭合。Requester 可从 resident `UC` 或
clean `SC` 发起，并以 `LikelyShared` 区分；Home 的显式 policy 可以选择
`CompDBIDResp→CopyBackWrData_{UC,SC}` data outcome，或 `Comp_I→CompAck` no-data outcome。两条路径
都使 requester 进入 `I` 并只移除其 directory authority；前者安装 Snoop-domain clean residency，
后者不搬运数据。四种 `UC/SC × data/no-data` resolved witness 都保持 reference backing
payload/version 不变。该能力是受限模型 profile，不代表完整 CHI allocation/replacement policy；
Home response 到达前的同址 invalidating Snoop 也已闭合：RN 保留原 REQ/`LikelyShared`，把当前
outcome 从 `LIVE_UC/LIVE_SC` 改为无 payload 的 `CANCELED_I`；迟到 `CompDBIDResp` 产生零
data/BE 的 `CopyBackWrData_I`，迟到 `Comp` 产生 `CompAck_I`。system-derived stale-holder
admission 使两条分支都只退休旧 correlation，不覆盖新 owner、backing 或 clean residency。
direct 双 Requester witness 覆盖 `UC/SC × data/no-data`；当前 scalar-requester resolver 尚不能构造
同一 resolved scope 内“旧 RN 发 WEOE、新 RN 发 CleanUnique”的取消 witness。post-response/其他
Snoop phase、Retry/error、CAH=1 和容量驱动 outcome 尚未闭合。

### 当前边界如何分类

这些边界不合并成一条“CHI 网络完整度”：

| 维度 | 当前边界与影响 |
|---|---|
| CHI lifecycle/profile 覆盖 | coherent DERR、post-Snoop error、MakeUnique Retry/error/MTE Update/partial write、Retry cancel/multi-waiter，以及 WEOE response 前 invalidating-Snoop 之外的 same-line transient 尚未闭合；它们限制可执行 transaction 组合 |
| representation / packetization | opcode/conditional-field encoding inventory 与 packed layout 属于表示；multi-packet DAT 的分片字段属于表示，split/reassembly、缺失/重复/乱序处理及 terminal retirement 属于 transaction/session。可执行 opcode 还需要 lifecycle、capability/flow、状态效应与 witness |
| observation / external integration | physical phit/lane、raw pin、RTL adapter/conformance 是观察和接入工作，不计作 CHI lifecycle 功能缺口；CDC/异步采样是跨协议的通用时间方法议题 |
| participant / VirtualDut policy | victim/LRU 与自动 replacement/writeback 是 Cache policy；snoop filter 是 Home/ICN 的 cache-presence/选靶结构，当前 exact directory holder set 是 reference oracle，带容量、更新和误判行为的 filter 才是可选 backend policy |
| system construction | dynamic multi-Home/SAM（System Address Map）remap 属于 address→Home authority 与 runtime 选择；需要观察独立 memory commit 时，HN→SN 需要另建 SN participant、flow 和 system witness |
| coherence state/policy | 当前 no-SD MESI slice 独立成立；一般 `SD`/Owned 是可选 shared-dirty 状态扩展 |
| forwarding/DCT lifecycle | forwarding Snoop、peer→requester DAT 与 Home correlation 是可选 CHI transaction/capability，不要求 `SD`/Owned |
| verification property | CHI channel-dependency/forward-progress 规则是实现合同；waiter selection、公平性、wait-for 和 deadlock/livelock verdict 则属于 system/scenario property，规范不要求通用 deadlock detector/unlocker。watchdog 可报无进展或触发场景级 recovery，但不是无死锁证明；有界 scheduler budget 耗尽仍只给出 inconclusive |

Participant facet、identity/capability resolver 和 scheduler 仍是 CHI family 实现，尚未并入通用
`SystemSession` action loop；这是 runtime 泛化边界，也不是当前 CHI network slice 的功能否定。

后续扩展继续以可执行 lifecycle 为单位增加，不把此处建议固化成永久顺序。
`WriteEvictOrEvict` response 前的 same-line invalidating-Snoop outcome/correlation 已闭合；下一决策点
比较 `WriteEvictFull(CAH=1)` 所需的 cached-CAH/hidden-copy provenance、
post-response-Snoop/Retry/error modifier、deliberate dirty invalidate 与其他未闭合 operation。若下一场景首先受
并发资源阻塞，则先闭合同一 Home/type 下多个 waiter 的具名选择、释放与公平性 witness。
`PCrdGrant`、`RetryAck` 仍走 Home→Requester 的 RSP 路径；`PCrdReturn` 根据 CHI Issue H B2.5.6 走
Requester→Home 的 REQ 路径，router 继续只按 `channel + TgtID` 透明转发。NodeID ownership 与首条
single-scope address/Home/domain authority 已由 system construction 闭合；dynamic multi-Home/SAM 选择和
动态 address remap 继续由 SystemProtocol authority/construction 扩展。MOESI shared-dirty authority
则由 participant policy 与 system monitor 共同扩展；两者都不作为局部 `TransportLink` 的占位字段。

架构依据与作用域说明见 `docs/architecture/communication-scope-and-transport.md` 和
`docs/architecture/ace-chi-communication-scopes.md`。
