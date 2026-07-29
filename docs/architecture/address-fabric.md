# AddressFabric VirtualDut

本文定义 address-oriented interconnect 的稳定建模方法：具名 interconnect module 接收完整地址 operation，
由 backend 保存 route、capacity、arbitration 和 completion owner，再通过显式 connections 与 system address
contract 闭合。

## 1. Interconnect 是多端口 VirtualDut

物理 decoder、mux、bridge 或 crossbar 默认建模为一个具名、多端口 `VirtualDut`：

```text
request InterfaceConnections
        ↓
ingress ports + completer attachments
        ↓
interconnect VirtualDut backend
  decode / remap / route
  store / correlate / arbitrate
  completion owner / return
        ↓
egress ports + requester attachments
        ↓
downstream InterfaceConnections
```

形态名称描述端口布局与主要行为：

| 形态 | 请求流 | 主要 capability |
|---|---:|---|
| bridge | 1→1 | protocol/profile、width、burst、attribute、ordering 与 completion translation |
| decoder-mux | 1→N | address decode、request demux、completion return |
| arbiter-mux | N→1 | admission、arbitration、owner retention |
| crossbar | N→M | route、per-egress arbitration、concurrency、response correlation |
| heterogeneous fabric | N→M | route 与 typed translation 的组合 |

这些形态由 Route、Store、Correlate、Arbitrate 和 Translation 组合。验证目标需要观察内部 module、
connection 或 hop 时，可将同一 interconnect 展开为内部 `SystemProtocol`，再封装回相同 boundary。

AddressFabric 处理带 address semantics 的 operation。stream-to-memory engine、coherent-message bridge 等
产品使用各自 typed operation，并可复用相同的 Store、Route、Correlate 和 Arbitrate 方法。

## 2. Address 对象、owner 与 route authority

### 2.1 三个核心地址对象

| 对象 | 持有的事实 | 运行 owner / consumer |
|---|---|---|
| `AddressAccess` | 一次原子 byte-range read/write、size、data/byte enable 与 attributes | attachment 产生，backend 与 endpoint 消费 |
| `AddressRoute` | input window、egress port、可选 output-base remap | interconnect backend 的 executable route table |
| `AddressSpace` | endpoint regions 及其 read/write execution | endpoint `VirtualDut` backend |

`AddressAccess` 是协议中立 operation；route identity、protocol ID 与 reply path 随 interconnect owner record
保存。`AddressSpace` 的 region state 是 endpoint 私有执行状态。

每笔 access 或 burst 必须完整落入一个 route window。命中后，`AddressRoute.translate()` 产生下游地址；
route miss 在原 ingress 形成有序 `DECODE_ERROR`。需要跨 route 拆分、width conversion 或 burst lowering 时，
construction 选择显式 typed `TranslationPlan`。

### 2.2 System authority 与 backend projection

| 对象 | 事实角色 |
|---|---|
| `AddressClaim` | receiver boundary 对本地 address window 的接收声明 |
| `AddressRouterContract` | system authority：router ingress/egress 与 route tuple |
| `AddressRouterBoundaryProjection` | interconnect backend 实际公开的稳定 route 配置 |
| `ResolvedAddressPlan` | contract、route、connection 与 direct receiver claim 的只读 closure |

生成式 interconnect 沿一条 authority 链构造：

```text
AddressRouterContract.routes
        ├─► injected VirtualDut factory ─► backend executable route table
        └─► expected boundary projection

backend boundary projection == expected projection
        └─► register VirtualDut + contract
                └─► address resolution
```

外部 RTL/RPC interconnect 以 boundary contract/projection 声明本地 decode。System closure 读取该公开投影；
endpoint `AddressSpace` 与 interconnect 私有队列继续由各自 backend 执行。

## 3. Attachment 与 backend 的状态交接

ingress 使用 `AddressCompleterAttachment`，egress 使用 `AddressRequesterAttachment`：

```text
upstream CanonicalEvent
  → completer attachment state
  → AddressAccess + opaque reply context
  → fabric route / queue / owner state
  → AddressRequest(local request_id, translated access)
  → requester attachment state
  → downstream CanonicalEvent

downstream completion
  → requester attachment decode
  → owner lookup
  → completer attachment encode(reply context)
  → upstream completion
```

| 状态 | owner |
|---|---|
| single-access AW/W join、AHB phase、端口 partial transaction | 对应 attachment state fragment |
| AXI4 burst AW/W assembly | write backend 的 port-local assembly state |
| ingress FIFO、route result、arbiter cursor、local request ID | interconnect backend state |
| reply context、selected egress、completion owner | interconnect backend pending ledger |
| endpoint register/memory contents | endpoint backend / `AddressSpaceState` |
| connection-local protocol legality | `InterfaceSession` |

`InterfaceAttachmentBinding` 是 port 与 attachment 的 immutable 关联。`VirtualDut` construction 核对公开
binding 与 backend 实际投影的对象身份；所有 attachment state fragment 和 cross-port owner 都嵌入同一份
backend state。

