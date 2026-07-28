# 实施路线与阶段边界

[返回架构地图](README.md) · [查看总览图](overview.svg) · [项目 Roadmap](../../../ROADMAP.md)

这条路线按“下一个真实场景缺少什么”递归补共享能力，而不是把工程误画成唯一的上下层，或按协议名称与
软件包数量推进。三张视图见[通信建模的三张视图](../communication-scope-and-transport.md)。

本页不是 CHI 规范目录的镜像，也不是不可复审的绝对优先级。每个协议切片进入施工前分别记录四类依据：

1. **协议要求**：固定到官方规范的 document issue、章节与适用条件；不同 issue 或 errata 有差异时显式裁决，
   不从二手流程图补出规范结论；
2. **实现事实**：由当前代码、canonical implementation status 和定向回归证明，只说明已执行的 profile；
3. **架构/阶段选择**：说明为何先取某个合法子集及其非目标，不把 reference policy 写成所有实现必须遵守；
4. **发现线索或待验证假设**：review、教材、实现手册和网络资料可以帮助找到问题，但在官方规范核对前不提升为
   requirement。

因此“按路线推进”表示按依赖和证据成熟度选择下一小片，不表示追求未经限定的逐条 spec coverage。合法 witness
证明该输入和边界可执行，负例证明某条已声明规则生效；二者都不单独构成整份规范的一致性证明。

本页只给 CHI lifecycle/profile 切片排直接先后。opcode encoding inventory 属于表示覆盖，而可执行 opcode
还要有 lifecycle/capability/state/witness；multi-packet DAT 同时扩展分片表示与 transaction/session 聚合；
dynamic multi-Home/SAM、独立 HN→SN downstream transaction/commit、victim/LRU、`SD`/Owned、
forwarding/DCT、deadlock/fairness analyzer 以及 RTL/pin/CDC 分属 system construction、VirtualDut policy、
coherence state、可选 CHI lifecycle、验证 property 和观察/接入方法。未排进当前主线不等于否定现有
single-packet MESI slice 或 resolved network 的可用性。

## 当前已经打通的一条小型完整路径

```text
基础语义
  → 通用 pattern
  → AXI/APB/AHB InterfaceProtocol
  → InterfaceAttachment + binding
  → AddressSpace / AddressFabric VirtualDut
  → point-to-point / bridge-chain / single-ingress fabric / scheduled N×M crossbar SystemProtocol
  → 同步执行、trace、causality、artifact
```

它已经能回答：单个 interface connection 上发生的事务是否合法；一个 APB endpoint 如何执行地址访问；一个简单 fabric
如何解码、转发并归还 completion；多个具体模块如何组成可执行系统。

## 依赖驱动的推进顺序

当前瓶颈不是可声明的协议名称数量，也不再是首个 serial bridge 或 CHI credit hop。统一 bridge、最小
SystemProtocol、CHI REQ/RSP/DAT transport 和 direct read/retry lifecycle 已提供实验平台；下一步需要让
协议资源、participant、系统身份与通用 runtime 的边界继续闭合。

### C1 · 当前主线：从 participant/network 闭环到一致性 authority

第一条 participant→本地行为路径已经闭合：`ChiAddressHomeNode` 将 aligned full-DAT-width `ReadNoSnp`
转换成 `AddressRead`，并让 `AddressTarget` 独占本地 memory state。`DECODE_ERROR/ACCESS_ERROR` 现会沿
原 DAT return route 完成 `CompData_I(NDERR)`；Requester 正常退休 transaction，但不把线上零占位暴露为
有效 read data。该能力以 direct-read modifier 闭合 participant capability，并由 resolved runtime gate
启用，未增加 error 专用 flow。
`PCrdReturn`、NodeID ownership、feature-flow closure 和 clean `ReadShared/ReadUnique` participant 也已落地。当前
`ChiCoherenceNetworkSession` 可把这些 participant 与调用方构造的 XP/Link topology 组合起来，
逐小步闭合 REQ、SNP、RSP、DAT 和 CompAck。第一条 dirty-unique 纵向路径也已闭合：
`UC→本地写→UD→SnpRespData_I_PD→CompData_UD_PD`，最新数据和写回责任可经同一网络转移。
MESI no-SD 路径也已闭合：
`ReadNotSharedDirty→SnpNotSharedDirty→SnpRespData_SC_PD→Home pending 接管→CompData_SC→CompAck
→Home backing/directory commit`；它把 dirty unique line 收束为两个 clean shared copy，不引入 `SD`。
`SC→ReadUnique→UC→local write→UD` 的重取数据式 upgrade 也已闭合；clean-peer
`SC→CleanUnique→SnpCleanInvalid→Comp_UC→UC` 现可保留 requester 已有数据，不再为取得权限重取整行。
受限 shared-dirty 扩展也已闭合：预置的唯一
`SD`/`shared_dirty_owner` 经 `SnpCleanInvalid→SnpRespData_I_PD→I` 把最新数据交给 Home pending，
Home 在 completion 前准备 line-local backing write，保持同址 reservation 到 `CompAck`，再以 versioned
commit 与 directory transition 提交 requester 为 unique owner。Home payload 已从 directory entry 拆入
协议中立 `FullLineBackingCore`，公开 attach/canonical binder 也已落地。这里没有建立一般 `SD`
生成/维持 policy，也没有把 reference update 冒充独立 Memory/SN downstream transaction/commit。
第一条 coherence Retry 组合也已闭合：
`ReadUnique→RetryAck→PCrdGrant→AllowRetry=0 重发→SnpUnique→CompData→CompAck` 复用 family-local
Request-Retry/P-Credit 合同和原有 ReadUnique lifecycle。Retry 阶段不建立 Home coherence pending、
不分配 Snoop/DBID、不改 directory/backing；Grant 预留真实 transaction slot，network scheduler 自动推进
credit 与重发。一次 Retry 后成功是独立基线；下文另记录已闭合的 Retry/Snoop/pre-Snoop-NDERR 窄组合。
cancel 与多 waiter fairness 仍未实现。
第一条 construction authority
切片现已闭合：CHI 合同引用通用 `AddressClaim`，为本次 feature scope 选择唯一 Home。每个 requester
从 coherence-domain membership 派生 `eligible Snoopees = members - requester`；clean Shared/Unique、
CleanUnique、dirty WriteBack、WriteEvictFull base 与 CopyAtHome modifier 可声明有限 requester set，
其 Snoopee authority 取各 requester eligible-peer 的并集。NodeID、逐成员 capability 与
REQ/SNP/RSP/DAT flow 随后使用同一派生结果闭合。Home directory 仍只选择一笔事务的实际 holder，不取代
静态 domain authority。

