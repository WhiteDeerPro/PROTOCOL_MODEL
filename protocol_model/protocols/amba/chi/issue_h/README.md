# CHI Issue H executable slice

本包保存当前 CHI Issue H 的可执行最小切片。它不是一个固定 RN→XP→Home 网络，也不是完整 RN-I/HN
builder；调用方先用 SystemProtocol 声明 VirtualDut、TransportPort 和有向 hop，再选择这里的 family
component/session 执行相应 profile。

## 源码切面

```text
issue_h/
├── representation/   REQ/RSP/SNP/DAT message、NetworkPacket 与 ProtocolFlit
├── transport/        单 hop activation、分 channel L-Credit 与有限 TX/RX connection
├── interface/        transaction correlation、outstanding、Retry/P-Credit ledger
├── participants/     transaction/forwarding facet、能力声明与节点局部行为
└── system/           topology-backed network runtime、identity/capability closure
                      完整 read/retry composition 与只读 progress evidence
```

这些目录是彼此组合的视图，不是严格的协议栈继承关系：

- `representation` 说明线上携带什么 typed fact，并提供 named logical-field codec；packed bit layout 仍是后续边界；
- `transport` 只管理相邻 transmitter→receiver hop 的 activation、L-Credit、接纳和背压；
- `interface` 管理完成一笔 transaction 所需的关联和 protocol resource；
- `participants` 表达一个 RN、Home 或 router 怎样持有和改变本地状态；
- `system` 从同一份 resolved topology 闭合 route、跨组件原子提交和端到端 lifecycle。

P-Credit 与 L-Credit 必须保持独立。前者是 completer 对协议事务资源的接纳保证；后者是相邻 receiver 对一笔
flit 的接纳能力。

## Message、packet、flit 与 phit

CHI 的表示对象按用途分开，当前代码以独立对象表达相邻粒度：

```text
transaction
    └─ protocol message
          └─ one or more Network packets
                └─ exactly one protocol flit per packet
                      └─ exactly one phit per flit in CHI Issue H
```

- **Protocol message** 表达参与者之间的一次有类型交换，例如 `ReadNoSnp`、`CompData` 或
  `SnpShared`。TxnID、opcode、address 和操作属性在这一侧判定；message 本身不承担逐 hop 接纳。
- **Network packet** 是可独立路由的一份 message 表示，拥有 source/target route identity 和 packet
  序号。规范允许一个 message 形成一个或多个 packets；当前 executable slice 已显式保存这一边界，
  但尚未提供 multi-packet DAT splitter/reassembler。
- **Protocol flit** 是 packet 在一条相邻 Link 上占用 flow-control 资源的运输 envelope。CHI Issue H
  规定每个 protocol packet 恰好映射为一个 protocol flit；即便当前 cardinality 是一对一，packet route
  ownership 与 flit/L-Credit lifecycle 仍是不同职责。
- **Phit** 是相邻 network device 之间的一次 physical-layer transfer。Issue H 中每个 flit 由一个 phit
  传送；当前模型停在 normalized transport observation，没有实现 packed pin、lane 或 PHY transfer。

Link-maintenance flit 走另一条短路径。以 `LCrdReturn` 为例，它由当前 hop 的 transmitter 产生，并在相邻
receiver 终止，用于 deactivation 时归还未使用的 L-Credit；它不表示端到端 protocol message，也不进入
`ChiNetworkPacket` 或 router queue。

### Logical-field codec

typed message 已经适合 participant 和 system 执行，但外部 trace、字段报告和未来 packed codec 还需要一个
稳定的中间表示。`ChiIssueHLogicalFieldCodec` 为此建立严格的双向投影：

```text
ChiReadUniqueMessage(...)
    ↕
REQ {
  Opcode, TxnID, Addr, Size, QoS, PAS, LikelyShared,
  AllowRetry, Order, PCrdType, MemAttr, SnpAttr,
  Excl, ExpCompAck, TagOp, TraceTag
}
    ↕ future work
packed REQFLIT bits / observed pins
```

logical record 保存当前受限 typed profile 的规范字段名、逻辑类型、宽度和每个已登记 opcode form 的精确
字段集合，但不分配 bit offset，也不声称覆盖完整 Issue H conditional-field catalog。布尔字段保持 `bool`，
integer/enum 字段规范化为非负整数；缺字段、额外字段、错误常量和 profile-invalid 组合都会在 decode
边界得到可解释诊断。相同 opcode 数值必须与 channel 联合判别，例如 REQ、RSP 和 SNP 的 `0x07` 分别选择
不同 message form。

