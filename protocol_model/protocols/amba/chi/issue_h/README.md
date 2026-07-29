# CHI Issue H 源码导航

本包实现 CHI Issue H 的 typed representation、transaction ledger、Link transport、participant behavior
和 topology-backed system composition。调用方先声明 VirtualDut、TransportPort 与有向 connection，再用
Issue H feature 和 authority contract 闭合可执行 lifecycle。

当前覆盖、明确边界与证据统一记录在
[实现状态](../../../../../docs/architecture/implementation-status.md)。本页维护稳定的源码职责、关键合同和
查找路径。

## 源码切面

```text
issue_h/
├── representation/   REQ/RSP/SNP/DAT message、logical-field record、packet 与 flit
├── interface/        transaction correlation、Retry/P-Credit、Write、Atomic 与 Exclusive ledger
├── transport/        Link activation、channel FIFO、L-Credit、connection 与 path runtime
├── participants/     RN/Home/router 的局部状态、行为、binding、facet 与 capability
├── system/           identity、authority、flow/capability resolution、network 与 lifecycle session
└── observation.py    Issue H runtime event 到通用 observation 的只读投影
```

| 目录 | 拥有的输入 | 产生的输出 | 主要交接 |
|---|---|---|---|
| [`representation/`](representation/) | operation 字段、channel 与 opcode | typed message、logical-field record、`ChiNetworkPacket`、`ChiProtocolFlit` | transport 消费 packet/flit，participant 消费 typed message |
| [`interface/`](interface/) | issue、response、completion 与 credit effect | immutable ledger state、result、下一条 protocol message | participant 保存节点局部实例，system 组合跨节点原子步骤 |
| [`transport/`](transport/) | packet、activation/channel sample 与 receiver capacity | hop-local transfer、blocked/fault、capture/drain evidence | network runtime 串接逐 hop delivery |
| [`participants/`](participants/) | packet delivery、局部 cache/backing/directory state | 新 participant state、outbound packet、capability offer | system resolution 闭合角色与路径，session 调度行为 |
| [`system/`](system/) | topology、NodeID/address/coherence contract、feature intent | resolved plan、network/session state、progress evidence | scenario/test 驱动已闭合的 runtime |
| [`observation.py`](observation.py) | Issue H runtime event | scope-neutral event projection | visualization、artifact 与 analysis 只读消费 |

包根 [`__init__.py`](__init__.py) 只公开 Issue H 身份。具体对象从对应切面的 leaf facade 导入；内部模块使用
叶模块 import，使聚合 facade 退出循环依赖路径。CHI participant 与 VirtualDut 的最终装配位于
[`integrations/recipes/amba/chi`](../../../../integrations/recipes/amba/chi/__init__.py)。

## Message、packet、flit 与 phit

```text
operation
└── transaction lifecycle
    └── protocol message
        └── one or more network packets
            └── one protocol flit per packet
                └── one phit per flit in Issue H
```

| 对象 | 保存的事实 | 代码入口 |
|---|---|---|
| protocol message | REQ/RSP/SNP/DAT opcode、TxnID/DBID、address、response 与 operation attributes | [`req.py`](representation/req.py)、[`rsp.py`](representation/rsp.py)、[`snp.py`](representation/snp.py)、[`dat.py`](representation/dat.py) |
| logical-field record | 规范字段名、逻辑类型、宽度与已登记 form 的精确字段集合 | [`logical_fields.py`](representation/logical_fields.py) |
| network packet | source/target NodeID、channel、message、packet index/count | [`packet.py`](representation/packet.py) |
| protocol flit | packet 在一条相邻 Link 上占用的 transport envelope | [`flit.py`](representation/flit.py) |
| link-maintenance flit | 当前 hop 的 activation/credit maintenance | [`domain.py`](representation/domain.py) 与各 channel 的 `LCrdReturn` |

`ChiIssueHChannelDomain` 先按 channel 与 representation kind 分类；REQ/RSP/SNP/DAT profile 再判定 opcode 和
字段组合。Logical-field codec 负责 typed message 的双向投影。Codec registry 表示可投影 form，channel
profile 继续作为 message 合法性的权威。

Snoop request 的选靶由 system/network 完成。每个 Snoopee 获得一份带明确 `target_id` 的 packet copy，
typed SNP message 保持规范字段集合。Fanout copy 使用 route identity；同一 message 的内容分片使用
`packet_index/packet_count`。这两类一变多保持独立。

Issue H 当前使用 packet、flit、phit 一对一的运输粒度。对象边界仍分别保存 route ownership、Link resource
lifecycle 与 physical observation。Packed bit offset、lane/pin lowering 和 multi-packet DAT 的
split/reassembly 进度见实现状态。

## Credit、correlation 与 completion

