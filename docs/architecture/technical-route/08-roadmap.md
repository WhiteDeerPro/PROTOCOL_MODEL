# 实施路线与阶段边界

[返回架构地图](README.md) · [查看总览图](overview.svg) · [项目 Roadmap](../../../ROADMAP.md)

这条路线按“下一个真实场景缺少什么”递归补共享能力，而不是把工程误画成唯一的上下层，或按协议名称与
软件包数量推进。三张视图见[通信建模的三张视图](../communication-scope-and-transport.md)。

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
转换成 `AddressRead`，并让 `AddressTarget` 独占本地 memory state。`PCrdReturn`、NodeID ownership、
feature-flow closure 和 clean `ReadShared/ReadUnique` participant 也已落地。当前
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
生成/维持 policy，也没有把 reference update 冒充独立 Memory/SN physical commit。
第一条 construction authority
切片现已闭合：CHI 合同引用通用 `AddressClaim`，为本次 feature scope 选择唯一 Home，并从
coherence-domain membership 派生 `eligible Snoopees = members - requester`；NodeID、逐成员 capability
与 REQ/SNP/RSP/DAT flow 随后使用同一派生结果闭合。Home directory 仍只选择一笔事务的实际 holder，
不取代静态 domain authority。

1. 在已闭合的显式 `UD` topology writeback 基础上，增加 Retry/error/Snoop 并发与可选的
   victim/writeback scheduling；replacement policy 保持独立 refinement；
2. 在已闭合 clean/shared-dirty-peer `CleanUnique`、协议中立 Home backing 与 canonical Home binder
   基础上，按实际场景补 `MakeUnique` 与 clean `Evict`；只有验证目标需要观察 physical commit 时，再增加
   topology-visible HN→SN flow，而不是把已有 AXI/APB memory backend 暗绑为同一 state；
3. 增加同 line transient/hazard、Retry/error 组合、多 waiter policy、多个 pending emission batch 与
   wait-for projection；
4. 将当前只供 CleanUnique 消费的预置 `SD` 扩展为可生成、可维持的 Owned lifecycle，再以 dirty
   `SnpShared`、owner handoff、replacement 与 forwarding/DCT 检验 MOESI-like 扩展；
5. 第二种 packet network 提出相同接口后，再把 family scheduler 的稳定形状投影到通用 system runtime。

当前每个 resolved feature scope 显式选择一个未进入 address-router translation 的 address claim 和一个
scalar Home，RN participant 仍投影一个预配置 `home_node_id` 并由 resolver 核对；同一 runtime 按地址动态
切换多个 Home、由 SAM route 派生 system-visible window、remap 和跨 domain 执行尚未实现。
read/retry/coherence profile 另固定单 Requester、受限 opcode 与 full-line DAT；
AddressTarget 路径固定对齐和成功 completion；coherent Home backing 是 fixed-resident、同步、无 blocked
的 line-local commit profile，尚未等价于独立 SN physical memory。它们是上述工作的可执行起点；准确覆盖仍只在
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
物理时钟。

### S5 · wait-for 与 deadlock 证据

有了显式 blocked reason、动态资源和非立即 emission 后，SystemProtocol 才能构造 wait-for graph。分析目标
不是简单寻找拓扑环，而是寻找可达、非 quiescent、无 enabled transition、且 obligation 未完成的状态。

输出应包含：等待谁、持有什么资源、哪条 obligation 未关闭、是否存在 escape transition。

### S6 · 自主 emission 与时间窗口

当前同步 fixed-point 适合点到点和微型 bridge。异步扩展需要区分：

- backend 自主 emission 与外部 injection；
- blocked、deferred、scheduled output；
- 本地时钟和跨域不可比时间；
- deadline/time window，而不是强行使用一个全局 cycle。

这一步以后才能严谨表达 timer、CDC、异步 FIFO、长期 fairness 和 timeout。

## 贯穿所有阶段的验证方式

每条小型完整路径只需要与风险相称的证据：

1. 一个合法 witness；
2. 一个只违反目标规则的负例；
3. 可以解释的 state/resource/causal projection；
4. 明确记录仍未覆盖的规范条款和基础能力。

测试是验证架构判断的手段，不以 case 数量代替架构进度。
