# 实施路线与阶段边界

[返回架构地图](README.md) · [查看总览图](overview.svg) · [项目 Roadmap](../../../ROADMAP.md)

本页维护近期工作的顺序、依赖和验收门槛。路线按真实场景暴露的缺口推进，每次选择一个可以形成完整
证据链的小型切片。

相邻文档各自维护一种事实：

| 事实 | 权威入口 |
|---|---|
| 当前实现、明确缺口与 profile 边界 | [实现状态](../implementation-status.md) |
| 长期能力方向与依赖 | [项目 Roadmap](../../../ROADMAP.md) |
| CHI family 的稳定对象边界与源码入口 | [CHI family 源码导航](../../../protocol_model/protocols/amba/chi/README.md) |
| CHI Issue H 的可执行对象与场景说明 | [CHI Issue H executable slice](../../../protocol_model/protocols/amba/chi/issue_h/README.md) |
| CHI participant、authority 与 network session 的组合方法 | [CHI coherence network session](../chi-coherence-network-session.md) |
| Bridge 的稳定方法与 V1 状态 | [Bridge 与类型化事务转译](../typed-transaction-translation.md) · [V1 实施状态](../translation-implementation.md) |

## 工作包怎样进入主线

每个候选在施工前记录四类依据：

| 依据 | 记录内容 |
|---|---|
| 协议要求 | 官方 document issue、章节、适用条件，以及 issue/errata 的裁决 |
| 实现基础 | 可复用对象、现有 profile、定向回归和 canonical implementation status |
| 阶段选择 | 本次合法子集、依赖、验收条件和重新评估条件 |
| 待验证线索 | review、教材、实现手册或网络资料提出的假设，以及后续官方核对入口 |

一个工作包还要写明目标、边界、验收条件和非目标。合法 witness 证明选定输入与边界可以执行；单点负例
证明目标规则参与判定；state/resource/causal projection 解释运行结果。协议一致性结论以已记录的
profile 和证据范围为界。

仓库同一时刻保留一条主要 WIP。候选若暴露 system construction、状态 owner 或 runtime 依赖，先把该依赖
作为当前切片的阻塞项闭合，再返回 lifecycle。

## 当前起点

基础语义、通用 pattern、AMBA InterfaceProtocol、attachment/binding、AddressSpace/AddressFabric
VirtualDut，以及 point-to-point、bridge chain、single-ingress fabric、scheduled N×M crossbar 的
SystemProtocol 路径已经形成可执行基线。同步执行、trace、causality 与 artifact 可以为这些路径提供证据。

Bridge 主线已经具备 typed stage、`AddressBurst`、fanout ledger、capacity lease、attachment-aware backend
和 operation-level serial executor。CHI 主线已经具备 REQ/RSP/SNP/DAT transport、participant、单
Home authority、direct/XP witness，以及若干受限 coherence、Immediate Write、Exclusive 和 Atomic
lifecycle。完整覆盖矩阵由[实现状态](../implementation-status.md)维护。

### 最近 CHI 切片的状态交接

下表保留切片 14–19 的直接顺序和验收重点，便于确定下一项依赖；实现细节与后续状态更新继续归入
[实现状态](../implementation-status.md)和
[CHI Issue H executable slice](../../../protocol_model/protocols/amba/chi/issue_h/README.md)。