当前 codec 覆盖已实现的 20 个 protocol-message form，包括 read、dataless permission upgrade、snoop、
completion、Retry/P-Credit 与 writeback 使用的 REQ/RSP/SNP/DAT form。因此
`CleanUnique→SnpCleanInvalid→SnpResp/SnpRespData→Comp→CompAck`、clean ReadUnique、dirty unique
responsibility transfer、`WriteBackFull→CompDBIDResp→CopyBackWrData`，以及
`ReadNotSharedDirty→SnpNotSharedDirty→SnpRespData_SC_PD→Home pending 接管→CompData_SC→CompAck`
都可以完整 round-trip。`SrcID/TgtID`、packet index/count 仍归 `ChiNetworkPacket`；四个 channel 的
`LCrdReturn` 属于 hop-local maintenance flit，也不进入 message codec。SNP `Addr` 继续使用 normalized
full byte address，packed SNPFLIT 省略低位的处理留给未来 bit codec。

codec 复用 channel profile 作为合法性权威。本轮同时补齐了 coherent Read 的 Issue H 属性限制：
`Size=6`、`SnpAttr=1`、`MemAttr∈{0101,1101}`、`Order=0` 和 `ExpCompAck=1`；`ReadUnique` 还要求
`Excl=0`、`LikelyShared=0`。当前 `CleanUnique` profile 同样固定 full-line、snoopable、
`ExpCompAck=1`，`SnpCleanInvalid` 固定 `DoNotGoToSD=1/RetToSrc=0`，`Comp` 固定普通
`Comp_UC`。非数据 `SnpResp` 拒绝所有 PassDirty 编码，PassDirty 只能由带数据的
`SnpRespData` 携带。受限 `SD` peer 即使看到 `RetToSrc=0`，仍必须以 `SnpRespData_I_PD` 交回 dirty
data/responsibility；`RetToSrc` 不把 dirty response 降成无数据响应。这些规则留在相应 message/profile，
codec 不维护第二份判定逻辑。

codec registry 只表示“当前能够投影哪些 typed form”。未登记的新 message 仍可由
`ChiIssueHChannelDomain` 和调用方 profile 判为合法，不能反向使用 codec registry 充当全局 opcode
allowlist。

这里需要区分两种“一变多”。`packet_index/packet_count` 描述同一 message 的内容分片，例如较窄 DAT
channel 上的 cache-line 数据分包；Snoop fanout 则把同一选靶决定具体化为若干目标不同的 packet copy。
fanout copy 默认仍各自是 `packet_index=0, packet_count=1`，它们由目标 NodeID 和 Home 私有事务记录关联，
不会借用分片序号冒充 multicast identity。

SNP 的边界尤其需要保留：Snoop request 的协议字段不包含 `TgtID`，由 interconnect 选择 Snoopee。当前构造
接口要求 system/network 为每个选中的 Snoopee 生成一份带显式 `target_id` 的 packet copy，再由各 hop 包装成
protocol flit。这样一份 `SnpShared` message 可以对应多个路由目的地，而无需修改 message。当前已经实现
`SnpShared`、`SnpUnique` 与 `SnpNotSharedDirty` typed message/profile，以及 SNP `TransportLink`
channel 的共享 activation、独立 L-Credit、FIFO/reservation、背压与 capture/drain。clean
`ReadShared` profile 可从 Home directory 生成显式 per-target copies 并聚合 `SnpResp_I/SC`；受限
dirty-unique profile 可把 `SnpRespData_I_PD` 作为 DAT packet 返回 Home；no-SD MESI profile 则以
`SnpRespData_SC_PD` 把 dirty 数据交回 Home，同时把原 owner 降为 `SC`。通用 multicast switch、真实
snoop filter、完整 MOESI shared-dirty lifecycle 和 forwarding response 仍未实现；当前只为
dirty-peer CleanUnique 保存一个受限、可预置的 `SD→I` 出口。

## 检验职责怎样组合

当前判定链按所需观察范围逐级委托，同一条规则不在 system 层重新实现一遍：

| 输入/事实 | 主要判定者 | 当前检查 |
|---|---|---|
| typed REQ/RSP/SNP/DAT message | `representation` value 与 profile | 固定字段类型/宽度、address/data 范围、保留编码和本 opcode 的局部条件 |
| named logical-field record | `ChiIssueHLogicalFieldCodec` | channel+opcode form、当前 typed profile 的精确字段集合、常量、逻辑类型、profile width 与 typed message round-trip |
| `ChiNetworkPacket` | network envelope | channel 与 message 种类、可路由 source/target identity、packet index/count |
| `ChiProtocolFlit` 或 channel-local `LCrdReturn` | transport envelope | protocol flit 必须携带 packet；link-maintenance flit 必须留在当前 hop |
| 一帧 normalized channel observation | `ChiTransportLinkSession` | clock/tick、activation 顺序、FLITV/typed flit、frame-start L-Credit、Resource Plane、credit capacity 与 deactivation return |
| 一条有限 TX→RX connection | `ChiTransportConnectionSession` | 共享 activation，REQ/RSP/SNP/DAT 独立 FIFO、receiver reservation、L-Credit、backpressure、capture/drain 与同帧原子提交 |
| resolved directed topology | `ChiTransportNetworkSession` 与 router participant | connection/channel 匹配、逐 hop 运输、TgtID route、store-forward queue 和 lineage |
| CHI 构造闭合 | NodeID identity plan、flow projector 与 feature capability resolver | facet 的 NodeID ownership、端到端可运行 channel path、participant behavior offer 与 feature dependency |
| 一笔协议 operation | interface ledger、Requester/Home participant 与 read/retry system session | TxnID correlation、outstanding、RetryAck/P-Credit、credited reissue、CompData completion 和跨组件提交 |

