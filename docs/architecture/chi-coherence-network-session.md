# CHI coherence 与 transport-network 的窄版组合 session

[CHI family 边界](../../protocol_model/protocols/amba/chi/README.md) ·
[网络构造](network-construction.md) ·
[通信建模的三张视图](communication-scope-and-transport.md) ·
[当前实现状态](implementation-status.md)

本文规定一条受限但完整的 CHI 一致性网络执行路径：调用方提交 coherent read、`CleanUnique`、
`MakeUnique` 或 clean `Evict`，或者先在
拥有 unique copy 的 RN 上执行本地写；participant 产生的 packet 经过已解析的 CHI transport topology，
到达目标 participant 后继续驱动协议 lifecycle，直到网络和一致性状态共同静止。

这项组合位于 CHI family runtime。它连接两个已经存在的执行边界：

- `ChiCoherenceSession` 执行 RN/Home 的 clean read、clean Evict、dataless MakeUnique、受限 dirty
  unique-transfer、MESI no-SD dirty-to-clean-shared，以及受限 shared-dirty peer `CleanUnique` 行为，
  以“packet 已送达目标”为输入边界；
- `ChiTransportNetworkSession` 执行有向 hop、Link activation、L-Credit、有限 FIFO 和 router forwarding。

组合 session 不形成新的协议层，也不改变两个子 session 的职责。当前实现进度继续由
[当前实现状态](implementation-status.md)维护；本文集中记录目标对象、实施边界和验收条件。

## 1. 适用范围与决策性质

本文中的约束分为三类：

| 性质 | 含义 | 本切片中的例子 |
|---|---|---|
| 协议要求 | CHI lifecycle、消息相关性和 channel 使用所要求的事实 | Read、SNP、SnpResp、CompData 和 CompAck 必须按相应 identity 关联 |
| 架构选择 | Protocol Model 为保存职责边界而采用的组织方式 | participant 状态与 transport 状态分别由两个子 session 持有 |
| 阶段选择 | 为形成首个可执行纵向切片而采用的受限 profile | 一个 resolved requester、一个 Home、显式有限 Snoopee 集合、`I/SC/UC/UCE/UD` 加只供 dirty-peer CleanUnique 消费的 `SD`；`UCE` 是无 payload 的 unique authority，其余数据传输固定 512-bit full-line DAT |

阶段选择可以在后续 profile 中扩展。扩展时仍需通过 feature、capability、identity 和 route closure
显式声明，不由 topology 外形推断协议能力。

## 2. 目标对象与边界

目标对象在本文中称为 **coherence network session**，源码入口为
`ChiCoherenceNetworkSession`。

```text
ResolvedChiSystem（不可变构造证据）
  ├─ requester / Home / Snoopee role bindings
  ├─ NodeID ownership
  ├─ enabled clean-read / CleanUnique / MakeUnique / clean-Evict / dirty-unique / MESI no-SD features
  ├─ per-member REQ / SNP / RSP / DAT flow closure
  └─ ChiTransportNetworkSession
                    │ open
                    ▼
coherence network session
  ├─ ChiCoherenceSession
  │    └─ RN cache、Home directory、pending transaction
  ├─ ChiTransportNetworkSession
  │    └─ hop、activation、credit、FIFO、router、packet lineage
  └─ family scheduler
       └─ route dispatch、endpoint delivery、原子组合与公平轮转
```

各对象的所有权如下：

| 对象 | 持有内容 | 不持有的内容 |
|---|---|---|
| `ResolvedChiSystem` | 静态 topology、participant binding、NodeID、address→Home/domain authority、feature/capability 和可执行 flow 证据 | transaction、FIFO、cache line 等运行状态 |
| `ChiCoherenceSession` | RN/Home 行为、cache/directory、Snoop response 聚合、稳定点 invariant | packet 经过哪些 hop、Link credit 和 router queue |
| `ChiTransportNetworkSession` | protocol flit 的逐 hop 搬运、router store/forward、Link 资源和 hop lineage | opcode 对 participant 状态的作用、全局 coherence invariant |
| 组合 session | 两个状态的原子推进、packet 与 route 的装配、endpoint dispatch、跨 packet 因果 join | 新的 cache policy、隐式 snoop filter、未经构造证明的 route |

`ChiDeliverCoherencePacket` 在组合 session 中成为内部动作。它仍可保留为 participant 级单元测试入口，
但完整网络场景不通过它绕开 transport。

## 3. 构造期输入

组合 session 只从已经闭合的 `ResolvedChiSystem` 打开。构造过程至少执行以下检查：

1. `ResolvedChiSystem.require_closed()` 成功；
2. feature intent 选择 requester，以及 clean ReadShared、clean ReadUnique、其 NDERR/Retry modifier、
   clean Evict 及其 Retry modifier、clean-peer CleanUnique、独立 MakeUnique、
   `CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER`、dirty unique-transfer、
   dirty writeback，或 `CHI_MESI_NO_SD_REQUIRED_FEATURES` policy preset；ReadUnique NDERR 不增加 flow，
   shared-dirty CleanUnique 依赖 clean-peer CleanUnique 并增加 Snoopee→Home DAT flow，
   dirty unique-transfer 依赖 clean ReadUnique，no-SD preset 再组合 dirty unique-transfer 与独立的
   ReadNotSharedDirty feature；
3. 本次 feature scope 显式引用一个通用 `AddressClaim`；CHI authority contract 将该 claim 绑定到
   scalar Home，并在需要 Snoop flow 时绑定一个 coherence domain；
4. resolver 从 domain 派生 `Snoopee = members - requester`，拒绝调用方另行手填 Home/Snoopee role；
5. Home、requester 与 domain member 都解析为 transaction facet；当前 coherence runtime 要求每个绑定
   只有一个 NodeID，且 claim endpoint 属于 Home identity boundary；
6. participant component 类型与相应角色匹配，Home 初始 directory holder 不得越出 resolved domain；
7. 每条启用 lifecycle 所需的 per-member flow 都存在唯一的有向 connection 序列；
8. flow 的首 hop transmitter port 和末 hop receiver port 属于相应 participant binding；
9. packet channel 受到沿途每条 transport profile 支持，resolved runtime 拒绝越出所选 claim window 的请求。

当前一个 `ResolvedChiSystem` 仍只选择一个 feature address scope 和一个 scalar Home。authority plan 可以
保存多个互不重叠的 claim，但当前只接受未进入 address-router translation 的 claim；SAM route 的 input
window/remap 尚未投影成 CHI system-visible authority。同一 runtime 也不按每笔地址动态切换 Home；RN 中的
`home_node_id` 是被 resolver 核对的本地配置投影，不是第二份 system authority。

### 3.1 不可变 route 与 delivery 索引

运行时不重新搜索 topology。构造期从 `ChiFlowProjection` 生成两个只读索引：

```text
outbound route:
  (source NodeID, target NodeID, channel) -> ordered connection path

endpoint delivery:
  (last connection, receiver port, channel) -> target participant
```

索引建立时拒绝以下情况：

- 缺少 route；
- 同一个 key 对应多条可执行 route；
- target NodeID 不属于目标 participant；
- 首末端口与 participant binding 不一致；
- route 中途的 router 无法按 `channel + target NodeID` 选择下一跳。

SNP message 本身不承担所选 Snoopee 的 network route identity。Home 为每个目标产生独立的
`ChiNetworkPacket`，每份 packet 的 `target_id` 进入上述索引。fanout copy identity 与
message→multi-packet fragmentation 是两类关系；首版 fanout packet 仍各自包含一个完整 SNP message。

## 4. 组合状态

组合状态保留子状态边界，避免复制 participant、router 或 Link 状态：