| 资源或身份 | Owner | 合同 |
|---|---|---|
| TxnID | interface transaction ledger | 关联原始 request 与 protocol completion |
| DBID | Home participant + transaction ledger | 授予 data buffer/lease，并关联后续 DAT 或 CompAck |
| P-Credit | Retry contract | Home 按 `(NodeID, PCrdType)` 授予 transaction-independent request capacity |
| L-Credit | directed Link/channel runtime | receiver 按 channel 与 Resource Plane 提供 flit capacity |
| NodeID | packet representation + system identity plan | packet 携带 route identity，resolution 闭合唯一 ownership |
| address/Home authority | system authority plan | 从 address claim、coherence domain 与 feature scope 派生 Home 和 eligible peer |

P-Credit 与 L-Credit 必须使用独立 key、capacity 和 retirement 条件。前者服务 protocol transaction
admission；后者服务相邻 hop 的 flit admission。

Original TxnID 与 Home DBID 是两个 correlation domain。Combined response 或 `DBIDResp` 授予 DBID 后，
Requester 使用 DBID 发送 data，同时按 lifecycle 继续用 original TxnID 等待 completion。DBID lease 的
释放点由具体 operation 决定；TxnID 复用不会接管仍在途的旧 DBID data phase。

Session 以 immutable packet 的字段值和 phase 做 correlation。Transport/trace 可以重建字段等价的对象；
可靠 delivery contract 负责抑制 wire-identical 的迟到副本。Altered field、错误 phase、错误 TxnID/DBID、
stale backing version 和 replay 在状态提交前得到拒绝。

当前 Home ordering 以 terminal DAT 或 `CompAck` 释放同址资源。Home 发出 `Comp` 或
`CompDBIDResp` 后，禁止在 terminal 到达前接纳新的同址 Snoop。

## Lifecycle 入口

Lifecycle 实现按同一顺序组合：

```text
typed message/profile
  → interface ledger
  → participant transition
  → feature/capability/flow resolution
  → packet-delivery or topology-backed system session
  → progress and quiescence evidence
```

| Lifecycle family | Ledger | Participant | System composition |
|---|---|---|---|
| direct read 与 Request Retry | [`read_no_snp.py`](interface/read_no_snp.py)、[`read_retry.py`](interface/read_retry.py)、[`request_retry.py`](interface/request_retry.py) | [`direct_home.py`](participants/direct_home.py)、[`address_home.py`](participants/address_home.py)、[`retry_home.py`](participants/retry_home.py) | [`read_no_snp.py`](system/read_no_snp.py)、[`read_no_snp_retry.py`](system/read_no_snp_retry.py) |
| Immediate `WriteNoSnp{Full,Ptl}` | [`write_no_snp.py`](interface/write_no_snp.py) | [`write_no_snp.py`](participants/write_no_snp.py) | [`write_no_snp.py`](system/write_no_snp.py) |
| returning Atomic | [`atomic.py`](interface/atomic.py) | [`atomic.py`](participants/atomic.py) | [`atomic.py`](system/atomic.py) |
| non-snoop Exclusive Ptl | [`exclusive.py`](interface/exclusive.py) | [`exclusive.py`](participants/exclusive.py) | [`exclusive.py`](system/exclusive.py) |
| coherent read、permission、CopyBack 与 DCT | transaction state 随 RN/Home participant 保存 | [`coherence.py`](participants/coherence.py) | [`coherence.py`](system/coherence.py)、[`coherence_network.py`](system/coherence_network.py) |

### Direct read 与 Retry

Direct read 闭合 `ReadNoSnp → CompData`。Address-backed Home 把地址访问结果映射为 `CompData` 或
`CompData_I(NDERR)`；system authority 负责 address window。

Retry 使用
`initial REQ → RetryAck → matching PCrdGrant → AllowRetry=0 credited REQ → completion`。
Requester 可在 Ack 与 Grant 到齐后用 `PCrdReturn` 取消 retained request。Grant 与 Ack 支持任一到达顺序；
credited reissue 在同一个原子步骤中消费 P-Credit 与 Home reservation。

### Immediate Write

```text
WriteNoSnpFull or WriteNoSnpPtl(TxnID=A)
  → CompDBIDResp(TxnID=A, DBID=B)
  → NonCopyBackWrData(TxnID=B)
  → Home backing commit
```

REQ 携带 address/size 和属性；payload 与 byte enable 保存在 Requester ledger。Full profile 替换整条
512-bit line；Ptl profile 以 rounded-down `Addr/Size` window 限定 byte enable，并支持 masked merge 和
zero-BE retirement。Full DAT 的 64 个 byte enable 全部有效；Ptl DAT 将窗口外 byte enable 清零，并使
byte-enable=0 的 data byte 保持为零。DAT 保持 `CCID=original Addr[5:4]` 以及 response 交接的 trace identity。
Home 以 backing version、same-line reservation、DBID 和 exact packet evidence 保证一次提交。
当前 resolved session 每次选择 Full 或 Ptl 一种 requester profile；两者与 coherent lifecycle 的混合以共同
Home state owner 为构造前提。