因此可以概括为“现有局部检验设施完成单值、单 frame 和单 hop，system composition 再检查必须跨 participant 或
跨 hop 才能决定的关系”。system 不替代 transport 检查；它调用已经判定过局部合法性的 transport path，并增加
更大作用域的事实。

WaveDrom、DOT 和后续 MSC 只投影 observation/evidence，不产生协议 verdict。当前也没有完整 raw RTL CHI pin
adapter：`FLITPEND`、packed flit codec、lane/parity 和完整 Port bundle 尚未覆盖。因此现有“波形检查”的准确
输入是 `AtomicFrame` 中的 normalized activation/channel sample，而不是任意 VCD 引脚转储。

## 当前可组合路径

### Channel transport

REQ、RSP、SNP 和 DAT 保留独立的 channel-only point-to-point fixture，用于局部检验。网络执行使用
`ChiTransportConnectionSession`：一条 directed connection 只拥有一个 activation state，各启用 channel
分别持有 transmitter FIFO、receiver reservation 和 L-Credit。一个 `AtomicFrame` 可以同时接受多个
channel 的 flit；任一 channel 失败时整帧不提交。

`ChiTransportNetworkSession` 把这个 connection runtime 放进调用方声明的 topology，并可经过有限
store-and-forward router。lineage 按 `connection + channel` 与有序 FIFO 对齐，因此 mixed-channel Link
不会被误写成一条虚构的跨 channel 总顺序。protocol flit 在 connection 边界解包回同一个 network packet；
router 只依据 packet 的 route identity 转发，不读取 Link credit 状态。将来若加入自动 replicated channel、
lane 或 channel 内重排，lineage 仍需进一步绑定 packet-copy identity。

### 构造期系统证据

`ChiBehaviorFacet` 将同一个 VirtualDut 上的 transaction participant 与 forwarding behavior 分开组合；
它没有建立 RN/HN/SN/router 继承树。`ChiResolvedIdentityPlan` 检查 NodeID ownership。重复 NodeID
默认视为歧义，只有同一 VirtualDut、相同逻辑 port boundary 和显式 share group 才可共享。

feature catalog 把 direct `ReadNoSnp`、direct NDERR/Request Retry modifier、clean `ReadShared`、clean
`ReadUnique`、clean `ReadUnique` NDERR/Request Retry modifier、clean/shared-dirty peer `CleanUnique`、
dirty unique transfer、dirty writeback 和 MESI `ReadNotSharedDirty` profile 展开为 participant
capability、channel flow 与 system lifecycle requirement。flow projector 只处理合同所需 feature 及其依赖，
并只从已成功构造的 `ChiTransportNetworkSession` 产生证据：一条 topology edge 的存在本身不足以证明
channel、NodeID width 和逐 XP route 可运行。`resolve_chi_system()` 汇总 facet、identity、flow 与
capability，形成 `ResolvedChiSystem`；read、retry 与 coherence session 可以通过 `from_resolved()` 消费
同一份证据和同一个 network runtime。

### Direct read

`ChiReadNoSnpSystemSession` 组合 Requester ledger、Home participant、REQ route 和 DAT return route，执行受限
`ReadNoSnp → CompData`。同一个 session 类型可以运行 direct 或 caller-built router topology；拓扑不是类定义的
一部分。

`ChiAddressHomeNode` 是这一 profile 的 stateful Home 变体：它把 aligned full-DAT-width 请求转换为
`AddressRead`，再委派给协议无关 `AddressTarget`。`DECODE_ERROR/ACCESS_ERROR` 映射为
`CompData_I(NDERR)`，保留 TxnID/HomeNID/DataID、以零作为线上无效数据占位，并在 Requester 端得到
`succeeded=False/data=None`；resolved XP witness 证明它复用原 REQ/DAT route 并最终 quiescent。
`from_resolved()` 只在 feature closure 选中 NDERR modifier 时开放该响应，base-only construction 会在
Home state commit 前拒绝它；authority 外请求仍是 system fault。当前公开场景使用
`AddressSpace/MemoryRegion/RegisterRegion`；narrow DAT
placement、DERR 数据损坏来源、sideband lowering 和带 blocked/effect 的 target transition 仍是明确扩展点。