| 字段 | 作用 |
|---|---|
| `coherence` | 一个 `ChiCoherenceState` |
| `network` | 一个 `ChiTransportNetworkState` |
| `pending_egress` | 一次 participant transition 原子产生、尚未全部进入网络的有限 packet batch |
| `scheduler_cursor` | 对有限候选集合做 round-robin 的下一起点 |
| `committed_microsteps` | 已提交内部小步数量，用于诊断和有界运行 |

route/delivery 索引、role registry 和 enabled feature 属于 session 的不可变构造结果，不进入每个动态状态。

`ChiCoherenceNetworkSession.project_progress(state)` 从这份组合状态只读派生
`ChiCoherenceProgress`：Home/RN pending 是 `ChiHeldLine`，当前 transport endpoint head 若因其中一项
line resource 返回 `ResourceDemand`，则形成 `ChiLineWait`。这些对象不反向驱动 participant 或 scheduler，
也不复制 pending/packet 的所有权。

### 4.1 跨 packet 因果证据

transport runtime 已保存 packet 在每条 connection 上的 lineage；组合 session 在 endpoint accept 和
participant egress 处继续追加 lineage。coherence lifecycle 还包含跨分支 join：Home 只有收齐目标
Snoopee 的响应后才能产生 CompData。当前 Home pending transaction 是这项 join 的行为权威：

```text
(requester NodeID, requester TxnID)
  ├─ accepted request predecessor
  ├─ snoop branch[target NodeID]
  │    ├─ emitted SNP predecessor
  │    └─ delivered SnpResp predecessor
  └─ completion / CompAck predecessor
```

当前 packet lineage 可以分别追踪根 request、每条 SNP/SnpResp 分支和 completion，但还没有把这些分支
折叠成一条显式的 transaction-level causal join record。后续为 MSC 或 deadlock evidence 增加该 record
时，它只保存事件引用；Home pending state 仍负责决定是否可以产生 CompData，不能由可视化证据替代。

## 5. 小步调度

组合 session 使用有限、可枚举的小步候选。候选按 round-robin cursor 检查；一个候选受到背压时，
scheduler 可以尝试其他候选。轮转顺序是确定性 reference policy，不表示 CHI 规定了相同的仲裁顺序。

首版候选包含：

1. **外部 operation submit**
   requester 执行 `ChiSubmitCoherentRead`、`ChiSubmitCleanUnique`、`ChiSubmitMakeUnique`、
   clean-Evict 或 writeback submit，生成 REQ
   packet，并把完整 emission 保存为一个 `pending_egress` batch。

2. **egress packet → 首 hop enqueue**
   从 batch 头取一个 packet，按静态 route 索引加入首 hop；网络背压时 batch 保持不变。

3. **Link tick**
   推进一条 connection 的 activation、credit 和 protocol-flit transfer。

4. **capture → router**
   复用 network session 已有的原子动作，把 receiver capture 转交给有限 router FIFO。

5. **router → downstream connection**
   router 按 `channel + target_id` 选择 route，并在下游有容量时完成 enqueue。

6. **endpoint delivery + participant transition**
   从末 hop `peek_delivery`，核对 delivery index，向 coherence session 内部提交 delivered packet，
   将它产生的零个、一个或多个输出 packet 保存为新的 batch，并 drain 输入 capture。

每次 advance 最多提交一个候选。若所有候选均未启用：

- 已经共同静止时返回静止结果；
- 存在 typed `ResourceDemand` 时返回 blocked；
- 存在未关闭 obligation、同时没有可执行小步时，记录为 progress 分析输入；
- `max_steps` 耗尽产生 inconclusive 诊断，不直接形成 deadlock verdict。

因此调用方负责选择并提交初始 operation，并在离散模型中调用 `advance()` 或
`run_until_quiescent()`；scheduler 负责 packet admission、Link/router 推进、endpoint dispatch 和
participant 后续输出。调用方不需要逐包手工选择 Snoop、Comp 或 CompAck，但当前也没有后台线程或
真实时钟自动产生业务 operation。

endpoint participant 返回 `BLOCK` 时，候选不 drain 输入 capture，packet 仍位于同一个 endpoint head；
scheduler 可以推进其他候选，并在后续 `advance()` 中重新尝试该 delivery。因而 Home 同址 reservation
由首笔事务的 `CompAck` 释放后，等待请求会自动 replay，不要求调用方重新提交或手工重送 packet。

### 5.1 共同静止条件

组合 session 只有同时满足以下条件才静止：

- `ChiCoherenceSession.is_quiescent(coherence)`；
- `ChiTransportNetworkSession.is_quiescent(network)`；
- 没有待提交的 fanout continuation；
- coherence stable monitor 通过。

`pending_egress` 就是首版显式 continuation。它保存一次 participant 决策产生的完整 packet 集合，
但各 packet 可以在不同 microstep 进入网络。

## 6. 原子提交

一项组合候选在不可变快照上计算所有子 transition。只有每个必需步骤均成功时，coherence state、
network state、pending egress 和 scheduler state 才一起替换。

endpoint delivery 的概念顺序如下：

```text
delivery = network.peek_delivery(...)
coherence_step = coherence.deliver(delivery.packet)
egress_batch = validate_and_save(coherence_step.emissions)
network_candidate = network.drain(delivery)

commit(coherence_step.state, network_candidate, egress_batch)
```

这段顺序表示候选内部的数据依赖，不表示一个物理 cycle 内必须发生相同的动作组合。

组合规则如下：

- 任一 child transition 返回 `BLOCK`：返回原组合状态，并保留最具体的 `ResourceDemand`；
- 任一 child transition 返回 fault：返回原组合状态和带位置的 fault；
- route 或 identity 不可解析：形成 system/construction fault，不把 packet 丢弃；
- 成功：一次提交全部子状态和相应事件；
- 未提交的候选不公开部分 emission，也不消费输入 capture 或 L-Credit。

这条规则避免 Home 已改变 transaction state、但其 SNP emission 没有任何持有者的半提交状态，也避免
endpoint packet 已经 drain、participant 却因资源不足未接纳的状态。packet 后续进入首 hop 受网络容量
控制；未接纳的 packet 继续留在 batch 中。

`project_wakeups(before, after)` 只在原 `ChiLineWait` 消失且其 exact `ChiHeldLine` 也已释放时形成
`ChiLineWakeup`。它是解释 scheduler 为何可以重新尝试的 release evidence，不声称等待 packet 已经接纳、
没有其他 blocker，或系统已经排除 deadlock。

## 7. 多 Snoopee fanout

clean Home 可以从 directory 得到零个或多个 Snoopee。每个目标对应一个显式 SNP network packet，
router 仍按普通 unicast packet 处理。首版采用 **整批保存、逐 packet admission**：

1. participant transition 一次产生完整目标集合；
2. 组合 session 在提交 Home state 前验证每份 packet 都有已闭合 route；
3. 完整 packet tuple 与 Home state 一起原子提交到单个 `pending_egress` batch；
4. 后续 microstep 按确定顺序尝试把 batch 头加入对应首 hop；
5. 当前首 hop blocked 时 batch 不前移，其他 Link/router 候选仍可推进；
6. batch 清空后才接收下一项会产生 participant output 的 endpoint delivery。

这种 policy 不要求多个 SNP 出口同时有空位，也不会让 scheduler 丢失尚未 admission 的分支。它会把
participant emission 串行化为一次一个 batch；这是首版有限 composition storage 的阶段选择。

后续需要多个 participant emission 并存时，可以扩展为多个有界 continuation：

```text
coherence decision
  -> immutable target set
  -> per-target issued/accepted ledger
  -> independently admitted packet copies
```

届时 Home 对事务的逻辑决定仍只提交一次，静止条件和 completion gate 必须等待所有目标 packet 已发行并
收到所需响应。这个扩展需要新的有限存储和 wait-for projection，因此不混入首版。

## 8. 身份、route 与 participant dispatch