### Returning Atomic

`AtomicSwap` 与 `AtomicLoad ADD` 采用
`REQ(TxnID=A) → DBIDResp(DBID=B) → NonCopyBackWrData(TxnID=B) → CompData_I(TxnID=A)`。
当前 operation profile 使用 Size=0..3、自然对齐、little-endian、`PAS=0`、Normal Non-cacheable 和
`SnpAttr=0/SnoopMe=0`；每次 issue/submit 都携带 requester-line-I 的 admission evidence。
`SnpAttr=0/SnoopMe=0` 只限定这两个 operation profile，其他合法 Atomic form 由各自 profile 建模。

Requester 从 Addr/Size 派生自然 byte lane、动态 byte enable 与 CCID。Home 在 captured backing version 和
same-line reservation 下读取旧值，执行 selected-width Swap 或 fixed-width modular ADD，提交新值并返回旧值。
两项 operation 共享 backing、DBID 和 same-line runtime；feature key 与组件级
`Atomic_Transactions=True` 分别表达 operation slice 和完整组件能力。
与其他 backing-owning lifecycle 的组合以共同 Home state owner 为 resolver 的接纳条件。

### Non-snoop Exclusive Ptl

```text
ReadNoSnp(Excl=1, SrcID, LPID) → CompData(EXOK)
WriteNoSnpPtl(Excl=1, same SrcID+LPID) → CompDBIDResp(EXOK or OK)
  → NonCopyBackWrData
```

Requester 以 `SrcID` 和 5-bit `LPID` 约束跨 Read/Write 的单逻辑线程 outstanding，并核对两次 operation
的 Addr、Size、memory attributes、PAS 与 LPID。Aggregate Home 共同拥有 backing、
64-byte conservative System monitor 与 DBID。CompDBIDResp 冻结 pass/fail outcome；两种结果都消费 DAT，
EXOK 分支提交 masked payload，OK 分支完成 fail-discard。实际 competing nonzero masked commit 命中
monitor granule 时使另一逻辑线程的 reservation 失效。
System authority 覆盖完整 monitor granule。

Ordinary `ReadNoSnp`/`WriteNoSnpPtl` profile 原子拒绝 `Excl=1`，Exclusive feature 负责 LPID、monitor、
EXOK/OK 和五条 flow 的完整合同。

### Coherence 与 clean DCT

Coherence participant 持有 RN cache、Home directory/backing、pending transaction、DBID、同址 reservation
和 CopyBack phase。Feature catalog 把 clean Shared/Unique、dirty responsibility transfer、CleanUnique、
MakeUnique、Evict/Retry、WriteBack、WriteEvict、MESI no-SD 与组合条件投影为明确的 role、capability、
channel flow 和 lifecycle requirement。完整状态方法与原子边界见
[CHI coherence network session](../../../../../docs/architecture/chi-coherence-network-session.md)。

Clean ReadShared DCT 是 base lifecycle 的可选 modifier：

```text
Requester ReadShared(A)
  → Home SnpSharedFwd(B, FwdNID=Requester, FwdTxnID=A) to clean UC peer
  → peer CompData_SC(TxnID=A, DBID=B) to Requester
  → peer SnpResp_SC_Fwded_SC(TxnID=B) to Home
  → Requester CompAck(B) to Home
```

Peer DAT 与 forwarded RSP 使用独立 channel。Home 分别保存 forwarded response 和 CompAck，以任一到达顺序
完成 join，并在 join 后一次提交两名 sharer。`Resp` 与 `FwdState` 保持独立字段；base Home-data path
继续提供无合格 forwarding peer 时的 fallback。当前 profile 选择 clean、单 forwarding peer 和
`RetToSrc=0`；forwarding peer 来自 authority domain，并与 requester 使用不同 NodeID。该 clean UC 路径
与 SD/Owned lifecycle 解耦。扩展维度由实现状态维护。

## System construction 与运行证据

| 文件 | Owner |
|---|---|
| [`identity.py`](system/identity.py) | NodeID ownership、共享身份条件与诊断 |
| [`authority.py`](system/authority.py) | address→Home、coherence domain、Requester/Snoopee role 派生 |
| [`capability.py`](system/capability.py) | feature、dependency、participant capability、flow 与 lifecycle requirement |
| [`capability_projection.py`](system/capability_projection.py) | topology path 到 CHI flow capability 的只读投影 |
| [`resolved.py`](system/resolved.py) | identity、authority、flow 和 capability 的统一 closure |
| [`network.py`](system/network.py) | resolved directed topology 上的逐 hop packet runtime |
| [`progress.py`](system/progress.py) | held line、blocked demand、wakeup 与 unfinished obligation 投影 |