这条 direct-read adapter 不代表 coherent `ChiCoherentHomeNode` 绑定同一个 `AddressTarget`。
coherent Home 需要在 `Comp` 与 `CompAck` 之间保存可丢弃、可检测 stale 的 full-line write intent，
因此改为注入协议中立 `FullLineBackingCore`：payload/version 位于 `LineBackingState`，directory entry
只保存 holder authority。公开 Home attach/binder 已可从 core 创建新 VirtualDut，或绑定调用方已有的
canonical declaration；它们没有建立 topology-visible Memory/SN 或 HN→SN physical commit。

### Request Retry

`interface/request_retry.py` 保存 family-local 的共同合同：Requester retained phase、按
`(Home NodeID, PCrdType)` 池化的 transaction-independent P-Credit，以及 Home retry debt、真实容量
reservation 与 credit conservation。direct-read facade 和 coherent participant 都委派这份合同，再把
状态投影回各自的公开 participant state。

`ChiReadNoSnpRetrySystemSession` 在 direct-read profile 上增加：

```text
initial REQ
  → RetryAck
  → matching PCrdGrant
  → AllowRetry=0 credited REQ
  → CompData
```

Requester 按 `(Home NodeID, PCrdType)` 保存 transaction-independent P-Credit，并允许 Grant 先于 Ack 到达。
Home 发 Grant 时预留真实请求容量；重发入网和 credit 消耗采用同一个原子候选提交。

Requester 也可在 Ack 与匹配 Grant 均到达后取消该请求。此时 ledger 生成 `PCrdReturn`，它作为
Requester→Home 的 REQ packet 经过同一正向 route；只有入网成功才同时移除 retained request 和本地
P-Credit。Home 接收后释放 Grant 对应的真实预留槽，不产生 response。

`CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY` 则把同一合同作为 clean `ReadUnique` 的 modifier：

```text
initial ReadUnique
  → RetryAck
  → matching PCrdGrant
  → AllowRetry=0 credited ReadUnique
  → SnpUnique / SnpResp
  → CompData
  → CompAck
```

被拒绝的初始请求不会分配 coherence pending、DBID 或 snoop，也不会修改 directory/backing。正确重发原子
消耗 Home reservation 后才进入原有 clean `ReadUnique` lifecycle；Grant 可以先于 Ack 到达。当前 coherent
slice 只闭合一次 Retry 后成功，不包含取消、同 Home/type 多 waiter 公平性，或 Retry 与
error/Snoop/writeback 的组合。

### Coherent reads 与受限 dirty ownership transfer

`ChiCoherenceSession` 在 packet-delivery 边界组合一个 Home 与若干 RN。基线一致性 profile 使用
协议中立 Home backing state 和 `I/UC/SC/UD` 四种 RN 稳态；`CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER`
额外接受一个只供本 lifecycle 消费的预置 `SD` holder。当前没有 operation 生成或维持一般 `SD`。
clean `ReadShared` 闭合：

```text
RN0 ReadShared(A)
  → Home SnpShared(B) to clean UC owner RN1
  → RN1 UC→SC and SnpResp_SC(B)
  → Home CompData_SC(TxnID=A, DBID=C)
  → RN0 installs SC and CompAck(C)
  → Home commits sharers={RN0,RN1}
```

同一组 participant 也闭合一个从 `I` 发起的 clean `ReadUnique`：

```text
RN0 ReadUnique(A)
  → Home SnpUnique(B) to every other clean holder
  → each holder SC/UC→I and SnpResp_I(B)
  → Home CompData_UC(TxnID=A, DBID=C)
  → RN0 installs UC and CompAck(C)
  → Home commits unique_owner=RN0, sharers={}
```

`CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR` 是这条 lifecycle 的无新 flow modifier。Home 的显式预侦听
policy 可以在完成 admission、地址 authority 和 profile 检查后直接选择：

```text
RN0 ReadUnique(A)
  → Home reserves DBID=C, emits no SnpUnique
  → Home CompData_I(NDERR, TxnID=A, DBID=C)
  → RN0 keeps its original I or SC state and returns CompAck(C)
  → Home releases DBID and same-line reservation
```

错误数据位只作为无效线上占位，RN 不安装它；从 `I` 发起时不分配 cache line，从 `SC` upgrade 发起时保留
原 payload 和权限。Home 在 `CompAck` 前仍持有 pending/DBID 和同址 reservation，但 directory、backing
及 Snoop TxnID 均不变化。modifier 复用 base 的 REQ/DAT/CompAck 以及构造期 SNP/RSP flow，不声称错误专用
channel；policy 与 feature 必须同时启用。当前明确不组合 Retry→NDERR，post-snoop failure 与 DERR 也仍是
独立后续切片。

`SnpUnique` 设置 `DoNotGoToSD=1`。只启用 clean profile 时固定 `RetToSrc=0`。启用
`CHI_FEATURE_DIRTY_UNIQUE_TRANSFER` 后，持有 `UC` 的 RN 可执行本地 full-line write，使缓存行进入
`UD`；后续另一个 RN 的 `ReadUnique` 可完成：