每次 participant emission 和 endpoint delivery 都执行双向核对：

### 发射侧

- `packet.source_id` 属于发射 participant；
- `packet.target_id` 属于目标 participant；
- channel 与 message form 匹配；
- enabled feature 允许该 opcode；
- outbound route 的首 hop transmitter 等于发射 participant 的已绑定端口。

### 接收侧

- delivery connection、receiver port 和 channel 命中唯一 delivery index；
- packet target NodeID 等于接收 participant 的 NodeID；
- Read/CompAck 只能进入本构造的 requester/Home 关系；
- retryable initial/credited REQ 必须匹配 Requester retained entry 的 current form 与 phase；已经产生
  RetryAck 的 initial REQ replay 在 Home mutation 前作为 system correlation fault 拒绝；
- SNP 只进入声明的 Snoopee；
- SNP 必须命中并一次性消费 Home-produced exact delivery evidence；transaction identity 相同但
  opcode/message 被替换，或 completion 后重放的 SNP，都会在进入 RN participant 前被拒绝；
- SnpResp/SnpRespData 只由声明的 Snoopee 返回相应 Home；
- `RetryAck`/`PCrdGrant` 必须命中并一次性消费 Home 实际产生的完整 packet evidence；credit type、
  source/target、channel 或 packet metadata 被替换以及 replay 都不能驱动 Requester retry ledger；
- RSP/DAT completion 只进入已授权 requester，并命中、一次性消费 Home 实际产生的完整 packet
  evidence；data、Resp、DBID、RespErr 或 packet metadata 任一被替换以及 completion replay 都被拒绝。

这些 evidence 是 system correlation，不增加 wire 字段；它们把“身份相似的输入”收窄为“本 session
实际发出的 packet”，同时保持 participant state 为 cache permission 与 transaction lifecycle 的权威。
Home 的 P-Credit reservation 仍按 `(Requester, PCrdType)` 池化；`PCrdGrant/PCrdReturn` 不携带 TxnID，
因此 standalone Home participant 不制造 transaction-credit 绑定，也不能在 grant 后单独判断某个 initial
REQ 是否为旧副本。需要防伪/重放闭包的调用方使用 composition session，由 RN retained phase/current form
与 packet provenance 共同判定。

router 不解释 coherence opcode，也不修改 protocol message。它消费 packet route identity 和 transport
resource；participant 才解释 Read、SNP、response 和 completion。

## 9. MESI/MOESI 与当前 profile 的边界

基线 RN 稳态为 `I/SC/UC/UCE/UD`。其中 `UCE` 只保存 unique authority，不在 `CacheLineStore` 中保存
payload；它由 `CleanUnique` 的无数据 completion 在 requester payload 已不存在时形成，第一次 full-line
local write 安装 payload 并进入 `UD`。`CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER` 额外允许调用方为一条
CleanUnique witness 预置一个受限 `SD` holder；当前没有任何普通 read、write 或 replacement action 生成
`SD`。Home participant 保存 directory/pending，注入的协议中立 `FullLineBackingCore` 操作
`LineBackingState`；当唯一 holder 处于 `UD`，或 `shared_dirty_owner` 指向一个 `SD` sharer 时，backing
copy 可以陈旧，最新数据及其最终写回责任由相应 holder 持有。当前切片能表达：

- `ReadShared` 使 requester 获得 clean shared copy；
- clean `ReadUnique` 失效其他 holder，使 requester 获得 `UC`；
- pre-snoop `ReadUnique` NDERR 只保留 DBID/同址 reservation 到 `CompAck`，Requester 的原 `I`/`SC`
  与 payload、其他 holder、directory 和 backing 都不变化；
- `UC` 或 `UCE` holder 的本地 full-line write 将其推进到 `UD`；`UCE→UD` 同时安装此前不存在的 payload；
- 另一个 requester 的 `ReadUnique` 通过 `SnpRespData_I_PD → CompData_UD_PD` 接管最新数据和 dirty
  responsibility；
- requester 的 `ReadNotSharedDirty` 通过
  `SnpNotSharedDirty → SnpRespData_SC_PD → CompData_SC` 取得 clean shared copy；原 `UD` holder
  降为 `SC`，Home pending 接管最新数据和责任，待 `CompAck` 后再提交 backing/directory，最终两个 RN
  都不再承担 dirty responsibility；
- `SC` holder 可通过 `ReadUnique` 重新取得 full-line、失效其他 holder 并进入 `UC`，随后 local write
  进入 `UD`；
- `I` 或 `SC` requester 可发 clean-peer `CleanUnique`。若 requester 的 full-line payload 一直保留，
  Home 发 `SnpCleanInvalid` 收齐 clean `SnpResp_I` 后返回无数据 `Comp_UC`，requester 进入 `UC`；
  若从 `I` 发起，或 pending CleanUnique 期间被同址 `SnpUnique`/`SnpCleanInvalid` 失效，则
  `Comp_UC` 形成无 payload 的 `UCE`。两条路径都以 Home 分配的 DBID 返回 `CompAck`；
- `MakeUnique(0x0C)` REQ 本身无数据，submit API 另将 RN-local 512-bit full-line store intent 保存在
  requester pending state。规范描述的 expected initial requester state 为 `I/SC/SD`；当前模型还允许
  `UC/UCE`，并拒绝 `UD` 发起。Home 对实际 peer 发 `SnpMakeInvalid(0x0A)`；peer 从当前任一已表示状态
  `I/SC/SD/UC/UCE/UD` 进入 `I`，只返回 `SnpResp_I`，不发送 DAT，旧 dirty payload 被本阶段 profile
  明确丢弃。Home 收齐 response 后返回 `Comp_UC`；requester 在同一 transition 中覆盖/安装 intent 为
  `UD` 并发送 `CompAck`。Home 到 Ack 才提交 requester unique authority 并释放 DBID/同址 reservation，
  backing payload/version 保持不变；
- `UC/UCE/SC` requester 可先原子转为无 payload `I`，再发 clean `Evict`。Home 只条件删除仍匹配
  source 的 clean owner/sharer；stale/non-holder 或明确的 shared-dirty holder hint no-op。`Comp_I`
  通过原 TxnID 退休 RN pending，
  DBID 字段不形成 lease，不产生 DAT/CompAck，backing payload/version 与 Home allocator 不变；
- 选择 clean Evict Retry modifier 时，初始 `Evict` 可由独立 Home policy 返回 `RetryAck`。拒绝阶段只建立
  retry debt，不删除 holder、不修改 backing，也不分配 DBID/Snoop；`PCrdGrant` 预留真实容量，
  `AllowRetry=0` 且 `PCrdType` 匹配的 reissue 原子消费 reservation 后才进入上一条 Evict lifecycle。
  Grant 与 Ack 可按任一顺序到达，pending Evict 在等待期间仍是无 payload `I` 并可响应独立同址 Snoop；
- 启用 `CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER` 时，Home 可以对目录中唯一的
  `shared_dirty_owner` 发同一个 `SnpCleanInvalid(DoNotGoToSD=1, RetToSrc=0)`；该受限 `SD` peer
  以 `SnpRespData_I_PD` 返回最新数据并原子失效。Home 将数据保存在
  `ChiCoherentTransactionPending.dirty_result`，收齐所有 clean/dirty peer response 后先生成
  `prepared_backing_write`，再返回 `Comp_UC`；同地址 Home reservation 保持到 requester 的 `CompAck`，
  届时按该行 version 提交 backing，并在同一个 Home-state transition 中清除
  `shared_dirty_owner`、提交 requester 为唯一 `UC` holder；
- stable monitor 检查 directory permission；有 payload 的 clean copy 必须匹配 backing data，`UCE` 不得有
  payload 且必须是 directory unique owner，`UD` copy 必须是唯一 owner；受限 `SD` copy 必须与
  directory 的唯一 `shared_dirty_owner` 对应。