第一条 coherent error 切片也已闭合：Home 在 admission 后、Snoop 前由显式 policy 选择
`ReadUnique→CompData_I(NDERR)→CompAck`，不发 SNP；Requester 保持原 `I`/`SC` 与 payload，Home 保持
directory/backing/Snoop ID，只把 DBID 和同址 reservation 保留到 Ack。独立 modifier 复用 base flow，
并由单 XP 三 packet witness 证明。

第一条 same-line progress 切片也已闭合：pending `ReadUnique` 的 RN 可以接纳同址 `SnpUnique`，以
`I/SC→I` 响应而保留原 pending/Retry correlation，随后由自己的 `CompData` 重新安装 `UC`。Home 仍以
line reservation 串行化同址请求；被 block 的 endpoint packet 留在网络，`CompAck` 释放 reservation 后由
family scheduler 自动 replay。`project_progress()` 与 `project_wakeups()` 提供 family-local、只读的
held/wait/release evidence，不把一次资源释放夸大成 packet 已接纳或 deadlock verdict。

第二条 same-line progress 切片也已闭合：`CleanUnique` 可由 `I` 或 resident `SC` 发起；pending
`CleanUnique` 收到同址 `SnpUnique` 或 `SnpCleanInvalid` 时先响应并失效为 `I`，但保留原 transaction
correlation。后续无数据 `Comp_UC` 在 full-line payload 仍在时形成 `UC`，payload 已不存在时形成
`UCE`；`UCE` 表示“拥有 unique authority、尚无有效 payload”，不能保存 cache-line data，第一次 full-line
local write 原子安装 payload 并进入 `UD`。direct `ChiCoherenceSession` 的双 Requester witness 已证明两笔
`CleanUnique` 可由 Home reservation 串行完成；同构 CleanUnique requester set 也已能闭合 resolved route，
但这不等于异构 per-feature requester scope 或一般多 Requester construction。

第三条 same-line progress 切片现已闭合 `WriteBackFull` 的 Snoop cancel：RN pending 显式区分
`LIVE_UD` 与 `CANCELED_I`；前者收到同址 `SnpUnique`/`SnpCleanInvalid` 后把 dirty payload 通过
`SnpRespData_I_PD` 交出，进入无 payload 的 `CANCELED_I`，但保留原 WriteBack correlation。随后
`CompDBIDResp` 使 RN 发送 data/byte-enable 均为零的 `CopyBackWrData_I` 并退休。若原 REQ 延迟到
CleanUnique 已提交新 owner 后才到达 Home，只有组合 session 能从同一 source/TxnID/request 的 RN
`CANCELED_I` 和 `I` line 派生 `SNOOP_CANCELED` admission；这不是 wire field，独立 Home 也不从一笔
non-owner REQ 自行推断。Home 接纳时冻结当前 directory snapshot 与 backing version，收到
`CopyBackWrData_I` 时确认二者未变，只释放 DBID，不覆盖新 backing/owner。direct 双 Requester witness 已
闭合 `CleanUnique + delayed WriteBack`。normal 与 canceled outcome 现共用两阶段 exact packet evidence：
Home-produced `CompDBIDResp` 与 RN-produced `CopyBackWrData` 分别只允许成功消费一次，伪造或 replay
不推进 participant state。同时启用 CleanUnique 与 dirty WriteBack 的双 Requester resolved XP witness 已闭合这一窄组合；
异构 per-feature requester scope 和一般多 Requester construction 仍未闭合。