### 3.1 Completion 与错误

| 结果 | 处理路径 |
|---|---|
| route hit | backend 建立 owner，向所选 egress 发出 translated request |
| route miss | backend 在原 ingress 按 ordering 位置完成 `DECODE_ERROR` |
| endpoint decode/access result | requester attachment 解码，owner ledger 返回原 ingress |
| read-only register write / write-only register read | endpoint 产生 `ACCESS_ERROR`，attachment 编码协议错误响应 |
| unknown completion / wrong egress / owner mismatch | `ConstraintScope.VIRTUAL_DUT` 的 `SemanticFault` |

AMBA attachment 将 `DECODE_ERROR` 映射为 AXI `DECERR` 或相应 AHB/APB error，将 `ACCESS_ERROR` 映射为
AXI `SLVERR` 或相应 AHB/APB error。正常设备错误保留为 transaction completion；模型 fault 表示 owner、
binding 或 backend invariant 失效。

## 4. Executable profile 对照

| Profile | 请求边界 | Admission / scheduling | Ordering 与 owner return | Interface contract |
|---|---|---|---|---|
| `SingleIngressAddressFabricBackend` | 1×M atomic `AddressAccess` | 单活动请求，命中后立即向 egress 发射 | local request ID 保存 egress、reply context 与 owner | 任一匹配的 address completer/requester attachments |
| `ScheduledAddressCrossbarBackend` | N×M atomic `AddressAccess` | per-ingress finite FIFO；显式 service opportunity；per-egress round-robin | 每 ingress/egress 一笔 active，pending owner 返回 completion | 当前 concrete recipe 使用 homogeneous AXI4-Lite profile |
| `Axi4ReadCrossbarBackend` | N×M AXI4 AR/R burst | accepted AR 建立 bounded pending-burst entry | `(ingress, RID)` destination lock + `(egress, RID)` return-owner FIFO | read-only AXI4 profile |
| `Axi4WriteCrossbarBackend` | N×M AXI4 AW/W/B burst | per-ingress AW/W assembly；complete burst store-and-forward | AW acceptance 建立 BID destination slot；B owner FIFO 退休 | write-only AXI4 profile |

`build_axi4_read_demux_vdut()` 是 read backend 的 1×M configuration，沿用同一 route 与 owner algorithm。
N 与 M 分别由 ingress/egress port tuple 决定。

### 4.1 Read-only 与 write-only InterfaceProtocol

AXI4 slice 保留五 channel interface shape，并用 `InterfaceProtocol.forbidden_event_kinds` 明确 inactive
channels：

| Profile | active events | prohibited events |
|---|---|---|
| `build_axi4_read_only_profile()` | AR、R | AW、W、B |
| `build_axi4_write_only_profile()` | AW、W、B | AR、R |

recipe 接受上述 profile 或等价的 prohibition contract。InterfaceSession 和 attachment 在接口作用域执行
event prohibition，backend 专注已声明 slice 的 route、capacity 和 return owner。

### 4.2 Capability 与策略 owner

| 主题 | 声明/执行 owner | Closure 方式 |
|---|---|---|
| address semantics | attachment capability | 端口产生 typed `AddressAccess` 或 AXI burst |
| transfer size、alignment、data width、byte enable | port capability + translation plan | direct compatibility 或显式 split/remap/reject |
| burst、outstanding、ID、ordering | interface profile + backend ledger | capacity、destination lock、owner return |
| exclusive/atomic | protocol profile + source-qualified identity policy | direct support、ID remap 或 construction rejection |
| protection/cache/QoS attributes | typed operation + translation stage | preserve、rewrite、default、drop 或 reject |
| response/error representation | attachment | `AccessStatus` ↔ protocol completion |
| local arbitration | interconnect backend | fixed/round-robin/selected policy 与 cursor state |
| maximum wait、fairness、bandwidth、QoS target | system/scenario property | trace/monitor verdict |
| pin READY/VALID、cycle timing | observation/driver profile | event admission 的 cycle-level projection |

不同 protocol/profile 的端口通过 typed `TranslationPlan` 连接 semantic shape、cardinality、attribute 与
completion fold。具体 stage 合同见
[Bridge 与类型化事务转译](typed-transaction-translation.md)。

## 5. Capacity、owner return 与 ordering

### 5.1 Capacity admission

所有 queue、assembly buffer、active-ID table 和 pending ledger 都声明有限 capacity，以及 operation 被接纳、
阻塞或报错的语义。scheduled atomic crossbar 提供三种 ingress FIFO exhaustion policy：

| Policy | 语义 |
|---|---|
| `BLOCK` | 当前 operation 保持未接纳；`SystemSession` 原子回滚该 external action |
| `ERROR_COMPLETION` | 接纳一个有界、按 ingress 排序的 error marker，并在旧工作完成后返回错误 |
| `FAULT` | 将超限解释为模型或使用合同违规 |