这已经覆盖 MESI 中“unique clean 经过写入成为 modified、modified owner 被另一请求者接管，以及
modified 数据回到 Home 后形成两个 clean shared copy”的几条纵向路径，但还没有形成完整 MESI 状态机。
尚缺的主要行为是：

- 把 dirty-peer CleanUnique 的 reference memory-update obligation 下沉为独立 Memory VirtualDut 或
  CHI SN-F physical commit；
- MakeUnique Retry、DERR/NDERR、MTE Update、partial write、multi-Home 等扩展；当前 MakeUnique
  executable profile 为 tagless、OK-only；
- 从 victim policy 自动触发 eviction/writeback、deliberate dirty invalidate 与
  WriteEvict family；显式 clean Evict 以及选择一条 `UD` line 后的
  `WriteBackFull → CompDBIDResp → CopyBackWrData_UD_PD`、同址 invalidating-Snoop 后的
  `CopyBackWrData_I` cancel 已经闭合；
- 普通 `ReadShared` 命中 `UD` 时的 policy；当前 no-SD 行为由显式 `ReadNotSharedDirty` 路径承担；
- 同 line 并发已闭合若干具名 RN transient：pending ReadUnique 接收同址 `SnpUnique`，保留 pending/Retry
  correlation 后由 `CompData` 重新安装 `UC`；pending CleanUnique 接收同址 `SnpUnique` 或
  `SnpCleanInvalid`，先失效为 `I`，再由 `Comp_UC` 形成 `UCE`；pending MakeUnique 接收同址
  invalidating Snoop 后保留 store intent，再由自己的 `Comp_UC` 安装为 `UD`；pending clean Evict
  保持 `I`、返回 `SnpResp_I` 并保留 correlation。direct `ChiCoherenceSession` 的双
  Requester witness 证明两笔 CleanUnique 可由 Home line reservation 串行、第二笔最终取得 `UCE`；
  pending WriteBack 接收同址 invalidating Snoop，把 dirty data 交给 Home 后显式变为
  `CANCELED_I`，再以 `CopyBackWrData_I` 退休。等待者合并、一般 transient phase、Snoop 优先级，以及
  超出当前窄 witness 的 Retry/Snoop 到达次序、同一 accepted request 已发出 Snoop 后的 error 与
  Retry cancel 仍未闭合；
- runtime 按地址动态选择多个 Home、SAM remap 和跨 domain 执行。

当前 `SD` 只是一条受限 CleanUnique 前置状态及其失效出口，不是完整 MOESI/Owned profile。后者还需要
产生和维持 shared-dirty 状态的 lifecycle、dirty `SnpShared`、owner handoff、forwarding snoop/DCT，
以及 owner eviction/recovery。

当前 feature closure 可以分别选择 clean ReadShared、clean ReadUnique、clean-peer CleanUnique、
MakeUnique、clean Evict、clean Evict Retry、clean ReadUnique NDERR/Retry modifier、
shared-dirty-peer CleanUnique、dirty-unique、dirty-writeback 和独立的 MESI ReadNotSharedDirty
十二个 feature。NDERR modifier 依赖
clean ReadUnique，只增加
Requester/Home NDERR 原子能力和显式 system lifecycle fact，不增加 flow；Retry modifier 同样依赖 base，
但增加 Requester/Home Retry 原子能力、Home→Requester RSP flow 和另一项 system lifecycle fact。
`CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS` 的五类 REQ/SNP/RSP flow 不含 DAT，并与会返回
CompData 的 ReadUnique 保持独立。`CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER` 依赖前者，只增加
Snoopee→Home DAT、Home PassDirty data accept/reference memory update 与 peer dirty-data produce
要求，并产生 `CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE` 证据；runtime 复用 Home 的
`allow_dirty_data_transfer=True`，不增加另一枚 feature-specific flag。它不会把 DAT 要求反向加到
clean-only construction。该 modifier 的名称来自最先闭合的 `SD/shared_dirty_owner` witness；当前 runtime
把它解释为“CleanUnique snoop 可以返回 PassDirty DAT”，因此同样约束已有 `UD unique_owner` 被
CleanUnique 失效并由 Home 吸收最新数据的路径。公开 feature 命名稳定前应将它泛化为 dirty-peer modifier
或拆成两个更窄的 profile，不应把这一复用误解为 `UD` 与 `SD` 是同一 cache state。

`CHI_FEATURE_CLEAN_EVICT` 独立于 read/CleanUnique feature，不要求 Snoopee。它只闭合
Requester→Home REQ、Home→Requester RSP、四个 participant 原子能力与一项 system lifecycle；
通用 packet-delivery completion evidence 防止未经过 Home 或字段被替换的 `Comp_I` 退休 request。
pending Evict 遇到由另一笔 transaction 产生的同址 Snoop 时返回 `SnpResp_I`，并保留原 Evict
correlation。

`CHI_FEATURE_CLEAN_EVICT_RETRY` 依赖 clean Evict base，增加 Requester/Home 的通用 Retry 原子能力、
具名 Home→Requester `retry_response` RSP flow 和独立 system lifecycle fact。它采用独立
`evict_retry_policy`，不会因启用 ReadUnique Retry 而放开 Evict，反向也一样；base Evict 的 completion
flow 与 Retry response 可以落在同一 resolved RSP route，但仍是两个可审计的 flow schema。

`CHI_FEATURE_MAKE_UNIQUE` 也独立于 CleanUnique，dependency set 为空；它显式要求
Requester/Home 和可为空的 Snoopee finite-set role 及一项 system lifecycle，并闭合五类 flow：Requester→Home REQ、
Home→Snoopee SNP、Snoopee→Home SnpResp RSP、Home→Requester Comp RSP 和
Requester→Home CompAck RSP。它不声明 DAT flow；dirty discard 是 Snoopee 的显式 capability。
feature 本身的独立性不表示所有 feature 组合都能使用当前窄 dirty policy：MakeUnique 可产生 `UD`，
所以与 clean ReadUnique 组合时当前 construction 还要求 dirty-unique-transfer modifier；与 clean-peer
CleanUnique 组合时要求 shared-dirty modifier。MakeUnique 与 MESI ReadNotSharedDirty 的两个方向
same-line transient 尚未闭合，因此当前 construction 拒绝同时选择。它们是阶段 closure，不是 CHI
协议永久禁止这些 transaction 共存。

`CHI_MESI_NO_SD_REQUIRED_FEATURES` 是 system 侧 policy preset：
它组合 dirty-unique 与 ReadNotSharedDirty，前者的 dependency closure 再带入 clean ReadUnique；
ReadNotSharedDirty feature 本身没有 dependency，也不要求 local-write capability。no-SD policy 使用
`DoNotGoToSD=1`，并复用 dirty-data 返回能力；
clean `ReadShared` 与任一允许 `UD` 的 feature 组合仍被明确拒绝，因为它尚未选择
writeback/downgrade 或 shared-dirty policy。这是一项阶段边界，不是 CHI 协议禁止这些 transaction
共存。

MESI/MOESI policy 位于 participant backend、system authority 和 stable system monitor 的组合边界。
transport-network session 继续搬运 packet，不保存 cache permission。功能通过显式 feature、participant
capability、flow requirement 和 invariant 加入；不同 feature 可以依赖同一基础路径，不要求彼此完全独立。
这里的三种投影各有权威：message/opcode/field 与 transaction-local correlation 由 representation 和完整
逻辑接口合同检查；RN cache payload 与 Home backing payload 分别由协议中立 core 持有，CHI
permission、directory 和 pending 由 participant behavior 持有；NodeID、
Home/domain authority、feature/flow closure 与跨节点 invariant 由 SystemProtocol 组合。`TransportLink`
仅表示一条有向 TX→RX hop，`InterfaceProtocol` 则是完整逻辑接口的作用域名称，二者不互相替代。