第一条 Retry/Snoop/error 窄组合也已闭合。被 `RetryAck` 拒绝的初始 `ReadUnique` 不会产生 Snoop；
Requester 在 `WAIT_RETRY_CREDIT` 期间可以响应另一笔同址 transaction 引发的 `SnpUnique`，由
`SC→I` 而不丢失原 TxnID/retry correlation。独立 transaction 完成并释放 Home line reservation 后，
P-Credit 重发被接纳，再由既有 pre-Snoop policy 返回 `CompData_I(NDERR)`；Requester 保持 Snoop 后的
`I`，不会恢复旧 payload，Home 也不会回滚新 owner 或 backing。组合复用现有 Retry phase、cache state、
feature/capability 与 flow 的并集，没有新增 opcode、组合 feature 或 cancel state。direct 双 Requester
witness 负责同址交错，单 XP witness 负责
`RetryAck/PCrdGrant→credited reissue→CompData_I(NDERR)` 的 topology closure；DERR、同一 accepted
request 已发出 Snoop 后的 error 与任意到达次序所需的 accepted-but-waiting queue 仍未闭合。

第一条 clean eviction 切片也已闭合。RN 只从 `UC/UCE/SC` 发起，先原子失效为无 payload 的 `I` 再发送
`Evict`；Home 将其作为 hint，只条件删除仍匹配 source 的 clean owner/sharer，stale/non-holder 或目录明确
标记为 shared-dirty responsibility 的请求 no-op，
随后返回 `Comp_I`。该 completion 不分配 DBID lease、不等待 `CompAck`，directory update 也不修改
backing payload/version。packet-delivery session 保存 Home-produced completion evidence，拒绝 early/forged
completion；pending Evict 遇同址 Snoop 返回 `SnpResp_I` 并保留 correlation。独立 feature 只声明
Requester→Home REQ 与 Home→Requester RSP，两 packet topology witness 不产生 SNP/DAT/CompAck。
自动 victim/LRU 与普通 dirty replacement 是可选 Cache VirtualDut policy；deliberate dirty invalidate 与
WriteEvict family 是独立 lifecycle/profile。它们没有并入 clean Evict base slice，也不是显式 Evict
transaction 可运行的前置条件；Request-Retry modifier 见下文独立切片。

第一条 `MakeUnique` 切片也已闭合。REQ `MakeUnique(0x0C)` 本身不携带数据；提交 API 另保存一份
RN-local 512-bit full-line store intent，它不是 wire payload。规范描述的 expected initial state 是
`I/SC/SD`；当前模型还允许已表示的 `UC/UCE`，并拒绝 `UD` 发起。Home 以
`SnpMakeInvalid(0x0A)` 失效实际 peer；peer 无论原来是 clean 还是 dirty
都进入 `I`，只返回 `SnpResp_I`，不发送 DAT，旧 dirty payload 被本阶段 profile 明确丢弃。Home 收齐
response 后返回 `Comp_UC`；requester 在接收 completion 的同一原子 transition 中覆盖安装 store intent、
进入 `UD` 并发出 `CompAck`。Home 的 DBID 与同址 reservation 保留到 Ack，随后只提交 requester 的 unique
directory authority，backing payload/version 不变。该 feature 独立声明 Requester/Home 以及可为空的
Snoopee finite-set role，闭合 REQ、SNP、SnpResp、Comp、CompAck 五类 flow，不依赖 CleanUnique；但因其结果可为 `UD`，与 clean
ReadUnique/CleanUnique base 组合时，当前 construction 分别要求 dirty-unique/shared-dirty modifier。
与 MESI ReadNotSharedDirty 的两个方向 same-line transient 尚未闭合，当前 construction 拒绝同时选择；
这些是阶段 dirty-policy closure，不是 CHI 永久禁配。当前 executable profile 固定
full-line、初始 `AllowRetry=1/PCrdType=0`、`TagOp=Invalid`、tagless（状态空间内没有 Dirty-tag
holder）、`TraceTag=0` 与 OK-only；引入 MTE Dirty tags 时需重新闭合 `TagOp` 和 snoop 选择。Retry、DERR/NDERR、
MTE Update 和 partial write 不在本 lifecycle/profile 中；multi-Home 另属 SystemProtocol
authority/construction。resolved dirty-peer witness 恰好运输
REQ、SNP、SnpResp、Comp、CompAck 五个 packet，并确认零 DAT。

第一条 clean `Evict` Request-Retry modifier 也已闭合：
`Evict→RetryAck→PCrdGrant→AllowRetry=0/匹配 PCrdType 重发→Comp_I`。RN 在首发前已经从
`UC/UCE/SC` 进入无 payload 的 `I`，Retry 期间保留 pending 与同一份 opcode-neutral retry entry；Home
拒绝阶段只登记 retry debt，不改 directory/backing/identifier allocator，也不建立 coherence pending 或
DBID。Grant 为 `(Requester, PCrdType)` 预留真实 transaction slot，并允许先于 RetryAck 到达；credited
Evict 原子消费 reservation 后才执行原有 matching-holder removal/stale no-op。packet-delivery state 对
Home 产生的 `RetryAck` 与 `PCrdGrant` 也保存并一次性消费完整 packet evidence，防止伪造或 replay
P-Credit；initial/credited REQ 另与 retained entry 的 current form/phase 核对，旧 initial REQ replay
在 Home mutation 前失败。resolved direct-topology witness 恰好运输两份 Evict REQ、RetryAck、PCrdGrant 和 `Comp_I`
五个 packet，零 SNP/DAT/CompAck。该 modifier 与 ReadUnique Retry 使用同一 Request-Retry ledger，但采用
独立 admission policy 与 feature gate；当前只证明一次 Retry 后成功，不包含 cancel 或多 waiter fairness。