| 顺序 | 已闭合切片 | 验收重点 | 后续边界 |
|---|---|---|---|
| 14 | full-line `WriteNoSnpFull` Immediate Write | original TxnID/Home DBID 分域、full-line backing version guard、Home DBID/same-line reservation，以及 direct/XP 三包 commit witness | 与其他 backing-owning lifecycle 的共同 runtime owner |
| 15 | Normal-memory `WriteNoSnpPtl` | Size=0..6、rounded-down Addr/Size window、合法 BE、masked commit、zero-BE retirement，以及 direct/XP 三包 witness | Full/Ptl 同 session、Retry、DWT、Device-memory 与 error profile |
| 16 | non-snoop Exclusive Ptl | `SrcID+LPID` gate、aggregate Home backing/System monitor/DBID owner、competing commit invalidation、EXOK/OK 分支与 fail DAT discard | monitor overflow、multi-LP、Full/coherent Exclusive 与 Retry/error |
| 17 | 参数化 non-snoop `AtomicSwap` | Size=0..3、自然对齐、LE、`PAS=0`、Normal-NC、动态 BE/CCID/natural lane、一次 pre-value read→masked replacement→old-value completion，以及 direct/XP 四包 witness | big-endian、SnoopMe、Retry/error、early completion 与其他 Atomic operation |
| 18 | clean `ReadShared` DCT | authority-domain forwarding role、peer→requester DAT、`SnpRespFwded`/`CompAck` 乱序双输入 join，以及 peer `UC→SC`、requester `I→SC` 的一次提交 | dirty/RetToSrc、动态多 peer 与一般 forwarding catalog |
| 19 | non-snoop `AtomicLoad ADD` | 复用切片 17 的 operation/geometry 与 runtime，执行 selected-width `(old + operand) & mask` 固定宽度截断，同址 Swap/Load ADD 由共同 reservation 串行 | 其他 Atomic operation/profile 与共同 backing-owning aggregate |

切片 17 和 19 当前采用 `SnpAttr=0/SnoopMe=0` 的窄 profile；Home snoop 能力由后续 profile 独立闭合。
clean DCT 以 clean ReadShared base/fallback 为依赖，可以独立于 Owned lifecycle 使用；dirty DCT 随 Owned
状态与 dirty responsibility transfer 一起进入后续切片。

2026-07-29 的质量复核修正了 ordinary Ptl/Exclusive DAT 的
`CCID=original Addr[5:4]`、response→DAT `TraceTag` 传播，以及 Exclusive Home pass/fail 与 system
期望 `EXOK/OK` response 的 checkpoint invariant。正向与伪造/恢复状态负例已经锁定这些合同；该工作按
基线缺陷归档，opcode 范围保持原状。

## Now · C1/S3：选择下一条 CHI lifecycle，并闭合构造依赖

当前工作从下面的候选队列选择一项。选择依据依次是：真实场景需求、官方规范证据、现有可复用基础和
可形成的最小 witness。候选触发共同 Home、address authority、capability 或 topology 缺口时，S3 构造依赖
先进入同一工作包。

| 次序 | 候选 | 进入条件 | 关键验收 |
|---|---|---|---|
| 1 | Immediate Write 的 Retry、DWT 或其他属性 profile | 场景给出一个具名属性组合和对应规范依据 | REQ→response→DAT phase、TxnID/DBID correlation、payload disposition、capability/flow closure 与 direct/XP witness |
| 2 | non-snoop Exclusive 的 monitor overflow、multi-LP 或 coherent Exclusive | 场景给出 monitor 粒度、参与者集合和竞争提交方式 | monitor owner、失效条件、EXOK/OK checkpoint、DAT disposition、资源释放和竞争 witness |
| 3 | 其余 Atomic operation/profile | operation、geometry、endianness、memory attributes 与 snoop policy 已固定 | operation-specific RMW、动态 lane/BE/CCID、same-line serialization、旧值 completion 与 direct/XP witness |
| 4 | CopyBack Retry/error | Retry 资源或具名错误来源已经进入场景 | RetryAck/P-Credit 与 reissue 维持 CAH provenance；error path 明确形成 phase、clean payload disposition 和 terminal evidence |
| 5 | deliberate dirty invalidate 与其他 CopyBack same-line 组合 | caller-visible invalidate/discard intent 或具名 opcode/phase 交错已经出现 | permission、directory、backing、residency 与 exact correlation 分别提交；交错 witness 保留新 owner 和 backing |
| 6 | Owned/dirty forwarding 扩展 | 场景需要可生成、可维持的 `SD`/Owned 状态 | dirty `SnpShared`、dirty DCT、owner handoff、replacement 和 responsibility transfer 形成闭环 |

这条队列保留以下门禁：