### 9.1 Dirty 为什么不做成所有 VirtualDut 的通用布尔位

Dirty 描述的是“这份 cache-line 数据比 Home backing 更新，并由谁承担最终写回责任”，并非任意 module 都有的
状态。当前模型将它放在三个互相校验的事实中：

- RN 的 `ChiCacheLine.state=UD` 表示本地同时拥有 unique permission 和 dirty responsibility；受限
  `SD` 表示该 RN 是 shared holders 中唯一暂时承担 dirty responsibility 的节点；
- Home directory 的 `unique_owner` 表示唯一 holder；`sharers` 决定 shared holder 选靶，
  `shared_dirty_owner` 再指出其中哪个 peer 必须返回 dirty data，且只在 restricted dirty-peer
  CleanUnique profile 中使用；
- transaction 内的 `SnpRespData_I_PD`/`CompData_UD_PD` 表示责任正在随数据转移；
- `SnpRespData_SC_PD` 表示旧 owner 交出 dirty 数据并降为 clean shared；Home pending 先接管数据与责任，
  再以 `CompData_SC` 给 requester 建立另一份 clean shared copy，收到 `CompAck` 后才提交
  backing/directory。
- dirty-peer CleanUnique 的 `SnpRespData_I_PD` 进入 `dirty_result` 后，Home 已接管最新数据与 reference
  memory-update obligation；直到 `CompAck` 前，同址 reservation 阻止另一笔事务观察旧 backing。

启用 dirty feature 后，Home 对 unique owner 使用 `RetToSrc=1`，因此即使 Home 不预知该 owner 当前是 `UC`
还是 `UD`，也不会在 backing data 可能陈旧时盲目完成请求。Home 以统一的 `ChiSnoopResult` 收集 RSP/DAT，
并拒绝一笔 transaction 出现两个 PassDirty source。非数据 `SnpResp` 在 representation 边界拒绝
PassDirty；它必须随 `SnpRespData` 和实际数据同行。

当前 directory 已以 `shared_dirty_owner` 表达这条受限 witness 的唯一 dirty sharer，而不是给所有
VirtualDut、FIFO 或普通寄存器添加 `dirty` 字段。它没有定义 `SC/UD→SD`、dirty shared read、owner handoff
或 replacement，因此不能据此宣称完整 `SD`/Owned。

### 9.2 Cache VirtualDut 与 transient 资源

Cache 的构造从协议中立的 resident-line storage 开始，再附加 CHI coherence behavior。当前
`CacheLineStore` 只保存 line presence 与 payload，薄层 `CacheCore` 在选择协议之前为这些状态提供设备本地
core 身份；它本身还不是 topology 中的 `VirtualDut` module boundary。`ChiCoherentRnNode` 保存
基线 `I/SC/UC/UCE/UD` permission、受限 `SD` CleanUnique 前置态、local dirtying、TxnID 和 pending
coherent transaction。`UCE` 不占用 resident-line payload。`ChiCoherentRnState.lines` 是由这两份不同职责的
事实合成的只读投影，不是第二份 line data。

`attach_chi_issue_h_coherence()` 接受已经建立的 core，再装配具名 `VirtualDut` transport boundary、
participant binding 与 transaction facet。`build_chi_issue_h_cache_vdut()` 是按相同顺序先创建 store、
形成 core、再调用 attachment 的便捷入口：

```text
CacheLineStore
  └─ resident line presence + payload
       │
       ▼
CacheCore
       │
       ▼
CHI-attached Cache VirtualDut assembly
  ├─ chi_tx TransportPort: REQ / RSP / DAT
  ├─ chi_rx TransportPort: RSP / SNP / DAT
  └─ transaction facet
       └─ ChiCoherentRnNode
            ├─ CHI permission: I / SC / SD(restricted) / UC / UD
            └─ finite pending coherent-transaction table
```

这里的 `attach` 是 `CacheCore → 新的第一个 VirtualDut`，不是把一个 bare VirtualDut 复制成另一个 attached
对象。调用方已经拥有带所需 ports 的 canonical VirtualDut 时，使用
`bind_chi_issue_h_cache_vdut(existing_vdut, ...)`；binder 返回的 assembly/facet 继续引用同一个对象，不创建
port、connection 或第二个 topology identity。

这个 family-local assembly 只展开到 CHI 可见深度；当前 CHI session 直接执行 participant/facet，尚未把
packet 输入降为通用 `VirtualDutBackend.accept(PortInput)`。因此它已经修正 storage→coherence attachment
的构造方向，但还没有宣称具备 CPU-side port 或通用 backend runtime。CPU-side pipeline、tag/set/way、
替换算法、预取和具体 RTL RAM 也没有被暗示。

普通 `MemoryRegion` 可以复用字节存储思想，却不能直接充当 cache：cache 还需要 resident/absent、line
install 和 eviction 语义。LRU/随机替换属于以后可插入的 victim policy；MMU 是本地请求到达 cache 前的
相邻地址翻译组件，不是 coherence attachment 的必选内部部件。

Home 已采用对应的 core-first 构造，但它需要比普通 `AddressTarget.access()` 更明确的延迟提交边界：

```text
FullLineBackingCore
  ├─ fixed resident BackingLine payload
  ├─ prepare_write: pure line patch + expected version
  └─ commit_write: line-local CAS
       │
       ▼ attach_chi_issue_h_home()
CHI-attached Home VirtualDut assembly
  ├─ chi_tx TransportPort: RSP / SNP / DAT
  ├─ chi_rx TransportPort: REQ / RSP / DAT
  └─ transaction facet
       └─ ChiCoherentHomeNode
            ├─ directory holder authority
            ├─ finite pending transaction table
            └─ prepared backing obligation
```

`ChiHomeDirectoryEntry` 不再保存 payload；`ChiCoherentHomeState.backing` 是唯一 reference copy。
dirty-peer CleanUnique 或 dirty `ReadNotSharedDirty` 收齐 Snoop data 后，Home 在发送 completion 前 prepare；
`CompAck` 时先校验该行 version，再把 backing candidate、directory candidate 和 pending retire 作为一个
不可变 state transition 暴露。不同地址的 intent 可以反序提交而不覆盖对方；同址 stale/double commit
产生 fault 并保留整个输入 state。clean-only CleanUnique 不生成 intent。普通
`CopyBackWrData_UD_PD` 在接收 DAT 的同一步 prepare+commit；Home 接纳 WriteBack 时同时冻结
`directory_snapshot` 与 `backing_version`，DAT 到达时先检查两者未变。Snoop-canceled
`CopyBackWrData_I` 不准备或提交 payload，只在相同 snapshot/version guard 下退休 DBID，因而不会用旧
requester 的数据或 owner 覆盖已经完成的同址 transaction。

`bind_chi_issue_h_home_vdut(existing_vdut, ...)` 与 cache binder 一样引用同一个 canonical object，不创建
port 或 topology connection。当前 profile 拒绝已有 executable backend 的 Vdut，因为 backend session 与
CHI participant session 尚不能共享同一份动态 payload state；把一个 AXI/APB Memory Vdut 直接传入会制造
双 authority。`ChiAddressHomeNode(AddressTarget)` 仍只是 direct `ReadNoSnp` adapter。若场景要求观察
physical commit，应显式增加 HN→SN 的 REQ/DAT/RSP、SN participant 和 system witness，不能把本地 reference
backing commit 冒充该网络事务。

后续 cache 功能按以下边界加入：