```text
RN1 UC --local write--> UD(new data)
RN0 ReadUnique
  → Home SnpUnique(RetToSrc=1) to RN1
  → RN1 UD→I and SnpRespData_I_PD(new data)
  → Home CompData_UD_PD(new data)
  → RN0 installs UD and CompAck
  → Home commits unique_owner=RN0
```

`PassDirty` 在这条路径中表示最新数据的写回责任随数据转移；Home backing data 因而可以保持旧值。
monitor 要求 `UD` 仍是唯一 holder，但不把它与旧 backing data 比较。`I/SC/UC/UD` 可分别与经典
I/S/E/M 的权限直觉对照；`UCE` 另表示不含有效 payload 的 unique authority，没有借用一个 MESI 数据态
冒充。这是当前 profile 的解释映射，并不把 MESI 另设为一条线路协议。

在此基础上，`CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY` 增加一条不引入 `SD` 的
dirty-to-clean-shared 路径：

```text
RN1 UC --local write--> UD(new data)
RN0 ReadNotSharedDirty
  → Home SnpNotSharedDirty(DoNotGoToSD=1, RetToSrc=1) to RN1
  → RN1 UD→SC and SnpRespData_SC_PD(new data)
  → Home pending accepts dirty data and responsibility
  → Home CompData_SC(new data) to RN0
  → RN0 installs SC and returns CompAck
  → Home commits backing data, unique_owner=None, sharers={RN0,RN1}
```

这条路径结束时没有节点继续承担 dirty responsibility：最新数据已经回到 Home backing，两个 RN 都是
clean shared holder。它属于当前 `I/SC/UC/UCE/UD` permission 切片，不声称已经实现完整 MESI，也不以 `SD` 模拟
MOESI Owned。当前 Home policy 固定吸收 PassDirty、返回 `CompData_SC`，并在 `CompAck` 后一次提交
backing/directory；这是规范允许结果的一个受限子集，不代表所有 Home 都必须采用同一结果。

显式 dirty writeback 使用独立 feature，闭合：

```text
RN holds UD
  → WriteBackFull(TxnID=A)
  → Home CompDBIDResp(TxnID=A, DBID=B)
  → RN reads the latest CacheLineStore payload, becomes I
  → RN CopyBackWrData_UD_PD(TxnID=B)
  → Home commits backing, clears unique_owner, releases DBID=B
```

RN 在收到 `CompDBIDResp` 前保留 resident `UD` line；Home 在收到 `CopyBackWrData` 前保留旧 backing 和
directory owner。read 与 writeback 在 RN 共享 TxnID/capacity，在 Home 共享 DBID/capacity，但各自使用
具名 pending record。当前 API 提交一条已经选中的 dirty line；LRU、victim selection、自动 eviction trigger
和 writeback queue scheduling 尚未包含在该 feature 中。

`SC` 仍不能直接执行本地写；启用 `CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS` 后，`I` 或 `SC` requester
可以发出 `CleanUnique`。若本地 full-line 数据一直保留，Home 以 `SnpCleanInvalid` 失效其他 clean holder，
无数据 `Comp_UC` 使 requester 进入 `UC`；若从 `I` 发起，或 pending CleanUnique 收到同址
`SnpUnique`/`SnpCleanInvalid` 而先失效，则 `Comp_UC` 形成不持有 payload 的 `UCE`。`UCE` 的第一次
full-line local write 原子安装 payload 并进入 `UD`。这避免了旧路径用 `ReadUnique` 重取整行；旧路径仍
保留给真正需要数据的 read lifecycle。clean-only feature 继续拒绝 dirty peer 的 DAT 路径。

`CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER` 依赖上述 clean feature，并增加一个受限分支：

```text
RN0 SC; RN1 SD(new data)
Home sharers={RN0,RN1}, shared_dirty_owner=RN1
RN0 CleanUnique
  → Home SnpCleanInvalid(DoNotGoToSD=1, RetToSrc=0) to RN1
  → RN1 SD→I and SnpRespData_I_PD(new data)
  → Home pending.dirty_result accepts data and reference update responsibility
  → Home Comp_UC to RN0
  → RN0 SC→UC and CompAck
  → Home commits reference backing=new data, unique_owner=RN0,
    sharers={}, shared_dirty_owner=None
```

Home 复用 `allow_dirty_data_transfer=True` 接纳 DAT，不增加第二个 transaction 事实；`dirty_result` 持有
最新数据，`prepared_backing_write` 在所有 Snoop 到齐、发送 `Comp_UC` 前捕获该行的 backing version。
同址 Home reservation 持续到 `CompAck`；届时 line-local CAS 与 directory candidate 在同一个不可变
Home-state transition 中提交。clean-only `CleanUnique` 不 prepare、不递增 backing version；
stale/double intent 会保留原 state 并产生可解释 fault。这里的 “memory update” 不是
独立 Memory VirtualDut 的 physical write，也没有发出 HN→SN-F 的 `WriteNoSnp/NCBWrData`。因此本切片不
声称具备完整 MOESI/Owned 或主存提交路径；`MakeUnique` 也尚未实现。普通
`ReadShared` 命中 `UD` 的 policy 仍在本切片之外；调用方若需要 no-SD MESI 行为，应显式使用
`ReadNotSharedDirty`。resolver/session 继续拒绝 clean `ReadShared` 与任一允许 `UD` 的 feature
组合，避免把尚未定义的 shared-dirty policy 延迟成运行时 fault；这项阶段边界不表示 CHI 协议禁止这些
transaction 共存。