`ScheduledAddressCrossbarBackend` 的 FIFO capacity 统计完整 `AddressAccess`；AXI4-Lite AW/W fragment 属于
attachment assembly state。AXI4 read profile 分别限制 active RID 与每 RID pending bursts；write profile
分别限制 AW/W assembly storage、active BID 与每 BID accepted bursts。AXI4 read/write bounded ledger
exhaustion 返回 typed `ResourceDemand`，由 caller 在资源释放后重试。

event-level capacity 描述 operation admission。READY/backpressure、wait-state 和 simultaneous pin offers 由
observation/driver 与 cycle scheduling profile 进一步投影。

### 5.2 Ordering 与单一 owner ledger

scheduled atomic crossbar 以每 ingress、每 egress 至多一笔 active 保持 ingress order；route miss 留在同一
ingress queue，并在前序工作退休后产生错误。一次 service opportunity 可向不同空闲 egress 各 grant 一笔，
且每个 ingress 本轮取得至多一次 grant。

AXI4 read backend 用一份 accepted-burst ledger 派生两种查询：

```text
(ingress, upstream RID)   → destination lock + outstanding count
(egress, downstream RID) → FIFO[pending burst owner]
```

destination lock 将同一 ingress/RID 的 outstanding bursts 保持在同一 egress；return-owner FIFO 按 downstream
acceptance order 逐 beat 返回，并在 RLAST 退休 owner。`raw-ID-serialized` profile 保留 RID；普通
`lock=0` traffic 因同名 downstream RID 获得额外串行关系。该 execution profile 拒绝 multi-ingress
exclusive；source-qualified downstream identity 由 prefix/allocator/remap profile 提供。

AXI4 write backend 分开保存 port-local AW/W assembly 与 route/ordering ownership。它接受 W-before-AW；
完整 burst 以 `AW → W[0..WLAST]` batch 发往 egress。accepted-write ledger 从
`(egress, downstream BID)` 派生 B owner FIFO。route miss 先消费与 AW 匹配的完整 W burst，再在原 ingress
产生 ordered `DECERR`，从而保持无 ID W stream 的配对顺序。

`DutAdvanceAction` 表示 caller 提供的一次 service opportunity。local round-robin cursor 决定当前 enabled
owner 的选择；clock period、长期 fairness 和 maximum wait 分别由 timing profile 与 system property 定义。
AXI4 read/write profile 以 canonical AR 或完整 AW/W operation 的提交顺序作为当前 execution witness 的
admission order；simultaneous pin offers 与 cycle grant 由 observation/scheduling profile 具体化。

## 6. System address closure

System construction 为每个 interconnect port 建立显式 point-to-point `InterfaceConnection`。
`SystemProtocol.connections` 是 topology 的唯一权威；interconnect backend 保存 module 局部 route 与 owner
state。

生成式 router 的 closure 顺序为：

1. `AddressRouterContract` 声明 router、ingress/egress 与 canonical route tuple。
2. `SystemProtocolBuilder.construct_address_router()` 将完整 contract 交给 injected factory。
3. factory 构造 `VirtualDut`，backend 从实际配置公开 `AddressRouterBoundaryProjection`。
4. Builder 在注册前核对 ports、normalized routes 和 egress mapping。
5. elaboration 将每个 ingress×route 闭合到同一 egress connection 上唯一、覆盖 translated window 的
   direct-neighbor `AddressClaim`。

这条 resolution 证明 system declaration、interconnect boundary 与直接 receiver claim 的一致性。端到端
multi-hop reachability、external projection adapter 和 runtime system resource analysis 沿同一 authority/projection
边界扩展。

interconnect 作为单个 `VirtualDut` 时，System monitor 观察 boundary events；展开成内部 `SystemProtocol`
时，内部 queues/hops 可进入 wait-for 与 refinement analysis。两种 realization 共享相同外部 contract。

## 7. 实现索引与后续入口

当前可执行 profiles 包括 single-ingress AddressFabric、scheduled AXI4-Lite N×M crossbar、AXI4 AR/R N×M
crossbar、read 1×M demux configuration 与 AXI4 AW/W/B N×M crossbar。它们分别验证 atomic access、
explicit scheduling、burst/RID owner return 和 AW/W assembly/BID return。

具体 recipe、witness、profile 限制和回归证据统一见
[实现状态](implementation-status.md)。Full AXI read/write composition、cut-through/cycle-level admission、
downstream ID remap/exclusive、heterogeneous capability closure、system fairness/wait-for、external projection
和 multi-hop address resolution 的依赖顺序见
[Roadmap](technical-route/08-roadmap.md)。

相邻文档：

- [VirtualDut 方法论](virtual-dut.md)
- [VirtualDut 源码导航](../../protocol_model/virtual_dut/README.md)
- [SystemProtocol 组网架构](network-construction.md)
- [容量、接纳与背压](capacity-admission-and-backpressure.md)
- [Bridge 与类型化事务转译](typed-transaction-translation.md)
- [AMBA integration recipes](../../protocol_model/integrations/recipes/amba/README.md)