| 内容 | 状态权威 | 说明 |
|---|---|---|
| stable line presence/data | protocol-neutral CacheLineStore | cache storage 的唯一 payload 事实 |
| CHI permission、local dirtying | Cache VirtualDut 的 CHI participant | 权限变化受 coherence lifecycle 约束 |
| victim selection | 可选 replacement policy | eviction 是 cache 的本地决策，LRU 只是其中一种策略 |
| same-line transient、等待者合并或 block/replay、writeback slot | Cache VirtualDut participant resource | 影响是否能接纳本地请求或 Snoop |
| `CleanUnique`/`MakeUnique`/`WriteBackFull` 的字段与单 transaction correlation | CHI representation 与完整逻辑接口合同 | 这些是协议通信形式 |
| Home backing payload | protocol-neutral `FullLineBackingCore` / `LineBackingState` | prepared line-local commit 只闭合 reference authority；独立 Memory/SN physical commit 尚未建模 |
| Home sharer/owner、shared-dirty owner 与跨 RN invariant | Home participant + CHI SystemProtocol monitor | directory 的局部状态由 Home 持有，跨 participant 一致性由 system 判定 |
| packet/flit、L-Credit 和 hop backpressure | CHI transport | 不解释 cache permission |

当前 `coherence_transaction_capacity` 约束 RN 共享的 coherence/writeback pending 数量；Home 的 coherence 与
writeback pending 也共享 transaction capacity 和 DBID allocation space。它们可以承担“有限 outstanding
coherence lifecycle”的验证语义，但不宣称等于一种 RTL MSHR 组织。完整 MSHR 通常还记录同地址等待者、
原稳定态、返回数据/ack、post-invalidate/post-downgrade 等 transient 信息；只有当场景需要验证并发接纳、
合并、背压或进度时才应把这些字段加入 participant。dirty victim 的写回队列同理，应作为独立有限资源，
不与 read-miss slot 被动合并成一个含义模糊的容量。

当前每个 RN cache line 同时只允许一个本地 coherent lifecycle；同地址第二笔本地请求被 block。允许的
具名 Snoop 重叠包括：pending `ReadUnique` 收到同址 `SnpUnique` 时，`I` 保持 absent、`SC` copy 被失效，
`I` 或 `RetToSrc=0` 返回 `SnpResp_I`，`SC` 且 `RetToSrc=1` 返回携带原 payload 的
`SnpRespData_I`；pending transaction 与 Request-Retry ledger 原样保留，后续 `CompData_UC` 再安装完整
payload 和 `UC` permission。pending `CleanUnique` 收到同址 `SnpUnique` 时采用相同响应区分，收到
`SnpCleanInvalid` 时返回 `SnpResp_I`；两者都先失效为 `I` 并保留 CleanUnique pending，后续 `Comp_UC`
形成无 payload 的 `UCE`。`UCE` 遇到 invalidating Snoop 即返回无数据 `SnpResp_I` 并进入 `I`，即使
`RetToSrc=1` 也不伪造 DAT。pending MakeUnique 收到同址
`SnpUnique`/`SnpCleanInvalid`/`SnpMakeInvalid` 时也先进入 `I`，但保留独立的 RN-local store intent；
自己的 `Comp_UC` 随后仍原子安装该 intent 为 `UD`。pending clean Evict 本来已经是无 payload `I`，
收到同址 Snoop 时返回 `SnpResp_I` 并保留 Evict correlation。`WriteBackFull` pending 则以
`ChiRnWriteBackPending.outcome` 显式区分
`LIVE_UD` 与 `CANCELED_I`：前者保留 resident `UD` payload；收到同址 `SnpUnique` 或
`SnpCleanInvalid` 时以 `SnpRespData_I_PD` 交出 dirty payload；收到 `SnpMakeInvalid` 时则按
MakeUnique profile 丢弃旧 dirty payload 并只返回 `SnpResp_I`。两类路径都转为无 payload 的 `I` 并保留原
WriteBack request/TxnID correlation。之后收到 `CompDBIDResp`，`LIVE_UD` 产生
`CopyBackWrData_UD_PD` 并转 `I`，`CANCELED_I` 则产生 data 与 byte-enable 均为零的
`CopyBackWrData_I`；两者都退休 RN pending。

这里闭合的顺序是 Snoop response 完成后，Home 才给出 `CompDBIDResp`，RN 再发送 DAT。CopyBack
WriteData 是 implicit `CompAck`；Home 发出 completion 后必须等 DAT 才能发新的同址 Snoop，因此本切片
不注入绕过该顺序的 post-`CompDBIDResp` Snoop。

late WriteBack REQ 在前一同址 transaction 完成前仍由 Home line reservation block/replay。若它在
CleanUnique 已提交新 owner 后到达，packet-delivery `ChiCoherenceSession` 只有在 source RN 仍持有精确匹配
的 request/TxnID、outcome 为 `CANCELED_I`、line 为无 payload `I`，且旧 source 已不在当前 directory
authority 中时，才派生 `SNOOP_CANCELED` Home admission。该 admission 是 SystemProtocol 跨 participant
核对出的内部证据，不是 `WriteBackFull` wire field；独立 Home participant 不能从一笔 non-owner REQ
自行推断。Home 为 normal/canceled admission 都保存接纳时的 directory snapshot 与 backing version；
cancel DAT 只能是 `CopyBackWrData_I`，校验 snapshot/version 后仅释放 DBID，拒绝迟到的
`CopyBackWrData_UD_PD`。一般 I→S、S→U 等等待阶段仍未编码成完整 transient 状态机。

Home 的 coherent pending、Home writeback pending、RN coherent pending 与 RN writeback pending 分别可由
`project_progress()` 投影为 held line，其 release event 记录为 `CompAck`、`CopyBackWrData`、
`Comp`/`CompData` 与 `CompDBIDResp`。waiting 只枚举当前 transport endpoint head 且 demand 命中这些
exact resource 的 packet；`project_wakeups()` 比较前后快照给出 holder release evidence。该投影仍留在
CHI family，不生成 wait-for edge、公平性结论或 deadlock verdict。

因此 MSHR 和 write buffer 与一致性有关，但不是 MESI/MOESI 的协议状态本身。MESI 的正确性至少需要 line
permission、dirty responsibility、Home authority 和 transaction lifecycle；替换算法、set associativity
以及精确 MSHR 微架构可以留作可选的 Cache VirtualDut refinement。

## 10. 首版可执行场景

首个场景采用一个 requester、一个 Home、两个 clean Snoopee 和调用方声明的有限 XP topology：

```text
RN0 requester ──► XP0 ──► XP1 ──► HN0 + clean memory
                    │       │
                    ▼       ▼
                   RN1     RN2
                 Snoopee  Snoopee
```

实际源码仍使用有向 connection 表达每个方向；图中的线只概括连接关系。构造期应闭合：

- RN0 → HN0：REQ；
- HN0 → RN0：DAT；
- RN0 → HN0：RSP/CompAck；
- HN0 → RN1、RN2：SNP；
- RN1、RN2 → HN0：RSP/SnpResp 或 DAT/SnpRespData。

核心 witness 使用 `ReadUnique`：

```text
RN0 ReadUnique
  → multi-hop REQ
  → HN0 emits SnpUnique to RN1 and RN2
  → each peer becomes I and returns SnpResp_I
  → HN0 aggregates both responses
  → multi-hop CompData_UC to RN0
  → RN0 becomes UC and returns CompAck
  → stable directory names RN0 as the unique clean holder
```

同一构造方法另保存 MakeUnique 的 dirty-peer resolved witness：

```text
RN0 MakeUnique + RN-local full-line store intent
  → HN0 sends SnpMakeInvalid to dirty RN1
  → RN1 discards its payload, becomes I, returns SnpResp_I
  → HN0 sends Comp_UC to RN0
  → RN0 atomically installs the intent as UD and returns CompAck
  → HN0 commits RN0 as unique owner; backing payload/version stay unchanged
```

endpoint accept 顺序恰为 REQ、SNP、SnpResp RSP、Comp RSP、CompAck RSP 五个 packet；resolved route
集合不含 DAT。该 witness 同时证明 participant capability、feature/flow closure 与 topology transport，
不把 submit API 的 store intent 冒充线上 payload。