`A`、`B` 和 `C` 分别处于 requester transaction、Home snoop transaction 和 completion-buffer
correlation domain；参考实现不要求它们取相同数值。Home 在 CompAck 前保留 pending record，稳定 directory
在闭环末端一次提交。`ChiCoherenceInvariantMonitor` 只在静止点比较 directory、RN permission 与相应
数据权威：clean holder 必须匹配 Home backing，`UD` 的最新值由唯一 owner 持有；受限 `SD` 必须与
directory 的唯一 `shared_dirty_owner` 对应。
它不产生 Home/RN 输出，也不参与 transport 调度。

这里的 RN/Home class 是可绑定到具体 VirtualDut 的 participant behavior，并未建立一棵 CHI 专属设备继承树。
cache 的 `attach_chi_issue_h_coherence(core, ...)` 与 Home 的 `attach_chi_issue_h_home(core, ...)` 都从
协议中立 core 创建第一个 VirtualDut；`bind_chi_issue_h_{cache,home}_vdut(existing_vdut, ...)` 则引用
同一个已有 canonical 对象，不复制成另一个 attached VirtualDut，也不创建 connection。Home binder 当前
只接受没有独立 executable backend 的 boundary，避免 address-memory runtime 与 CHI participant 各持一份
payload state；topology-visible SN physical commit 仍未实现。

`ChiCoherenceSession` 的输入仍是“已经送达目标的 packet”，可用于 participant 级单元检查。
`ChiCoherenceNetworkSession.from_resolved()` 则把它与同一份
`ChiTransportNetworkSession` 组合起来：构造期从 closed feature-flow evidence 建立
`(source NodeID, target NodeID, channel) → connection path` 索引；运行时以轮转 microstep 推进
participant emission、首 hop enqueue、Link、router 和 endpoint delivery。因此一致性状态机不固化
direct、ring 或 mesh 拓扑，具体形状仍由调用方构造并由 resolver 闭合。

Home 因同址 reservation 暂不接纳 endpoint packet 时，组合 transition 不 drain transport capture；
packet 留在 endpoint head，首笔事务的 `CompAck` 释放 reservation 后由 scheduler 自动 replay。只读
`project_progress()` 从 Home/RN pending 与 endpoint head 派生 `ChiHeldLine`/`ChiLineWait`，
`project_wakeups()` 只报告 exact holder 的释放证据；它们不反向驱动 scheduler，也不形成一般 wait-for
graph、fairness 或 deadlock verdict。

一次 Home transition 可能同时产生多份 SNP。组合 session 先把完整 emission 原子保存为显式
`pending_egress` batch，再按网络容量逐 packet 接纳；这样不要求所有 Snoopee 路径同一时刻有空位，也不会
在背压时遗失尚未入网的分支。当前只有一个 batch 槽，会串行化产生新输出的 participant transition。
在 DAT splitter 落地前，这个 full-line profile 要求沿途每条 DAT connection 都是 512-bit；network
session 会在打开 resolved plan 时拒绝 128/256-bit DAT 路径。