- Home 发出 `Comp` 后，同址 Snoop 的接纳门在 `CompAck` 后重新开放；
- Home 发出 `CompDBIDResp` 后，同址 Snoop 的接纳门在 DAT 后重新开放；
- DERR 路径以 ECC、Poison、DataCheck 或其他具名错误来源为输入；
- 容量驱动的 data/no-data outcome 由 Home/Cache VirtualDut 的容量、victim/replacement 与 residency
  policy 决定；
- coherent 与 Immediate Write 同时操作同一 backing 的场景先建立共同 Home state owner/aggregate；
- exact evidence 负责 correlation 和 phase retirement；permission、directory、backing 与 residency
  effect 继续由 participant transition 持有。

### S3 构造依赖的处理顺序

generated address router 已提供 route boundary projection、`AddressClaim`/router contract 和
direct-neighbor resolution。后续依赖按场景需要从下列顺序取用：

1. endpoint claim 自动派生、external/opaque boundary projection 与 typed port capability；
2. multi-hop address resolution 与显式 bridge auto-lowering；
3. 一个 claim/scalar Home 扩展为 multi-Home/SAM authority、system-visible window、remap 和跨 domain
   execution；
4. 场景需要观察 Home 之外的 downstream commit 时，增加独立 SN participant、HN→SN flow 和
   topology-visible commit witness。

Builder construction lowering 消费公开 boundary facts 并记录 translation plan；core elaboration 检查
展开后的 topology。backend 的私有 AddressSpace 继续由 backend 持有。

## Next · S4：resource-aware runtime

S4 在现有 `ResourceDemand`、`BLOCK` 整步回滚和显式 advance 基础上，闭合动态等待与恢复：

1. admission 从外部 action 细化到 emission/egress；
2. connection lineage 延伸到 deferred emission；
3. held lease、waiting demand、release provenance 和 recoverable wakeup 形成统一投影；
4. 多个 pending emission batch 与同 Home/type 多 waiter 具备显式选择和释放；
5. waiter-selection/fairness property 可以读取上述投影并生成 witness。

验收要求是：一次资源释放可以精确指出被唤醒的 demand，调度器随后通过实际接纳推进状态；blocked、
deferred、scheduled output 保持可区分。CHI participant pending 与 endpoint head 已提供 family-local
held/wait/wakeup 只读起点。

第二种 packet network 提出相同 runtime 接口后，再把 family scheduler 的稳定形状提取到通用 system
runtime。该门槛为共性抽取提供第二个独立证据。

## Next · S5：wait-for 与 deadlock 证据

S5 依赖显式 blocked reason、动态资源和非立即 emission。SystemProtocol 由这些运行事实构造 wait-for
graph，并在有界可达状态中寻找：

```text
reachable(state)
and non_quiescent(state)
and no_enabled_transition(state)
and open_obligations(state)
and environment_assumptions_hold(state)
```

诊断输出包括等待对象、已持有资源、开放 obligation、候选 wait cycle 和 escape transition。多 waiter
公平性、starvation 与长期调度由 scenario property 描述；deadlock verdict 处理当前状态的推进能力。

运行投影与诊断 schema 稳定后，再将 family scheduler 上提为有界并发 LTS 探索。

## Later · S6：自主 emission 与时间窗口

S6 在同步 fixed-point 基线上增加：

- backend 自主 emission 与外部 injection；
- blocked、deferred 和 scheduled output；
- 各 clock domain 的本地时间及跨域 relation；
- deadline、time window、timer、异步 FIFO、fairness 和 timeout。

CDC 由通用 control-topology 与 observation 方法提供输入；协议 family 继续提供相应 channel、lifecycle 和
capability 合同。

## 贯穿所有阶段的验收方式

每条小型完整路径提供与风险相称的证据：

1. 一个合法 witness；
2. 一个只违反目标规则的负例；
3. 可解释的 state/resource/causal projection；
4. 已覆盖的协议条款、当前 profile 边界和下一依赖；
5. 相对链接、术语、claim 与文档 owner 检查。

优先级在三种情况下重新评估：新场景出现阻塞依赖、基线违反已声明合同、官方 issue/errata 改变协议依据。