同一 resolved 装配另保存预侦听 NDERR 的三 packet witness：

```text
RN0 ReadUnique
  → HN0 reserves DBID and emits no SnpUnique
  → CompData_I(NDERR) crosses XP0 to RN0
  → RN0 keeps its original cache state and returns CompAck
  → HN0 releases DBID without changing directory/backing
```

这个 modifier 复用 base feature 已证明的 REQ/DAT/CompAck 以及构造期 SNP/RSP flow；“本次没有实际
Snoop packet”不等于删掉 base lifecycle 的 topology contract。当前 Home policy 与 modifier 必须成对启用。
这个三 packet witness 本身不声称
`RetryAck/PCrdGrant→credited reissue→CompData_I(NDERR)`、同一 accepted request 已发出 Snoop 后的
failure 或 DERR；Retry 组合由下文的独立 witness 闭合。

同一装配可再运行 `ReadShared`，验证 shared directory 更新。首版验收至少包含：

1. `ReadUnique` 双 Snoopee 的完整合法 witness；
2. `ReadShared` 的合法 witness；
3. `ReadNotSharedDirty` 将 `UD` owner 降为 `SC`、给 requester 建立 `SC`，并在 `CompAck` 后更新
   Home backing/directory；
4. Home 首跳容量只能容纳一份 SNP 时，完整 fanout 仍被保存并最终逐份送达；
5. 缺少一条 SNP 或 SnpResp/SnpRespData route 时，构造期产生明确 gap；
6. 错误 NodeID、角色或 endpoint port 在投递前被拒绝；
7. 最终 network/coherence 同时静止，stable monitor 通过；
8. 因果证据可以从根 Read 追到 Snoop 分支、CompData 和 CompAck；
9. MakeUnique dirty-peer 五 packet witness 没有 DAT，Ack 前仍持有 DBID/同址 reservation，Ack 后
   requester 为 `UD`、peer 为 `I`、backing payload/version 不变。

同一 XP 装配还保存一条 dirty-unique 定向 witness：

```text
RN1 UC --local write--> UD
RN0 ReadUnique
  → HN0 SnpUnique(RetToSrc=1) to RN1
  → RN1 SnpRespData_I_PD and becomes I
  → HN0 CompData_UD_PD to RN0
  → RN0 becomes UD and returns CompAck
  → directory.unique_owner=RN0; Home backing remains the older value
```

这条 witness 检查“数据运输”和“dirty responsibility 转移”两个事实，不把 `PassDirty` 简化为普通
data-present 标记。

同一 participant/network 组合还保存一条 MESI no-SD 五 packet witness：

```text
RN1 UC --local write--> UD
RN0 ReadNotSharedDirty
  → HN0 SnpNotSharedDirty(DoNotGoToSD=1, RetToSrc=1) to RN1
  → RN1 SnpRespData_SC_PD and becomes SC
  → HN0 pending accepts dirty data and sends CompData_SC to RN0
  → RN0 becomes SC and returns CompAck
  → HN0 commits backing; unique_owner=None; sharers={RN0,RN1}
```

它固定了“dirty 数据回到 Home 后再形成 clean shared copy”的责任终点，并以五份 protocol packet
覆盖 REQ、SNP、DAT、DAT 和 RSP。当前 Home 固定选择吸收 PassDirty 并返回 `CompData_SC`，这是规范
允许结果的受限子集。它没有建立 `SD`，也不能替代下面独立 writeback lifecycle 对 DBID 与提交时点的检查。

受限 shared-dirty CleanUnique 另保存一条五 packet witness：

```text
RN0 holds SC; RN1 holds restricted SD(new data)
directory.sharers={RN0,RN1}; shared_dirty_owner=RN1
RN0 CleanUnique
  → HN0 SnpCleanInvalid(DoNotGoToSD=1, RetToSrc=0) to RN1
  → RN1 SD→I and SnpRespData_I_PD(new data)
  → HN0 pending.dirty_result captures data and prepares a backing write
  → HN0 Comp_UC; RN0 SC→UC and returns CompAck
  → HN0 commits reference backing=new data, unique_owner=RN0,
    sharers={}, shared_dirty_owner=None
```

这条 witness 只证明 Home participant 已接管 dirty 数据、同址事务在旧 backing 不可观察期间被 reservation
挡住，并在 `CompAck` 后以协议中立 line commit 与 directory transition 更新 reference state。它没有产生
topology-visible HN→SN write，也不证明独立 Memory VirtualDut 的 physical commit。

participant packet-delivery session 还闭合了第一条 dirty writeback：

```text
RN holds UD
  → WriteBackFull(TxnID=A)
  → Home reserves DBID=B and returns CompDBIDResp(TxnID=A, DBID=B)
  → RN becomes I and sends CopyBackWrData_UD_PD(TxnID=B)
  → Home commits the latest data, clears unique_owner, and releases DBID=B
```

这里实现的是显式提交一条已选择的 `UD` line；victim selection、LRU、自动 eviction trigger 和 writeback
queue scheduling 仍属于可选 Cache VirtualDut refinement。完整 lifecycle 已在 packet-delivery session
以及 resolved XP topology/network 中运行：后者从 feature/capability 证据闭合 Requester↔Home 的
REQ/RSP/DAT route，保存三份 packet 的连续 lineage，并检查 Home backing/DBID 与 RN `UD→I` 的最终提交。
RN cache behavior 通过 canonical binder 绑定调用方已有 VirtualDut；binder 不创建 port 或 connection，
网络仍由 SystemProtocol construction 显式声明。

direct packet-delivery session 另闭合了 WriteBack cancel 与 CleanUnique 的组合：

```text
old RN holds UD and emits WriteBackFull(TxnID=A), but its REQ is delayed
  → new RN issues CleanUnique(TxnID=C)
  → Home sends SnpCleanInvalid to old RN
  → old RN sends SnpRespData_I_PD, becomes CANCELED_I, retains TxnID=A
  → CleanUnique completes; Home commits the dirty data and new owner becomes UCE
  → delayed WriteBackFull reaches Home with system-derived SNOOP_CANCELED evidence
  → Home snapshots the current directory/backing version and returns CompDBIDResp(DBID=B)
  → old RN sends CopyBackWrData_I(TxnID=B, Data=0, BE=0)
  → Home verifies the snapshot/version, releases DBID=B, and preserves new backing/owner
```

这条 witness 同时证明 dirty payload 只通过 Snoop response 转移一次、迟到 WriteBack 不会 stale-commit，
并拒绝以同一 DBID 伪造 `CopyBackWrData_UD_PD`。它使用 direct `ChiCoherenceSession` 中两个 requester；
当前 resolved construction 仍只派生一个 requester authority，因此不能据此声称一般多 Requester
topology 已闭合。

当前 cache-line 数据不分片，因此所有参与 coherence lifecycle 的 DAT route 都在打开 session 时检查为
512-bit。128/256-bit DAT connection 需要先提供 splitter/reassembler 和 fragment correlation，不能只因
NodeID/channel route 已闭合就宣称该场景可执行。

clean ReadUnique 现另有一次成功 Retry 的 modifier：
`ReadUnique→RetryAck→PCrdGrant→AllowRetry=0 重发` 之后复用本页既有 SnpUnique/CompData/CompAck
lifecycle。Home 拒绝阶段只建立 Retry debt；Grant 预留真实 transaction slot，credited reissue 原子消费
reservation 后才建立 coherence pending。direct packet-delivery 与单 XP topology witness 均覆盖该路径，
但 cancel 与多 waiter 仍延期。

Retry、独立同址 Snoop 与 pre-Snoop NDERR 现另有一条窄组合。direct 双 Requester witness 的顺序为：