第一条 clean `WriteEvictFull` base slice 现已闭合。Requester 只从已选中的 resident `UC` line 发起
`WriteEvictFull(MemAttr=1101, CAH=0)`，在收到 `CompDBIDResp` 前保留 payload；随后用 Home DBID 发出
full-line/full-BE 的 `CopyBackWrData_UC` 并原子进入 `I`。Home admission 冻结 directory snapshot 与
reference-backing version，精确 DAT 到达后才清除 unique owner，并把 clean payload 安装到单独的
Snoop-domain residency；backing 对象、payload 与 version 全程不变。该 feature 独立声明 REQ/RSP/DAT
三条 flow，resolved witness 恰好运输三包且没有 SNP 或显式 `CompAck`。canonical Home binder 可透传同一
协议无关 `CacheCore`，但当前 retain policy 仍是无容量/替换行为的 sparse state。`CAH=1` 由下文独立
modifier 闭合；Retry/error 和级联 eviction 是后续 lifecycle/profile，下游读取命中与 victim/LRU 是可选 Cache/Home
VirtualDut policy。它们没有并入该 WEF base slice，但不撤销显式选中 resident line 的三包 closure。
随后完成的 robustness slice 只开放 REQ 已发出、`CompDBIDResp` 前的 invalidating Snoop：RN 由
`LIVE_UC` 转为无 payload 的 `CANCELED_I`，保留 request/TxnID，并在晚到 DBID 后发送
`CopyBackWrData_I(Data=0, BE=0)`。system 从 exact RN 状态派生 stale-owner admission；Home 只校验并
退休 DBID，不安装 clean residency，也不改当前 directory/backing。

第一条 `WriteEvictOrEvict(CAH=0)` base slice 现已闭合。`WriteEvictOrEvict(0x42)` 固定
`MemAttr=1101/ExpCompAck=1`；`LikelyShared=0/1` 分别表示当前模型中的 resident `UC/SC`，RN 与 Home
都核对实际 permission/holder。显式 Home policy 在两个终态中选择：
`CompDBIDResp→CopyBackWrData_{UC,SC}` 搬运 full-line clean data 并安装 Snoop-domain residency，
或 `Comp_I→CompAck` 不搬运数据。两者都只删除 requester 的 directory authority、使其进入 `I`，并保持
reference backing payload/version 不变。feature closure 同时要求 REQ、Home→Requester RSP、
Requester→Home DAT 与 CompAck RSP 四条 flow；`UC/SC × data/no-data` 四个 resolved witness 各恰好运输
三个 packet，证明 operation-specific response/terminal evidence、route lineage 与最终 quiescence。这里的
policy 是当前模型的显式输入，不表示完整 CHI allocation/replacement policy。
随后完成的 robustness slice 允许 Home response 前的同址
`SnpUnique`/`SnpCleanInvalid`/`SnpMakeInvalid`：RN 保留原 REQ/`LikelyShared`，把 post-Snoop
outcome 记为 `CANCELED_I`；迟到 `CompDBIDResp`/`Comp` 分别以零载荷
`CopyBackWrData_I`/`CompAck_I` 退休。`UC/SC × data/no-data` direct 双 Requester witness 证明旧
correlation 不会覆盖 CleanUnique 建立的新 owner、backing 或 clean residency。

第一条 `WriteEvictFull(CAH=1)` modifier 现已闭合。它依赖 clean ReadUnique 与
`WriteEvictFull(CAH=0)` base：Home 只能在 clean `CompData_UC` 上返回 `CAH=1`，RN 将其缓存为
“自 Home 给出该标记后未修改此行”的 provenance；本地写或 line removal 会清除证据，RN 不能凭 resident
`UC` 自行伪造 CAH=1。CAH=1 不证明 Home 在后续 WEF 到达时仍有 copy。为得到首个确定、可审计的子集，
当前 Home 要求显式 `write_evict_full_current_copy_policy`，并采用 `CHECK_CURRENT_COPY` profile：只在
Snoop-domain `clean_residency` 仍有匹配 clean line 时允许
`Comp→CompAck_UC` no-data outcome；即使 copy 存在，policy 仍可选择
`CompDBIDResp→CopyBackWrData_UC` data outcome。两者都使 requester 进入 `I`、删除其 directory
authority，并保持 reference backing payload/version 不变。hidden clean copy 是 Home 的 Snoop-domain
state，不是 physical memory 或 topology-visible HN→SN commit。参数化 resolved witness 已通过公开 Home
recipe、真实 resolver/capability/flow closure 与 `ChiCoherenceNetworkSession` 分别执行正常
data/no-data 分支。