一条 topology edge 表示结构关系。`resolve_chi_system()` 继续检查 NodeID width/ownership、authority、
逐 connection channel 支持、逐 hop route 和 participant capability，最终形成 `ResolvedChiSystem`。
Lifecycle session 只消费这份闭合证据。

`ChiTransportConnectionSession` 为一条 directed connection 保存共享 activation，以及 REQ/RSP/SNP/DAT
各自的 FIFO、receiver reservation、L-Credit 和 backpressure。一个 `AtomicFrame` 可同时提交多个 channel；
任一 channel 的 admission failure 会使整帧保持原状态。Router 按 packet route identity
store-and-forward，并保持 channel-local FIFO lineage。

Coherence network session 以 `pending_egress` batch 保存一次 participant transition 的完整多 packet 输出，
再按路径容量逐 packet 接纳。该边界在背压下保留所有 Snoop fanout 分支。Progress projection 记录
held resource、blocked demand 和 wakeup；deadlock/fairness verdict 由更大 system analysis 负责。

## 查实现、测试与状态

| 要查询的内容 | 源码 | 本地维护回归 |
|---|---|---|
| logical-field schema、opcode 与 round-trip | [`representation/`](representation/) | `test_chi_issue_h_logical_fields`、`test_chi_issue_h_representation_layers` |
| activation、L-Credit、connection 与 network route | [`transport/`](transport/)、[`system/network.py`](system/network.py) | `test_chi_issue_h_transport_connection`、`test_chi_issue_h_transport_network` |
| Request Retry 与 P-Credit | [`interface/request_retry.py`](interface/request_retry.py) | `test_chi_issue_h_retry_system`、`test_chi_issue_h_coherent_retry` |
| Immediate Write | Write lifecycle 三个同名文件 | `test_chi_issue_h_write_no_snp_full`、`test_chi_issue_h_write_no_snp_ptl_system` |
| AtomicSwap / AtomicLoad ADD | Atomic lifecycle 三个同名文件 | `test_chi_issue_h_atomic_swap_resolution`、`test_chi_issue_h_atomic_load_add` |
| non-snoop Exclusive Ptl | Exclusive lifecycle 三个同名文件 | `test_chi_issue_h_non_snoop_exclusive`、`test_chi_issue_h_non_snoop_exclusive_resolution` |
| coherence、CopyBack 与 clean DCT | [`participants/coherence.py`](participants/coherence.py)、[`system/coherence.py`](system/coherence.py) | `test_chi_issue_h_coherence_network`、`test_chi_issue_h_clean_read_shared_dct` |
| identity、authority 与 feature closure | [`system/`](system/) | `test_chi_issue_h_identity`、`test_chi_issue_h_coherence_authority`、`test_chi_issue_h_capability` |
| VirtualDut participant 装配 | [`integrations/recipes/amba/chi`](../../../../integrations/recipes/amba/chi/__init__.py) | `test_chi_issue_h_cache_vdut`、`test_chi_issue_h_home_vdut` |

表中回归名称属于维护工作区的证据索引；精简公开源码不要求运行环境依赖测试目录。Showcase 只投影实际运行
产生的 topology、transaction、causal 与 event evidence，服务演示和审计。

## Canonical 文档

- CHI family 的稳定职责、表示粒度与 credit 分工：
  [`../README.md`](../README.md)
- 通信建模的 interface、representation/transport 与 system 三张视图：
  [`communication-scope-and-transport.md`](../../../../../docs/architecture/communication-scope-and-transport.md)
- coherence participant、session、CopyBack 与原子边界：
  [`chi-coherence-network-session.md`](../../../../../docs/architecture/chi-coherence-network-session.md)
- 已实现 feature、明确边界和证据：
  [`implementation-status.md`](../../../../../docs/architecture/implementation-status.md)
- 当前工作顺序与下一切片：
  [`technical-route/08-roadmap.md`](../../../../../docs/architecture/technical-route/08-roadmap.md)

本页按源码 owner 提供入口。Feature 数量、codec form 数量、完成清单与后续缺口随实现状态更新，统一由
`implementation-status.md` 维护。

## 与一般 NoC 构造的边界

VirtualDut、typed transport port、directed connection、resolved adjacency、有限资源和
blocked/fault effect 提供协议中立底座。Issue H 包继续拥有 `TgtID + channel` route、NodeID、Resource
Plane、L-Credit、CHI participant role 与当前 store-and-forward runtime。

当第二种真实运输体系需要同类 route key、packet lineage、participant identity namespace 或
held-resource/progress 查询时，可把已经对齐的合同提炼到通用 NoC API。在此之前，family-local owner 使
通用内核保持 scope-neutral。