`CHI_FEATURE_CLEAN_READ_SHARED` 与 `CHI_FEATURE_CLEAN_READ_UNIQUE` 是两个独立构造合同。
`CHI_FEATURE_CLEAN_READ_UNIQUE_NDERR` 依赖 clean ReadUnique，只增加 Requester/Home 的 NDERR
accept/produce capability 和 `CHI_SYSTEM_CLEAN_READ_UNIQUE_NDERR_LIFECYCLE`；不增加 flow。
`CHI_FEATURE_CLEAN_READ_UNIQUE_RETRY` 依赖 clean ReadUnique，只增加 Requester/Home retry capability、
Home→Requester `retry_response` RSP flow 和
`CHI_SYSTEM_CLEAN_READ_UNIQUE_RETRY_LIFECYCLE`；原有 snoop、completion 与 CompAck flow 由依赖闭合保留。
dirty unique transfer 也依赖 clean ReadUnique，因为它直接扩展该 read lifecycle。dirty writeback
把“当前 line 为 `UD`”作为 participant-state 前置条件，不强制同一 construction 证明该权限由哪条获取路径产生；它声明
Requester→Home REQ、Home→Requester RSP 和 Requester→Home DAT 三条 flow，但不引入 Snoopee role。
`CHI_FEATURE_MESI_READ_NOT_SHARED_DIRTY` 本身没有 feature
dependency，也不要求 local-write capability，只声明这笔 read/snoop/completion 所需的角色和 flow。
`CHI_MESI_NO_SD_REQUIRED_FEATURES` 是 system 侧 policy preset：它同时选择 dirty unique transfer 与
ReadNotSharedDirty，dependency closure 再由前者带入 clean ReadUnique。它们共享实现原件，
但一个 feature 的可用性不推导另一个 opcode 的行为。独立
`CHI_FEATURE_CLEAN_UNIQUE_CLEAN_PEERS` 合同闭合 Requester→Home `REQ`、Home→Snoopee `SNP`、
Snoopee→Home `RSP`、Home→Requester `RSP` 和 Requester→Home CompAck `RSP`，不声明 DAT flow。
`CHI_FEATURE_CLEAN_UNIQUE_SHARED_DIRTY_PEER` 依赖该 clean-only feature，仅增加
`clean_unique_snoop_data` Snoopee→Home `DAT` flow、Home 的 dirty-data accept/reference
memory-update capability `CHI_HOME_PASS_DIRTY_MEMORY_UPDATE` 和 Snoopee dirty-data produce capability，
并形成 `CHI_SYSTEM_CLEAN_UNIQUE_SHARED_DIRTY_PEER_LIFECYCLE`。依赖闭合保留 requester、REQ/SNP/RSP 与
CompAck 合同，不把 DAT 反向要求到 clean-only feature。它的现名来自首个 `shared_dirty_owner`
witness；runtime 以它统一许可 CleanUnique 的 PassDirty DAT，所以当前 `UD unique_owner` 被失效时也受
该 modifier 约束。后续稳定公开 feature API 前应泛化名称或拆分 profile，而不是把 `UD` 与 `SD` 合并成
一个状态。

clean coherent read 合同则检查三种参与角色和五种有向 flow schema：
Requester→Home REQ、Home→Snoopee SNP、Snoopee→Home RSP、Home→Requester DAT，以及
Requester→Home CompAck RSP。dirty-data 路径再增加 Snoopee→Home DAT；RSP 与 DAT 回程不会因目标相同
而合并成一条虚构 channel。两个 RSP 方向分别闭合。独立 capability API 仍允许用 `role_sets` 检查任意
有限集合；进入 `resolve_chi_system()` 后，feature intent 只手工选择 Requester。CHI authority contract
引用通用 `AddressClaim`，为本次 feature scope 派生 scalar Home，并从 coherence domain 派生
`Snoopee = members - requester`。resolver 拒绝另一份手填 Home/Snoopee role，随后 topology flow projector
对每个派生成员分别检查 participant capability、Home→peer SNP 和 peer→Home RSP；shared-dirty extension
还逐成员检查 peer→Home DAT，诊断保留具体端点。
只含 Requester 的 domain 会派生显式空 peer set；这与 authority 未绑定 domain 不同。

domain 是构造期声明的 eligible peer 集合，并非一笔事务已经选出的目标列表。运行时 Home 仍根据
directory 从中选择实际 holder 并生成 per-target packet copy；session opening 会拒绝 directory holder
越出 domain。`ChiCoherenceSession.from_resolved()` 从同一份 closed authority/feature construction 建立
恰好由 `requester ∪ snoopees` 构成的 RN registry；它同时保留 requester-only issue、Snoopee-only SNP/RSP 和
Shared/Unique/clean-ReadUnique-NDERR/Retry/clean/shared-dirty CleanUnique、dirty-unique/dirty-writeback/
MESI no-SD feature enablement。直接调用 packet-delivery API 也会重复检查这些 role authority，不能绕过
构造期边界。当前窄
profile 要求每个绑定只提供其 component 的单一 NodeID；
等 flow evidence 保存所选 identity 后才适合放宽 compound binding。

packet-delivery session 继续作为较小的 participant runtime；topology-driven 组合 session 已闭合
clean-peer `CleanUnique` 经 direct 与单 XP topology 的五 packet witness，并为 restricted `SD` peer
增加 `SnpRespData_I_PD` 的五 packet witness；后者检查 `dirty_result`、prepared backing intent、
`CompAck` 后 backing/directory commit 和 `SD→I`，但不声称独立 Memory/SN physical commit。clean `ReadUnique`
经 XP 的七 packet witness；其一次 Retry 后成功的 modifier 另有十 packet witness，覆盖两个
`ReadUnique`、`RetryAck`、`PCrdGrant`、两个 `SnpUnique`、两个 `SnpResp`、`CompData` 与 `CompAck`，
并检查最终 authority、backing version、retry ledger 和 transport quiescence。预侦听 NDERR modifier
另有三 packet witness：REQ、`CompData_I(NDERR)` 与 `CompAck` 都经过同一 XP，SNP/SnpResp 数量为零，
最终 cache、peer、directory 与 backing 保持原值。它也已闭合 dirty owner 经 XP 返回
`SnpRespData_I_PD`、再以 `CompData_UD_PD` 转移责任的五 packet witness。第三条五 packet witness
执行 `ReadNotSharedDirty→SnpNotSharedDirty→SnpRespData_SC_PD→Home pending 接管→CompData_SC→CompAck`，
并检查 Home
在 CompAck 后提交 backing/directory、两个 `SC` holder 与清空后的 `unique_owner`。显式 dirty
writeback 也已有经 XP 的三 packet witness，闭合 REQ、反向 RSP、CopyBack DAT 的 route lineage，并检查
Home backing/DBID 与 RN `UD→I` 的提交结果。详细原子边界与阶段限制见
[CHI coherence network session](../../../../../docs/architecture/chi-coherence-network-session.md)。