随后完成的窄 robustness slice 只处理 `WriteEvictFull(CAH=1)` 已发出、Home 尚未给出
`Comp`/`CompDBIDResp` 时到达的同址 invalidating Snoop：
`SnpUnique`、`SnpCleanInvalid` 或 `SnpMakeInvalid` 都使 RN 的当前 line/payload 与 cached CAH
provenance 清除并进入 `I`，但 pending 中冻结的原 REQ/TxnID/`CAH=1` 仍作为历史 correlation 保留，
不能被重写成当前 Home-copy 证明。Snoop response 完成后，data outcome 以
`CopyBackWrData_I(Data=0, BE=0)` 退休，no-data outcome 以 `CompAck_I` 退休。system-derived
`SNOOP_CANCELED` 只允许旧 CopyBack reservation 安全退休，不删除或覆盖期间建立的新
owner、reference backing 或 clean residency。

下一条 response 前 same-line slice 现已闭合 `SnpShared` 导致的 `UC→SC`。RN 返回
`SnpResp_SC`、保留 frozen WEF，并把 post-Snoop outcome 记录为 `LIVE_SC`；当前 CAH provenance 随
降级清除。`CAH={0,1}` 的 data 分支都要求 `CopyBackWrData_SC`，只有 CAH=1 modifier 可选择
no-data `Comp→CompAck_SC`。`CURRENT_SHARED_HOLDER` 由 system 根据 RN `LIVE_SC`、Home clean-sharer
directory 与 backing 一致性派生，不是 wire field。2RN+HN+XP resolved witness 在 RN 接收
`SnpShared` 并进入 `LIVE_SC` 后即把 WEF 送向 Home；ReadShared 的 directory transition 尚未提交时，
WEF 在 Home line resource 阻塞。五包 `ReadShared/SnpShared/SnpResp_SC/CompData_SC/CompAck`
完成后 runtime replay WEF，并走三包 data 或 no-data terminal；每个 case 恰好运输八个 endpoint packet。

CHI 功能不按 opcode 数量推进，而按“协议原子 + 可复用组合 + 必要基本状态”闭合。当前构造顺序如下：

