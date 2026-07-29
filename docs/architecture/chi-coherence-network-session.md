# CHI coherence 与 transport-network 的组合 session

[CHI Issue H 源码导航](../../protocol_model/protocols/amba/chi/issue_h/README.md) ·
[网络构造](network-construction.md) ·
[通信建模的三张视图](communication-scope-and-transport.md) ·
[当前实现状态](implementation-status.md) ·
[Roadmap](technical-route/08-roadmap.md)

本文定义 `ChiCoherenceNetworkSession` 的稳定组合方法：已解析的 CHI participant、authority、route 与
transport profile 共同打开一个可执行 session；Requester、Home 与 Snoopee 产生的 packet 经固定 topology
运输，直到 transaction、network 和 coherence state 共同静止。

具体 feature 数量、已完成 witness 和近期候选随实现演进，统一由
[实现状态](implementation-status.md) 和
[Roadmap](technical-route/08-roadmap.md) 维护。本文保留对象、owner、构造闭合、原子提交和 profile contract。

规范依据：

- [Arm AMBA CHI Architecture Specification, Issue H](https://developer.arm.com/documentation/ihi0050/h)
- [Arm AMBA CHI Issue H Errata](https://developer.arm.com/documentation/aes111415/latest)

## 1. 适用范围与决策性质

| 性质 | 含义 | 本文示例 |
|---|---|---|
| 协议要求 | message lifecycle、identity、channel、ordering 与 completion 的合法关系 | TxnID/DBID correlation、PassDirty data、CompAck、Retry/P-Credit |
| 架构边界 | Protocol Model 对状态 owner 与 handoff 的稳定分配 | participant state、transport state、system authority 和 monitor ledger 分开保存 |
| profile 选择 | 一个可执行切片声明的状态、字段、容量和 feature 组合 | scalar Home、有限 Requester/Snoopee、512-bit full-line DAT、clean DCT |

profile 扩展通过 feature、capability、flow、authority 和 route closure 接入同一组合方法。

## 2. 目标对象与边界

```text
SystemProtocol topology + Chi authority/features + participant bindings
                              │ resolve
                              ▼
                       ResolvedChiSystem
                       ├─ identity plan
                       ├─ authority plan
                       ├─ capability/flow closure
                       └─ transport plan
                              │ open
                              ▼
                  ChiCoherenceNetworkSession
                  ├─ ChiCoherenceSession
                  ├─ ChiTransportNetworkSession
                  └─ family scheduler
                              │
                              ▼
              state + trace + progress + stable verdict
```

| 对象 | 输入 | 持有的事实 | 输出与交接 |
|---|---|---|---|
| `ResolvedChiSystem` | topology、feature intent、authority、participant offer | NodeID ownership、Home/domain、role、capability 与 flow closure | session 的不可变构造证据 |
| `ChiCoherenceSession` | delivered typed packet、participant action | RN cache、Home directory/backing、pending transaction、DBID 与 Snoop aggregation | participant state 与 outbound packet batch |
| `ChiTransportNetworkSession` | packet、resolved hop、Link action | activation、per-channel L-Credit、FIFO、reservation、router 与 hop lineage | endpoint delivery 与 transport state |
| `ChiCoherenceNetworkSession` | 两个子 session、route/delivery index、scenario action | 原子组合状态、pending egress、调度 cursor 与跨 packet evidence | accepted step、blocked demand、fault、trace 和 quiescence |
| system monitor / analysis | authority、事件、资源投影 | reference coherence ledger 与派生关系 | invariant verdict、wait-for 或 progress evidence |

`ChiDeliverCoherencePacket` 继续服务 participant 级定向测试；topology-backed 场景通过 transport session
完成 packet delivery。

## 3. 构造期输入

组合 session 从 `ResolvedChiSystem.require_closed()` 成功的结果打开。resolver 按以下顺序闭合输入：

| 输入 | 闭合内容 | 结果 |
|---|---|---|
| feature intent | dependency、role cardinality、participant capability、lifecycle requirement | enabled feature set |
| `ChiCoherenceAuthorityContract` | address claim、scalar Home、coherence domain、eligible requester/peer | authority plan |
| participant bindings | transaction/forwarding facet、NodeID、transport ports | identity plan |
| `DirectedTransportConnection` | channel support、direction、profile 与逐 hop capability | flow projection |
| Home/Cache boundary projection | line width、backing、directory、clean residency 与 capacity | executable participant binding |

当前 coherence profile 为一个 feature address scope 选择一个 scalar Home。resolver 从 coherence domain
派生有限 Snoopee set，并核对：

1. Home、Requester 与 domain member 的 NodeID ownership；
2. Home 初始 directory holder 全部位于 resolved domain；
3. 每条启用 lifecycle 的 REQ/RSP/SNP/DAT flow 都有唯一有向 path；
4. path 的首末端口属于相应 participant binding；
5. 每一 hop 支持所选 channel、Resource Plane 和 DAT width；
6. operation address 落在 authority claim window；
7. feature 的 policy、capacity 和 state owner 已显式提供。

System authority 是 address→Home、domain membership 与 NodeID assignment 的来源。RN 的
`home_node_id`、Home/router 的 route 配置和 directory 初态是经过 resolution 核对的 boundary projection。

### 3.1 不可变 route 与 delivery 索引

构造期从 `ChiFlowProjection` 生成两个只读索引：

```text
outbound route
  (source NodeID, target NodeID, channel) -> ordered connection path

endpoint delivery
  (last connection, receiver port, channel) -> target participant
```

每个 key 对应唯一可执行 path。route 逐项核对 source/target identity、首末端口、channel 和 router 的
`channel + target_id` next-hop 选择。runtime 直接查询该索引。

SNP protocol message 保持规范字段集合；Snoopee 选择进入 packet route identity。Home 为每个目标建立独立
`ChiNetworkPacket`，并将 `target_id` 写入 route index。Fanout packet copy 与一条 message 的
multi-packet fragmentation 使用不同 identity。

## 4. Transaction、message、packet 与 flit handoff

```text
operation
  └─ transaction lifecycle
       └─ typed REQ/RSP/SNP/DAT message
            └─ ChiNetworkPacket
                 └─ ChiProtocolFlit
                      └─ one directed Link hop
```

| 形式 | owner | 关键事实 | 交接 |
|---|---|---|---|
| transaction | interface/participant ledger | request、response、completion、TxnID/DBID、Retry phase | participant transition |
| protocol message | CHI representation | opcode、规范字段、channel 与 response state | packetizer |
| network packet | CHI network representation | source/target NodeID、channel、copy/fragment identity | route 与 router |
| protocol flit | transport session | 当前 Link 的 channel、activation、L-Credit 与 capture | receiver 或 router |
| phit/pin sample | observation/external integration | physical transfer 与采样 | normalized Link observation |

Issue H profile 使用 packet、protocol flit 和 phit 一对一的运输粒度，同时保留三个对象各自的 owner。
`LCrdReturn` 从 flit 层开始，在相邻 transmitter/receiver 之间归还 Link resource。

### 4.1 Identity、credit 与 completion

| 资源或 identity | owner | key 与释放条件 |
|---|---|---|
| original TxnID | Requester/interface transaction ledger | 关联 initial request 与 response/completion |
| Home DBID | Home participant + operation ledger | 关联后续 DAT 或 `CompAck`，按 terminal 释放 |
| P-Credit | Request-Retry ledger | `(Requester NodeID, PCrdType)`；credited reissue 原子消费 |
| L-Credit | 每条 directed Link 的 channel runtime | channel + Resource Plane；flit drain/return 后恢复 |
| NodeID | system identity plan + packet | resolution 闭合 ownership，packet 携带 route identity |
| address/Home | system authority plan | claim + feature scope + domain |

P-Credit 与 L-Credit 必须使用独立的 key、capacity 和 retirement 条件。P-Credit 负责 protocol request
admission；L-Credit 负责当前 hop 的 flit admission。

Original TxnID 与 Home DBID 也是两个独立 correlation domain。`CompDBIDResp` 或 combined response
授予 DBID 后，Requester 用 DBID 发出 data/ack，并按 operation contract 继续使用 original TxnID。
typed `ChiCopyBackPhaseLedger` 记录：

```text
HOME_RESPONSE(original TxnID)
  → REQUESTER_DATA(Home DBID)
  or REQUESTER_ACK(Home DBID)
  → terminal retirement
```

data terminal 与 no-data terminal 由 operation 和 phase 精确选择。packet evidence 一次性消费完整字段、
source/target、channel、TxnID/DBID 和 phase；altered field、stale backing version 与 replay 在 participant
state 提交前形成 fault。

协议护栏：Home 发出 `Comp` 或 `CompDBIDResp` 后，禁止在 terminal DAT 或 `CompAck` 到达前接纳新的同址
Snoop。PassDirty 必须随 `SnpRespData` 和实际 data 同行；一笔 transaction 至多接收一个 PassDirty source。

### 4.2 Transport 原子帧

一条 connection 共享 Link activation，REQ/RSP/SNP/DAT 分别持有 FIFO、receiver reservation 与 L-Credit。
一个 `AtomicFrame` 中启用的 channel 统一提交或回滚。这里的 transport frame atomicity 与 CHI returning
Atomic operation 是两项独立合同。

## 5. 组合状态

| 字段 | 状态 owner | 用途 |
|---|---|---|
| `coherence` | `ChiCoherenceState` | RN/Home participant、directory、backing 与 transaction |
| `network` | `ChiTransportNetworkState` | connections、router、Link resource 与 lineage |
| `pending_egress` | composition session | 一次 participant transition 产生的完整 packet batch |
| `scheduler_cursor` | composition session | 有限候选的 round-robin 起点 |
| `committed_microsteps` | composition session | 有界运行和诊断计数 |

route/delivery index、role registry、enabled feature 和 authority plan 属于 session 的不可变构造结果。

### 5.1 跨 packet 因果证据

Home pending transaction 是 fanout 与 join 的行为权威：

```text
(Requester NodeID, Requester TxnID)
  ├─ accepted request
  ├─ snoop branch[target NodeID]
  │    ├─ emitted SNP
  │    └─ delivered SnpResp or SnpRespData
  ├─ optional forwarded-data branch
  └─ completion / CompAck
```

transport lineage 记录 packet 经过的 connection；composition lineage 在 endpoint accept 与 participant
egress 处继续追加。transaction-level causal view 只保存事件引用，Home pending 继续决定 completion gate。

## 6. 小步调度与原子提交

family scheduler 枚举以下候选：

1. operation submit：Requester transition 产生 REQ packet batch；
2. egress admission：batch 头按静态 route 进入首 hop；
3. Link tick：推进 activation、credit 与 flit transfer；
4. capture→router：把 receiver capture 原子交给 router FIFO；
5. router service：按 `channel + target_id` 进入 downstream connection；
6. endpoint delivery：核对 delivery index，执行 participant transition，保存新 batch 并 drain capture。

候选按 round-robin cursor 尝试。scenario 可以选择具名候选控制合法交错；candidate 名称表示模型提交顺序，
trace 中的时间或 latency 由独立时间语义提供。

### 6.1 原子提交

每个候选先在不可变快照上计算：

```text
delivery = network.peek_delivery(...)
participant_step = coherence.deliver(delivery.packet)
egress_batch = validate_and_save(participant_step.emissions)
network_step = network.drain(delivery)

commit(participant_step.state, network_step, egress_batch)
```

| 结果 | 组合语义 |
|---|---|
| success | coherence、network、pending egress、scheduler cursor 与事件一次替换 |
| `BLOCK` | 原状态保留，返回最具体的 `ResourceDemand` |
| fault | 原状态保留，返回带 participant/connection/phase 位置的诊断 |
| route/identity gap | construction/system fault，packet 继续由原 owner 持有 |

该提交边界保证 participant state 与全部 outbound packet 同时取得 owner，也保证 endpoint capture 只在
participant 成功接纳后 drain。

### 6.2 多 Snoopee fanout

fanout 使用“整批保存、逐 packet admission”：

1. Home transition 一次确定完整目标集合；
2. composition 核对每个目标的 identity 和 route；
3. Home state 与完整 immutable packet tuple 原子进入 `pending_egress`；
4. 后续 microstep 按 path capacity 接纳 batch 头；
5. blocked packet 保留在 batch，其他 Link/router 候选继续推进；
6. batch 清空后开放下一项 participant output。

该 policy 在有限首跳容量下保留全部 Snoop branch。扩展为多个并行 continuation 时，需要显式增加
per-target issued/accepted ledger、有限 storage 和 wait-for projection。

### 6.3 共同静止与 progress

共同静止同时满足：

- `ChiCoherenceSession.is_quiescent(coherence)`；
- `ChiTransportNetworkSession.is_quiescent(network)`；
- `pending_egress` 为空；
- coherence stable monitor 通过。

`project_progress()` 只读派生 `ChiCoherenceProgress`：Home/RN pending 投影为 `ChiHeldLine`，endpoint
head 的匹配 `ResourceDemand` 投影为 `ChiLineWait`。`project_wakeups(before, after)` 在 exact holder
释放且对应 wait 消失时形成 `ChiLineWakeup`。system analysis 再把这些投影组合为 wait-for、fairness 或
deadlock/livelock verdict。

## 7. Home、Requester、Snoopee 与 directory state

| 事实 | owner | 稳定含义 |
|---|---|---|
| resident payload | protocol-neutral `CacheLineStore` / `CacheCore` | line presence、install 与 removal |
| RN permission | CHI Requester participant | `I/SC/UC/UCE/UD` 与受限 `SD`、local dirtying |
| RN transaction | Requester pending ledger | TxnID、Retry phase、store intent、CopyBack outcome |
| directory | Home participant | `unique_owner`、`sharers`、受限 `shared_dirty_owner` |
| reference backing | `FullLineBackingCore` / `LineBackingState` | payload、version 与 prepared/committed write |
| Snoop-domain clean residency | Home 的独立 `CacheCore` | fixed retain 与 CopyAtHome current-copy predicate |
| Snoop result aggregation | Home pending transaction | target set、clean response、dirty result 与 completion gate |
| global invariant | system monitor | holder/permission/data 与 authority 的跨 participant 一致性 |

`ChiHomeDirectoryEntry` 保存 holder identity；reference payload 由 backing core 保存。Home 以
`prepare_write + expected version → commit_write` 提交 line-local 更新，使 backing、directory 和 pending
retirement 在一个不可变 transition 中闭合。

### 7.1 MESI/MOESI 与 Dirty/Owned profile

基线稳定态为：

| 状态 | payload | authority / responsibility |
|---|---|---|
| `I` | absent | 无 holder authority |
| `SC` | present | clean shared holder |
| `UC` | present | clean unique holder |
| `UCE` | absent | unique authority；首次 full-line local write 安装 payload |
| `UD` | present | unique holder + dirty responsibility |
| 受限 `SD` | present | shared holders 中唯一 dirty responsibility owner |

stable monitor 要求：

- 有 payload 的 clean copy 与 Home backing 匹配；
- `UCE` payload 为空且对应 directory unique owner；
- `UD` 是唯一 holder；
- 受限 `SD` 与 directory 的 `shared_dirty_owner` 一一对应。

Dirty 表示“最新数据相对 Home backing 的新旧关系与最终写回责任”。责任可以通过
`SnpRespData_*_PD`、`CompData_*_PD` 和 Home pending 在 participant 间转移。Home 收到 dirty data 后先
持有 prepared write，按 lifecycle 的 terminal 时点提交 backing 与 directory。

当前 no-SD MESI profile 以 `UD → SnpRespData_SC_PD → Home pending → CompData_SC → CompAck`
把 dirty responsibility 收回 Home，并形成 clean sharers。受限 `SD` 服务 dirty-peer CleanUnique 的显式
输入与失效路径。完整 `SD`/Owned profile 另需 shared-dirty 生成、dirty `SnpShared`、owner handoff 和
owner eviction/recovery；这些扩展拥有独立 feature 与 policy。

Direct Cache Transfer 依赖 forwarding transaction、clean peer capability 与 Home join。它和
`SD`/Owned coherence-state profile 沿两条独立依赖链组合。

### 7.2 Cache VirtualDut 与 transient 资源

Cache assembly 采用 core-first 构造：

```text
CacheLineStore
  → CacheCore
  → attach_chi_issue_h_coherence()
  → CHI-attached Cache VirtualDut
       ├─ REQ/RSP/DAT transmitter ports
       ├─ RSP/SNP/DAT receiver ports
       └─ ChiCoherentRnNode transaction facet
```

`bind_chi_issue_h_cache_vdut(existing_vdut, ...)` 把 facet 绑定到调用方已有的 canonical object，保留同一
port、connection 和 topology identity。

Home assembly 采用对应结构：

```text
FullLineBackingCore
  → attach_chi_issue_h_home()
  → CHI-attached Home VirtualDut
       ├─ RSP/SNP/DAT transmitter ports
       ├─ REQ/RSP/DAT receiver ports
       └─ ChiCoherentHomeNode
            ├─ directory
            ├─ pending transaction + DBID
            └─ prepared backing obligation
```

`coherence_transaction_capacity`、Home DBID space、same-line reservation 和 CopyBack slot 是有限
participant resources。MSHR、waiter merge、victim selection、replacement 和 writeback scheduling 作为
Cache VirtualDut policy/refinement 接入，并公开相应 capacity 与 progress projection。

## 8. Profile construction

一个可执行 feature 以同一 schema 声明：

| 项 | 作用 |
|---|---|
| role/cardinality | Requester、Home、Snoopee 或 forwarding peer 的数量与绑定 |
| dependency | base lifecycle、modifier、state policy 与共同 Home owner |
| participant capability | message accept/produce、state effect、capacity 与 local policy |
| flow requirement | source/target role、channel、message family 与 path capability |
| system lifecycle fact | 跨 participant ordering、commit point、authority effect 与 invariant |
| witness | direct 或 topology-backed legal trace、negative boundary 与最终 stable state |

`resolve_chi_system()` 对这些项取闭包，然后把 resolved result 交给 lifecycle session。完整 built-in catalog、
逐 feature 状态与证据入口见
[实现状态](implementation-status.md) 和
[CHI Issue H 源码导航](../../protocol_model/protocols/amba/chi/issue_h/README.md)。

### 8.1 Clean ReadShared Direct Cache Transfer

clean DCT 是 ReadShared base lifecycle 的可选 modifier：

```text
Requester ReadShared(TxnID=A)
  → Home SnpSharedFwd(TxnID=B, FwdNID=Requester, FwdTxnID=A)
      to one clean UC forwarding peer
  → peer CompData_SC(TxnID=A, DBID=B) to Requester
  → peer SnpResp_SC_Fwded_SC(TxnID=B) to Home
  → Requester CompAck(TxnID=B) to Home
```

profile closure 包含：

1. forwarding peer 来自 resolved authority domain，NodeID 与 requester 分离；
2. `SnpSharedFwd` 使用 clean、单 peer、`RetToSrc=0` profile；
3. peer `UC→SC` 并直接提供最新 payload，requester `I→SC`；
4. peer DAT 与 forwarded RSP 使用独立 channel，各 hop 独立消费 L-Credit；
5. `Resp` 与 `FwdState` 保持两个 typed field；
6. Home 分别保存 exact forwarded response 与 `CompAck`，接受两种到达顺序；
7. join 完成前冻结 directory/backing，join 完成后一次提交两名 sharer；
8. base Home→Requester DAT path 继续提供 Home-data fallback。

该 modifier 已闭合 `SnpSharedFwd`、peer `CompData_SC`、`SnpRespFwded` 与 `CompAck` 的双输入乱序 join。
当前 profile 选择 clean、单 peer 与 `RetToSrc=0`；dirty DCT、`RetToSrc=1`、动态多 peer 和一般 forwarding
catalog 由后续 profile 扩展。DCT 的 forwarding dependency 与 `SD`/Owned state dependency 分开闭合。

### 8.2 Returning Atomic

`ChiAtomicSwapMessage` 与 `ChiAtomicLoadAddMessage` 分别选择 `AtomicSwap` 和 `AtomicLoad ADD`。
两个 operation 使用共同的参数化 Requester/Home、backing、DBID 和 same-line runtime：

```text
REQ(TxnID=A)
  → DBIDResp(DBID=B)
  → NonCopyBackWrData(TxnID=B)
  → CompData_I(TxnID=A, old value)
```

当前两个 operation profile 共同声明：

| 维度 | Profile |
|---|---|
| Size | `0..3`，即 1/2/4/8 byte |
| address | 自然对齐 |
| byte order | little-endian |
| memory/system attributes | `PAS=0`、Normal Non-cacheable、`SnpAttr=0/SnoopMe=0` |
| DAT placement | Addr/Size 派生 natural lane、动态 byte enable、`CCID=original Addr[5:4]` |
| admission | 每次 issue/submit 显式提供 requester-line-`I` evidence |
| result | Home 提交新值，并把旧值返回 Requester |

Swap 执行 selected-width replacement；Load ADD 执行 fixed-width
`(old + operand) & mask`。Home 在 captured backing version 与 same-line reservation 下完成一次 immutable
read-modify-write。两个 operation 可以在同一 Atomic runtime 组合，line reservation 负责同址串行。
与其他 backing-owning lifecycle 组合时，resolver 要求一个共同 Home state owner。

`SnpAttr=0/SnoopMe=0` 界定当前窄 profile 的 admission；其他 CHI Atomic form 按各自 profile 声明。
early CompData、big-endian、SnoopMe/Retry/error、其他 Atomic operation 与完整组件能力的推进状态见
[实现状态](implementation-status.md) 和
[Roadmap](technical-route/08-roadmap.md)。

### 8.3 Coherence、CopyBack 与 completion

coherence feature family 共享以下稳定合同：

- clean Shared/Unique、MakeUnique、CleanUnique、Evict 和 CopyBack 分别声明自己的 flow 与 state effect；
- local full-line write 把 unique authority 与 payload 组合为 `UD`；
- dirty transfer 以 PassDirty data 移交最新 payload 与 responsibility；
- WriteBack、WriteEvictFull 和 WriteEvictOrEvict 通过 `ChiCopyBackPhaseLedger` 区分 operation 与 terminal；
- Home line reservation 覆盖 pending lifecycle，terminal 到达后释放；
- backing write 使用 captured version，成功时与 directory/pending retirement 原子提交；
- Snoop-canceled CopyBack 以具名 post-Snoop outcome 和零 data/byte-enable terminal 退休旧 correlation，
  并由 system-derived evidence 核对当前 authority。

具体 opcode、modifier 组合、CopyAtHome、Retry/NDERR 与同址 transient 覆盖统一由
[实现状态](implementation-status.md) 维护。

## 9. 可执行场景与验收

canonical witness 由 resolved topology 驱动，并至少核对以下关系：

| 维度 | 验收 |
|---|---|
| construction | identity、authority、feature dependency、participant capability 和每条 required flow 闭合 |
| route | 每份 packet 使用唯一 path，endpoint delivery 命中唯一 participant |
| fanout | 有限首跳容量下完整 target set 原子保存并最终逐份送达 |
| credit | P-Credit 与 L-Credit 分域；blocked step 保持原状态和 exact demand |
| correlation | exact packet evidence、TxnID/DBID phase、completion 与 replay guard |
| coherence | RN permission、Home directory/backing、dirty responsibility 与 stable invariant 一致 |
| DCT | peer DAT、forwarded response 与 CompAck 的乱序 join，join 前冻结、join 后单次 commit |
| Atomic | 四 packet route、lane/BE/CCID、old-value completion、RMW 与 same-line serialization |
| progress | coherence/network/pending egress 共同静止，unfinished obligation 形成可分析 evidence |
| provenance | trace 从 root operation 连接到 Snoop branch、completion、terminal 和最终 state |

场景可以采用 direct topology、调用方声明的 XP route、ring、mesh 或其他固定结构。Topology witness 证明所选
route、resource 与 quiescence；feature witness 另行证明 opcode lifecycle、state effect 和 invariant。

## 10. 可执行资源与测试夹具

稳定源码入口与本地维护回归索引由
[CHI Issue H 源码导航](../../protocol_model/protocols/amba/chi/issue_h/README.md) 维护。测试分层属于维护
工作区，不构成公开生产包对测试目录的运行依赖。

文档职责分工：

| 文档 | 负责内容 |
|---|---|
| 本文 | coherence network session 的对象、owner、闭合、调度、状态与 profile contract |
| [实现状态](implementation-status.md) | 当前 feature、codec、witness、明确缺口和证据入口 |
| [Roadmap](technical-route/08-roadmap.md) | 当前工作顺序、依赖与下一切片 |
| [Issue H 源码导航](../../protocol_model/protocols/amba/chi/issue_h/README.md) | 源码目录、lifecycle 文件、测试与公共入口 |
| [网络构造](network-construction.md) | protocol-neutral topology、construction、resolution 与 runtime 交接 |

Showcase 与发布快照从实际 runtime evidence 投影，服务演示与审计；可执行测试继续拥有正向 witness、负向
边界、原子回滚与 stable-state 验收。