```text
RN-A(SC) ReadUnique(A) → RetryAck，Home 不建立 pending/Snoop/DBID
  → RN-A waits for P-Credit
  → RN-B 的独立同址 ReadUnique 使 Home 向 RN-A 发送 SnpUnique
  → RN-A SC→I、SnpResp_I，并保留 A 的 pending/retry correlation
  → RN-B CompData_UC→CompAck，Home 提交 RN-B 为 unique owner
  → PCrdGrant；RN-A 以 AllowRetry=0/匹配 PCrdType 重发 A
  → Home 接纳后在 Snoop 前选择 CompData_I(NDERR)
  → RN-A 保持 I、返回 CompAck；RN-B owner 与 backing 不被回滚
```

初始 request 已被 `RetryAck` 拒绝，因此这里的 Snoop 只能归因于 RN-B 的独立 transaction；NDERR 只属于
credited reissue。组合不增加 feature key 或 wire form，而是同时选择现有 Retry/NDERR modifier，并使用
`ChiRequestRetryPhase × ChiCacheState` 表达正交状态。单 XP 另有六 packet witness：两份 REQ、
`RetryAck`、`PCrdGrant`、`CompData_I(NDERR)` 与 `CompAck`；两项 response 可以相互乱序，但都必须先于
credited REQ，且全程不产生 SNP。当前 Home 对尚未释放的同址 reservation 仍返回 `ResourceDemand`，
因此不能把该证据扩大成“credited REQ 在任意跨 channel 到达次序下均立即接纳”；那需要
accepted-but-waiting queue。同一 accepted request 已发出 Snoop 后的 failure、DERR/Snoop error 与
Retry cancel 也仍未实现。

展示产物优先包含一张 topology、一张简化 MSC 和一份最终 directory/cache-state 摘要。Link tick 等内部
microstep 保存在诊断记录中，无需全部放入主 MSC。

## 11. 延期能力

下列能力仍在当前切片之外：

- 自动 victim selection/writeback scheduling、deliberate dirty invalidate、
  WriteEvict family、CMO/DVM、等待者合并和一般 transient phase；
- MakeUnique Retry、DERR/NDERR、MTE Update、partial write 与 multi-Home 扩展；
- dirty writeback 与 RetryAck/P-Credit 或错误响应的组合，以及超出已闭合 invalidating-Snoop cancel 的
  其他 WriteBack/Snoop phase 组合；
- 让 Home participant 与独立 Memory/SN VirtualDut 通过 topology-visible protocol transaction 共同执行，
  以及相应 HN→SN physical write lifecycle；
- 完整 MOESI `SD`/Owned：当前只实现 seedable `SD→I` dirty-peer CleanUnique 出口，尚无 `SD` 生成、
  dirty `SnpShared`、owner handoff、forwarding snoop/DCT 或 shared-dirty replacement；
- 一般多 Requester resolved topology、多 Home、按每笔地址动态选择 authority，以及动态/多 scope
  coherence-domain membership；
- 一个 component/port 承载多个 NodeID 的运行时选择；
- 动态 snoop filter、router multicast 和 topology-wide broadcast；
- 独立 fanout branch admission、fanout continuation 及其额外 storage；
- message→multi-packet DAT splitter/reassembler、multi-flit response、narrow completion、DERR 与
  同一 accepted request 已发出 Snoop 后的 error completion；
- 多个 coherence Retry waiter、cancel、上述 post-Snoop error，以及超出上述窄 witness 的
  Retry/Snoop 到达次序；
- 多 waiter 公平性、跨资源 wait-for graph、escape transition 搜索和 deadlock verdict；当前
  `ChiCoherenceProgress` 只提供 family-local held/wait/wakeup evidence；
- virtual channel、adaptive route、QoS/fairness property 和 deadlock/livelock proof；
- raw packed bit codec、phit/lane、FLITPEND、pin waveform 和 cycle-accurate RTL timing；
- 自动生成 mesh/ring route table；
- 合并到通用根 `SystemSession` 或提炼“所有 NoC”共同的 runtime API。

这些延期项可以复用本页的 resolved route、原子候选和双状态组合原则。是否上提通用层，应等待第二种
真实协议或 switching model 提出相同的状态查询和生命周期。

## 12. 可执行资源与测试夹具

当前已经固化在 `protocol_model` 公共包中的资源包括 typed message/codec、RN/Home participant、
feature/capability/flow closure、packet-delivery coherence session 和 topology-backed network session。
它们不依赖某一个测试文件或固定拓扑。

调用方构造的单 XP 与 2×2 XP mesh 仍属于场景 recipe。2×2 showcase 是可执行的 clean ReadUnique 证据，
并由一个不发布 artifact 的 smoke test 调用；MESI no-SD 与受限 shared-dirty CleanUnique 路径当前保存在
定向 network witness 中。clean Evict 另有只含 REQ/RSP direct route 的两 packet resolved witness，
检查零 SNP/DAT/CompAck、Home 条件 holder removal、backing 不变与共同静止；其 Retry modifier 另有
初始 Evict、`RetryAck`、`PCrdGrant`、credited Evict、`Comp_I` 的五 packet resolved witness，检查
exact Retry response evidence、独立 feature/policy gate、零 SNP/DAT/CompAck 与共同静止。MakeUnique 另有
dirty-peer 五 packet resolved witness，检查独立 feature/capability/flow closure、
`SnpMakeInvalid` 的 dirty discard、零 DAT、`Comp_UC` 原子安装 RN-local intent 为 `UD`、Ack 前
DBID/line reservation、Ack 后 unique owner，以及 backing payload/version 不变。direct participant session
另有双 Requester CleanUnique 串行见证：第一笔
CleanUnique 失效第二个 requester 的 pending line，第二笔随后经 `Comp_UC` 获得 `UCE`，再以 full-line write
进入 `UD`；另一条 direct 双 Requester witness 组合 `CleanUnique + delayed WriteBack`，验证
`LIVE_UD→CANCELED_I→CopyBackWrData_I`、system-derived stale-owner evidence 与 Home
snapshot/version guard。它们不经过 resolved construction，因而不证明一般多 Requester topology。
前者不是通用 `MeshBuilder`，这些 witness 也尚未替代全部测试夹具。
下列内容仍需要保留在定向测试中：

- malformed identity、route、capability 与 feature dependency 负例；
- Home-produced exact SNP delivery evidence 的同 identity/opcode 替换与 post-completion replay 负例；
- fanout 在有限容量下的原子保存；
- orphan/重复 Snoop response、双 dirty owner、ReadUnique/SnpUnique 同址重叠、CleanUnique 对
  `SnpUnique`/`SnpCleanInvalid` 的同址重叠与 `UCE` 无 payload invariant，以及 WriteBack 同址
  invalidating Snoop 的 `CANCELED_I`、零数据 CopyBack retirement 与 stale-data rejection；
- Evict 的 clean→I issuance、stale Home hint、same-line `SnpResp_I`、early/forged/late completion
  correlation 与 backing/allocator 不变式；
- MakeUnique 的 expected/permitted requester 初态、任意已表示 peer state→`I`、零 DAT、丢弃 dirty
  payload、store-intent/completion correlation、`CompAck` 提交时点与 backing/version 不变式；
- clean 与 dirty participant 状态转换的局部诊断；
- `SD`/`shared_dirty_owner` 对齐、DAT route/capability 和 reference backing 提交时点；
- coherent pre-snoop NDERR 的零 SNP、状态不变与 DBID/CompAck 定向生命周期；
- coherent Retry/P-Credit 尚未进入公开 showcase 的定向生命周期。

测试只有在对应公共入口或 showcase 已被自动 smoke test 调用，并保留等价的负例与原子边界证据后才适合
缩减。`showcase/generated` 的既有 PASS 快照只代表一次发布结果，不能单独替代可执行检查。