| 顺序与功能 | 协议原子 | 可复用组合 | 新增基本状态或机制 | 当前阶段 |
|---|---|---|---|---|
| 0 · `ReadUnique` same-line | `ReadUnique`、`SnpUnique`、`SnpResp`、`CompData`、`CompAck` | pending/Retry correlation、Home line reservation、blocked packet replay | 无；复用 `I/SC/UC` | 已闭合 |
| 1 · `CleanUnique` / `UCE` | `CleanUnique`、`SnpCleanInvalid`/`SnpUnique`、`SnpResp`、`Comp_UC`、`CompAck` | 既有 CleanUnique fanout/聚合、同址 reservation、full-line local write | `UCE` 空数据 unique authority；pending CU 的 post-Snoop line state | 本切片已闭合 |
| 2 · WriteBack same-line/cancel outcome | `WriteBackFull`、invalidating Snoop、`CompDBIDResp`、post-Snoop `CopyBackWrData_I` | 既有 writeback DBID/correlation、dirty Snoop data transfer、directory/backing authority | RN `LIVE_UD/CANCELED_I`；system-derived stale-owner admission；Home snapshot/version guard 与零数据 retirement | 本切片已闭合 |
| 3 · Retry/Snoop/error 窄组合 | `RetryAck`、`PCrdGrant`、独立 transaction 的 SNP、`CompData_I(NDERR)`；DERR 原子待来源 | 既有 Retry ledger、same-line transient、coherence pending 与 pre-Snoop NDERR modifier | 无新增；正交组合 `ChiRequestRetryPhase × ChiCacheState` | 本切片已闭合 |
| 4 · clean `Evict` | `Evict`、`Comp_I`；无 DAT/CompAck/DBID lease | 复用 RN TxnID/line reservation、条件 directory removal、system return correlation 与 REQ/RSP topology | RN clean→I pending intent；Home-produced completion evidence；无新 cache 稳态 | 本切片已闭合 |
| 5 · `MakeUnique` | `MakeUnique`、`SnpMakeInvalid`、`SnpResp_I`、`Comp_UC`、`CompAck`；无 DAT | 复用失效 fanout、Home DBID/line reservation 与 full-line cache store | RN-local store intent；operation-specific correlation；`Comp_UC` 原子覆盖安装 `UD` | 本切片已闭合 |
| 6 · clean `Evict` Retry | `RetryAck`、`PCrdGrant`、credited `Evict`、`Comp_I` | 复用 opcode-neutral Retry ledger、Home capacity reservation、Evict exact completion 与 REQ/RSP scheduler | Evict-specific policy/feature gate；exact RetryAck/P-Credit delivery evidence；无新 cache 稳态 | 本切片已闭合 |
| 7 · clean `WriteEvictFull(CAH=0)` | `WriteEvictFull`、`CompDBIDResp`、`CopyBackWrData_UC`；无 SNP/显式 CompAck | 复用 RN TxnID/line reservation、Home DBID allocator、CopyBack DAT 与三通道 topology | 独立 clean residency authority；operation-specific RSP evidence；backing 不提交 | 本切片已闭合 |
| 8 · `WriteEvictFull` pre-DBID Snoop cancel | pending `WriteEvictFull`、`SnpUnique`/`SnpCleanInvalid`/`SnpMakeInvalid`、`CopyBackWrData_I` | 共用 `ChiRnCopyBackOutcome`、stale-owner admission、Home snapshot/version guard 与 exact RSP/DAT evidence | WEF `LIVE_UC/CANCELED_I`；cancel 只退休 DBID，不改 directory/backing/clean residency | 本切片已闭合 |
| 9 · `WriteEvictOrEvict(CAH=0)` 双 outcome | `WriteEvictOrEvict`、`CompDBIDResp`/`Comp`、`CopyBackWrData_{UC,SC}`/`CompAck`；无 SNP | 复用 CopyBack TxnID/DBID split、clean residency、Evict-style holder removal、CompAck 与 exact evidence | `LikelyShared` 对应 `UC/SC`；显式 Home outcome；四 flow、每 outcome 三 packet | 本切片已闭合 |
| 10 · `WriteEvictOrEvict` response 前 Snoop cancel | pending WEOE、`SnpUnique`/`SnpCleanInvalid`/`SnpMakeInvalid`、迟到 `CompDBIDResp`/`Comp`、`CopyBackWrData_I`/`CompAck_I` | 复用 invalidating-Snoop、`CANCELED_I`、system-derived stale-holder admission、Home snapshot/version guard 与既有 WEOE RSP/DAT/Ack evidence | 原 REQ/`LikelyShared` 与 post-Snoop outcome 分离；`UC/SC × data/no-data` direct 双 Requester witness | 本切片已闭合 |
| 11 · `WriteEvictFull(CAH=1)` | clean `ReadUnique→CompData_UC(CAH=1)` acquisition；`WriteEvictFull` 后由 Home 选择 `CompDBIDResp→CopyBackWrData_UC` 或 `Comp→CompAck_UC` | 复用 WEF base、clean residency、CompAck、feature/capability/flow closure 与统一 CopyBack phase evidence | RN unchanged-line provenance；显式 current-copy policy；WEF dual terminal | 本切片已闭合 |
| 12 · `WriteEvictFull(CAH=1)` response 前 invalidating Snoop | pending CAH=1 WEF、`SnpUnique`/`SnpCleanInvalid`/`SnpMakeInvalid`、随后到达的 `CompDBIDResp`/`Comp`、`CopyBackWrData_I(0/BE0)`/`CompAck_I` | 复用 `CANCELED_I`、typed CopyBack ledger、system-derived `SNOOP_CANCELED` 与 snapshot/version guard | frozen request CAH 历史和当前 cached provenance 分离；旧 reservation 不覆盖新 owner/backing/residency | 本窄切片已闭合 |
| 13 · `WriteEvictFull` response 前 `SnpShared` | pending WEF、`SnpShared→SnpResp_SC`、随后到达的 `CompDBIDResp`/`Comp`、`CopyBackWrData_SC`/`CompAck_SC` | 复用 clean ReadShared、typed CopyBack ledger、finite requester capability/flow closure 与 system-derived `CURRENT_SHARED_HOLDER` | WEF `LIVE_SC`；CAH={0,1} 共用 SC data 规则，CAH=1 另有 SC no-data ack；2RN+HN+XP 八包 witness | 本窄切片已闭合 |