participant runtime 另有 direct 双 Requester witness：两个 RN 都先提交 `CleanUnique`，Home 以 line
reservation 串行处理；第一笔的 invalidating Snoop 可以命中第二个 RN 的 pending CleanUnique，第二个 RN
先返回 `SnpResp_I` 且保留 transaction，随后自己的 `Comp_UC` 形成 `UCE`，full-line write 再完成
`UCE→UD`。该见证不经过 resolved construction，不把 fixture 中的两个 requester 冒充一般多 Requester
system authority。

## 场景与功能边界

direct topology、调用方组装的一个或多个 router topology 和具体 FIFO 深度属于测试/showcase 的参考装配，
不属于 CHI 核心 API。coherent `ReadUnique` Retry 已保存单 XP router witness；direct `ReadNoSnp`
Retry/Cancel 仍保留为独立、较窄的 profile。

pending `ReadUnique` 已可处理同址 `SnpUnique`：RN 的 `I` 保持 absent，或把 `SC` copy 失效为 `I`，
`RetToSrc=0` 或原状态为 `I` 时返回 `SnpResp_I`，原状态为 `SC` 且 `RetToSrc=1` 时返回
`SnpRespData_I`；两者都保留 pending/Retry correlation，随后由自己的 `CompData_UC` 重新安装 line。
pending `CleanUnique` 也可处理同址 `SnpUnique` 或 `SnpCleanInvalid`：前者采用上述区分，后者返回
`SnpResp_I`；失效为 `I` 后仍保留 pending，
再由自己的 `Comp_UC` 形成无 payload 的 `UCE`；`UCE` 遇到 invalidating
Snoop 只返回无数据 `SnpResp_I` 并进入 `I`。Home 仍只允许一个同址 lifecycle；direct packet-delivery
fixture 已表达两个 requester 的 CleanUnique 串行化，但 resolved system 仍只有一个构造期 Requester
authority，不能据此声称一般多 Requester topology 已闭合。

仍属功能缺口的是同 Home/type 多 waiter 的具名选择/公平性合同、`MakeUnique`、clean `Evict`、自动
victim/writeback scheduling、coherent DERR 与 post-snoop/组合错误路径、Retry 与
error/Snoop/writeback 的并发组合、WriteBack 同址 Snoop/cancel、显式 transient phase/等待者合并、
完整 `SD`/Owned lifecycle、forwarding snoop、真实 snoop filter、可共同执行的 Home→Memory/SN
participant 与 topology-visible `WriteNoSnp` physical commit、multi-packet DAT、同一 runtime 的
一般多 Requester、multi-Home/SAM 选择、跨 domain 执行，以及跨 hop wait-for/deadlock
分析。准确状态只在
[实现状态](../../../../../docs/architecture/implementation-status.md)维护，协议/网络/链路的分工见
[通信建模的三张视图](../../../../../docs/architecture/communication-scope-and-transport.md)。

测试可以保存私有 topology builder 和负例 fixture；可复用状态机、ledger、router 或 session 必须位于本包，
不能把 tests 当作生产实现目录。

## 与一般 NoC 构造的边界

这一轮证明了几项协议中性的底座已经足够：VirtualDut、typed transport port、directed connection、
resolved adjacency、有限资源与 blocked/fault 语义不依赖 CHI。当前 store-forward router、channel runtime、
participant facet、identity namespace 和 capability closure 仍留在 CHI family，因为它们携带
`TgtID + channel` route、Resource Plane、L-Credit、NodeID 与 CHI role 等具体假设。

后续只有出现第二种真实运输体系并提出相同查询时，才适合提炼公共 NoC API。例如：

- CHI C2C 或另一 transport family 也需要相同的 family-runtime validation hook；
- TileLink/PCIe 也需要“一个 module 上多个逻辑 participant 与 identity namespace”；
- 第二种 route key 或 switching mode 复用同一 store/forward/service 生命周期；
- 两种 packetization 都需要稳定的 message→packet→flit lineage；
- CHI router 与 AXI fabric 都能投影 held resource、blocked demand 和 unfinished obligation。

在这些证据出现前，保留 family-specific 实现能避免把“所有 NoC 都按 NodeID、L-Credit、单 flit packet
和 store-forward 工作”等 CHI 当前形状写进通用内核。