对 [Arm IHI 0050 Issue H](https://developer.arm.com/documentation/ihi0050/h/) 的 CopyBack transaction、
CAH 与 requester state 规则进行切片级核对后，后续候选的证据成熟度并不相同：

| 候选 | 协议依据与当前依赖 | 路线判断 |
|---|---|---|
| `WriteEvictOrEvict` response 前 same-line invalidating Snoop | RN 以 `CANCELED_I` 保留原 REQ/TxnID，迟到 data/no-data Home outcome 分别产生零载荷 `CopyBackWrData_I`/`CompAck_I`；system exact evidence 只退休旧 correlation | 已闭合；不据此声称 post-response/非失效 Snoop、Retry/error 或动态 allocation policy |
| `WriteEvictFull` 正常终态与 response 前 Snoop | CAH=1 是 RN 未修改该行的 cached provenance，不证明 Home 当前仍有 copy；首个 profile 从 clean `CompData_UC(CAH=1)` 获取，并用显式 current-copy policy 收窄 no-data 结果。invalidating Snoop 形成 `I` terminal；`SnpShared` 形成 `LIVE_SC`，由 system 派生 `CURRENT_SHARED_HOLDER` | CAH=1 正常双终态、三种 invalidating-Snoop→`I`、以及 CAH={0,1} 的 SC data/CAH=1 SC no-data 规则已闭合 |
| CAH CopyBack 的其余 same-line/ordering | Home 发出 `Comp` 后须等 `CompAck`，发出 `CompDBIDResp` 后须等 DAT，才能再发同址 Snoop；其他 CopyBack opcode/phase 的非失效 Snoop 仍需各自 lifecycle | WEF pre-response `SnpShared` 已闭合；post-response Snoop 不建正向路径，作为当前 ordering 负向边界 |
| WriteEvict Retry/error | Retry 需要 RetryAck/P-Credit、容量预留与 reissue 后仍正确维持 CAH provenance；error 需要分别定义错误来源、形成 phase 与 clean payload disposition，当前没有相应 ECC/Poison/DataCheck 来源 | 与 Snoop modifier 分离并后置，不用普通 decode/access failure 冒充 |
| 容量驱动 data/no-data outcome | 需要 Home/Cache VirtualDut 的容量、victim/replacement 与 residency policy；当前 fixed sparse residency 不提供这些决策 | 保持为可选 participant policy，不把它冒充 CHI transaction 必备功能 |
| deliberate dirty invalidate 后的 `Evict` | 规范允许由 deliberate action 触发 dirty→I，并可用 Evict 使其可见；当前没有 caller-visible invalidate/discard intent | 等具体 invalidate 场景提出，不把普通 replacement 当成 deliberate action |
| 同 Home/type 多 waiter、公平性与 deadlock | 来自 runtime/scenario 的 progress 验证需求，不是某个 CHI opcode 的规范前置条件 | 当前不升为 opcode 主线；保留 held/wait/release seam，待真实资源场景阻塞后形成 waiter-selection/fairness property 与 wait-for/deadlock verdict |

本轮也完成了 CopyBack exact-evidence 的实现收敛。WriteBackFull、WriteEvictFull 与
WriteEvictOrEvict 现在由 typed `ChiCopyBackPhaseLedger` 保存 operation、Requester/original TxnID、
Home DBID 与 `HOME_RESPONSE/REQUESTER_DATA/REQUESTER_ACK` 下一阶段；旧 operation-specific mapping
只保留为构造兼容输入和只读 projection，不再与 canonical ledger 并列持有状态。各 opcode 的 permission、
directory、backing 与 residency effect 继续分开；该收敛不新增 wire 行为，既有三类 CopyBack 正负向
witness 保持原语义，并让 WEF(CAH=1) 的 DAT/ack 双终态不再增加一组平行 evidence authority。

1. pending `WriteEvictOrEvict` response 前 invalidating Snoop、`WriteEvictFull(CAH=1)` 正常双终态，
   以及 WEF response 前 invalidating-Snoop→`I` 和 `SnpShared→SC` 的窄切片已经闭合，并保持 exact
   terminal correlation。下一 lifecycle 决策点比较 Retry/error、deliberate dirty invalidate 与其他
   CopyBack opcode/phase 的 same-line 组合；Home 已发 `Comp`/`CompDBIDResp` 后的同址 Snoop 不作为正向候选，而是
   “先等 `CompAck`/DAT” ordering 的负向边界。容量驱动 outcome 继续等待 Home/Cache VirtualDut policy，
   不从 fixed residency 外推。若下一真实场景首先受并发资源阻塞，
   则先做同 Home/type 多 waiter 的具名选择、释放和公平性 witness。DERR 继续等待
   ECC/Poison/DataCheck 来源，不用普通 decode/access failure 冒充；
2. 只有验证目标需要观察 Home 之外的 downstream commit 时，才增加独立 SN participant 与
   topology-visible HN→SN flow；这是 system integration slice，不把已有 AXI/APB memory backend 暗绑为
   Home 的同一 state，也不作为当前 reference-backing coherence closure 的前置条件；
3. 将多 waiter 选择/公平性、多个 pending emission batch、wait-for cycle 与 deadlock verdict 作为
   system/scenario verification property 推进；只有这些运行投影稳定后，才将 family scheduler 上提为
   有界并发 LTS 探索；
4. 当前 no-SD MESI slice 保持独立有效；需要 MOESI-like profile 时，再把只供 CleanUnique 消费的预置
   `SD` 扩展为可生成、可维持的 Owned lifecycle，并以 dirty `SnpShared`、owner handoff 与 replacement
   检验。若场景需要 DCT，则另补 forwarding Snoop、peer→requester DAT、Home correlation 与 capability；
   clean-state DCT 不要求先有 Owned；
5. 第二种 packet network 提出相同接口后，再把 family scheduler 的稳定形状投影到通用 system runtime。

当前每个 resolved feature scope 显式选择一个未进入 address-router translation 的 address claim 和一个
scalar Home，RN participant 仍投影一个预配置 `home_node_id` 并由 resolver 核对；同一 runtime 按地址动态
切换多个 Home、由 SAM（System Address Map）route 派生 system-visible window、remap 和跨 domain 执行属于后续
SystemProtocol authority/construction，不是当前单 Home network 的 opcode 缺口。
MakeUnique、Evict/retry 及其余未具名扩展的 coherence feature profile 仍固定单 Requester；clean
Shared/Unique、CleanUnique、dirty WriteBack、WriteEvictFull base 与 CopyAtHome modifier 可在同一 scope
绑定同构有限 requester set。所有 profile 仍只覆盖受限 opcode 与 full-line DAT；
AddressTarget 路径固定对齐，只闭合成功与 decode/access→NDERR completion；coherent path 另闭合
pre-snoop `ReadUnique` NDERR 及其与 Retry/独立同址 Snoop 的窄组合。两者都未覆盖 DERR、
post-snoop failure、sideband lowering 或
narrow/multi-packet data；后者同时扩展分片表示与 transaction/session 聚合，不否定当前 full-line single-packet
transport。coherent Home backing 是 fixed-resident、同步、无 blocked
的 line-local commit profile，尚未等价于独立 SN participant 的可观察状态。它们是上述工作的可执行起点；准确覆盖仍只在
[实现状态](../implementation-status.md)维护。

scheduled AXI4-Lite N×M crossbar 与 direct-neighbor address closure 已形成 S3 的第一条纵向切片；因此下一阶段
按以下顺序推进。

### S1 · 已具备的局部 attachment baseline

APB、AHB、AXI4-Lite 和 AXI4 normal-access integration 已打通首个同步请求—处理—响应路径；AXI4-Stream 也已有独立
StreamTransfer contract：

- AHB 已保存 address/data phase context，并完成 narrow bus-lane mapping；后续边界是 Exclusive Access Monitor；
- AXI4-Lite 已处理 AW/W FIFO join；
- AXI4 subordinate 已展开 burst 并聚合 response，generic manager 当前是 serialized single-beat；
- AXI4-Stream 已能 capture，width conversion 与 autonomous source 后续处理。

这里列出的 Exclusive、width conversion 和 autonomous source 是各 profile 的后续扩展，不阻塞 typed bridge
T1–T6。当前 baseline 的成立依据是 attachment 的接口侧状态、quiescent 条件、错误映射和 backend binding
已经可被执行和检查。

### S2 · 已完成的类型化 bridge 与容量资源

typed stage、`AddressBurst`、fanout ledger、capacity lease、attachment-aware backend 和 operation-level
serial executor 已落地。统一 composition root 已覆盖 AXI4、AXI4-Lite、AHB、APB 四种 address family，
AHB/APB/AXI egress 和 AXI→AHB→APB chain 已证明 plan/executor 不依赖某一个协议对。

当前 serial profile 仍有意保持一个 ingress、一个 egress 和一个 active child。width split/merge、并发 child、
ID remap pool、READY/backpressure 和 crossbar 不属于 S2 已完成范围；它们按下一层真实需求继续推进。

稳定架构见[Bridge 与类型化事务转译](../typed-transaction-translation.md)，具体阶段与验收只在
[V1 实施计划](../translation-implementation.md)维护。

### S3 · 当前主线：capability、address projection 与系统构造

VirtualDut 将对系统可见但不泄漏内部实现的事实投影出来：

- 支持的 transfer size、byte enable、burst、ID、ordering；
- address claim 和 route window；
- externally visible capacity。

Builder construction lowering 与 core elaboration 只消费这些边界事实，不反射 backend 的私有
AddressSpace。前者在用户授权后选择 translation plan，后者检查展开后的 topology；未授权时保持 direct
或报告 mismatch，不在 runtime 插入 adapter。

当前已先行实现 generated address router 的 route boundary projection、`AddressClaim`/router contract 和
direct-neighbor resolution。Endpoint claim 自动派生、external/opaque projection、typed port capability、
multi-hop resolution 与 bridge auto-lowering 仍是本阶段后续内容。

### S4 · 收束 resource-aware runtime

当前 runtime 已能用 `ResourceDemand` 表示未接纳工作，以 `BLOCK` 整步回滚，并通过显式 advance 推进部分
queued backend。后续需要把 admission 从整个外部 action 细化到 emission/egress，补齐跨 connection lineage、
held lease、waiting demand 和可恢复的 wakeup 条件。这个阶段扩展现有 fixed-point runtime，不要求同时引入
物理时钟。CHI family 已先用 participant pending 与 endpoint head 提供一条只读 held/wait/wakeup 投影，
但它不等价于通用 SystemProtocol 动态资源合同。

### S5 · wait-for 与 deadlock 证据

有了显式 blocked reason、动态资源和非立即 emission 后，SystemProtocol 才能构造 wait-for graph。分析目标
不是简单寻找拓扑环，而是寻找可达、非 quiescent、无 enabled transition、且 obligation 未完成的状态。
这是 system/scenario verification property，不是 CHI opcode、MESI lifecycle 或现有 route 可运行的前置条件。

输出应包含：等待谁、持有什么资源、哪条 obligation 未关闭、是否存在 escape transition。

### S6 · 自主 emission 与时间窗口

当前同步 fixed-point 适合点到点和微型 bridge。异步扩展需要区分：

- backend 自主 emission 与外部 injection；
- blocked、deferred、scheduled output；
- 本地时钟和跨域不可比时间；
- deadline/time window，而不是强行使用一个全局 cycle。

这一步以后才能严谨表达 timer、CDC、异步 FIFO、长期 fairness 和 timeout。CDC 是跨协议的通用
control-topology/观察方法议题，长期 fairness 是验证 property；二者都不计作 CHI opcode 或现有网络功能缺口。

## 贯穿所有阶段的验证方式

每条小型完整路径只需要与风险相称的证据：

1. 一个合法 witness；
2. 一个只违反目标规则的负例；
3. 可以解释的 state/resource/causal projection；
4. 明确记录仍未覆盖的规范条款和基础能力。

测试是验证架构判断的手段，不以 case 数量代替架构进度。
