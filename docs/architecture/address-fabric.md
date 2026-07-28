# AddressFabric VirtualDut

## 1. 互连模块的表示方式

默认把一个物理互连 module 表示为具名、多端口 `VirtualDut`，不预先展开内部 `SystemProtocol`：

```text
request ingress ports
        ↓
single module boundary
  decode / remap / route
  store / correlate / arbitrate
  protocol conversion policy
        ↓
request egress ports
```

`fabric` 是这种组合的描述名称，不增加位于 VirtualDut 与 SystemProtocol 之间的新语义层。以后需要
检查内部 FIFO、仲裁器或 wait-for 关系时，可以把同一 module 展开成内部系统；当前执行模型只观察
它的外部端口和跨端口行为。

## 2. Bridge、decoder 与 crossbar

这些名称由端口数量和主要行为派生，不形成设备继承树：

| 形态 | 请求流形状 | 主要行为 |
|---|---:|---|
| bridge | 1→1 | protocol/profile、宽度、burst、ordering 和错误转换 |
| decoder-mux | 1→N | 地址解码、请求选择和 completion return |
| arbiter-mux | N→1 | admission、仲裁和 owner 保存 |
| crossbar | N→M | 路由、仲裁、并发和 response correlation |
| heterogeneous fabric | N→M，端口协议可不同 | crossbar 与 bridge 行为的组合 |

在 address-oriented 范围内，bridge 可以看作路由维度退化、转换行为突出的 AddressFabric；传统 crossbar
则更突出多入口、多出口路由和仲裁。Stream 或 coherent-message bridge 不属于 AddressFabric，但仍可复用
通用 transaction translation 构造。公共代码按行为和 capability 组合，不要求这些名称互相继承。

## 3. 地址对象的边界

地址建模保留三类不同对象：

| 对象 | 含义 | 不包含 |
|---|---|---|
| `AddressAccess` | 一次原子 byte-range read/write | route、来源端口、协议 ID、返回路径 |
| `AddressRoute` | 输入地址窗口到 egress 及可选地址重映射 | endpoint 数据和寄存器状态 |
| `AddressSpace` | 终点实际执行访问的 Register/Memory region 集合 | fabric topology 和仲裁 |

Fabric 不假装拥有下游地址内容。它保存本地 route table，终点仍用自己的 AddressSpace 或外部 backend
决定访问结果。SystemProtocol 当前可以用 `AddressClaim` 声明终点边界窗口，并用
`AddressRouterContract` 保存显式 route；address resolution 检查 route 重映射后的窗口是否由同一 egress
connection 上唯一的 direct-neighbor claim 覆盖。这个闭合证明的是声明之间的一跳可达性，不读取终点私有存储，
也不代替终点在运行时返回 decode/access error。

## 4. Port attachment 与跨端口 backend

`InterfacePort` 与 attachment 先形成不可变 `InterfaceAttachmentBinding`。同一个 binding 对象同时交给
`VirtualDutBuilder` 和 AddressFabric backend，因此端口协议/role 与 backend 实际使用的 adapter 不会
分别配置。Binding 不保存 pending 或 reply context；运行状态仍只属于 backend state。

地址端口分成两个相对角色：

```text
AddressCompleterAttachment
  CanonicalEvent request → AddressAccess + opaque reply context
  AccessResult           → CanonicalEvent completion

AddressRequesterAttachment
  AddressRequest         → CanonicalEvent request
  CanonicalEvent response → AddressCompletion(request_id, result)
```

Attachment state 保存一个端口内部尚未组成 operation 的接口关联状态，例如 APB requester 的唯一 pending
request、AXI completer 的 AW/W join。完整 request decode 后，attachment 产出的 opaque reply context 与
operation 一起移交给 Fabric/bridge backend；backend 保存选择的 egress、内部 request ID、reply context 和
completion owner，形成结果后再把 context 交回 attachment 编码。

协议无关 `AddressAccess` 是优先共享的语义，不要求所有 bridge 行为都脱离协议。ID remap、跨端口
ordering 或某个协议规定的 completion policy 若直接影响 module 行为，应留在 Fabric backend 或其
boundary contract，而不是分散到彼此看不到的 attachment。

## 5. 当前可执行范围

`SingleIngressAddressFabricBackend` 当前实现同步、单入口、单活动请求：

```text
upstream request
  → completer attachment decode
  → entire access falls in one AddressRoute
  → allocate local request_id
  → requester attachment encode
  → selected downstream request

downstream completion
  → requester attachment decode(request_id)
  → pending owner lookup
  → completer attachment encode
  → upstream completion
```

地址未命中时不产生下游事件，而是在 ingress 直接返回 `DECODE_ERROR`。completion 先接受单 interface 与
attachment 检查；通过这些检查后仍找不到跨端口 owner，或从错误 egress 返回，属于 VirtualDut 语义
故障。只要仍保存 pending request，backend 就不是 quiescent。

第一个 recipe 是 `build_apb_address_fabric_vdut()`：

```text
manager ─ APB ─ fabric.upstream (completer role)
                     │
                     ├─ fabric.control (requester role) ─ APB ─ endpoint 0
                     └─ fabric.status  (requester role) ─ APB ─ endpoint 1
```

它把 decoder、request demux、pending owner 和 response mux 放在同一个 VirtualDut backend。由于只有
一个 APB ingress，当前不需要 arbiter 或 FIFO。SystemProtocol 仍持有三条明确的 point-to-point connection；
Fabric 不建立与 topology 并行的隐式总线。

该 recipe 位于 `protocol_model.integrations.recipes.amba.fabrics.apb`：它是 APB attachment 与通用
AddressFabric 之间的装配根。APB 定义本身不提供 `attach(vdut)`，VirtualDut 核心也不维护 AMBA
协议名单。

第二个可执行 profile 是 `ScheduledAddressCrossbarBackend`。它把 N 个 ingress 的完整 address operation
分别入队，通过显式 service opportunity 为 M 个 egress 仲裁，并在 completion 返回后释放本地 owner。
协议无关装配入口是 `build_scheduled_address_crossbar_vdut()`；当前具体协议 recipe 是
`build_axi4_lite_address_crossbar_vdut()`。`SingleIngressAddressFabricBackend` 继续保留单入口立即转发的
低成本路径，scheduled backend 则用于需要共享出口、排队与仲裁的 N×M 模块。

## 6. 地址端口的 capability 边界

APB、AHB-Lite、AXI4-Lite 和 AXI4 端口都可以通过各自 attachment 暴露地址请求能力，但“协议有端口”
本身不是进入 AddressFabric 的条件。例如 AXI4-Stream 没有地址访问语义；stream-to-memory 行为需要一个
显式 Transform/engine backend，不能只靠普通 address attachment 获得。

端口能够 attach 也不表示两端语义自然兼容。每条 address route 需要比较 capability，并为差异选择显式
策略：

- transfer size、alignment、data width 和 byte enable；
- burst 拆分或合并；
- outstanding、ID 和 ordering；
- exclusive/atomic；
- protection、cache、QoS 等 attributes；
- error/completion 表达和 backpressure。

这些差异由 typed TranslationPlan 显式选择 preserve、remap、split、serialize、reject 或 emulate；单端口
attachment 不静默完成有损转换。Stage、completion fold、容量 lease 与 AXI→APB witness 统一由
[Bridge 与类型化事务转译](typed-transaction-translation.md) 说明，本页只保留 address route 和 endpoint
claim 的专属边界。

## 7. Scheduled N×M address crossbar

Crossbar 最初用作方法完整性探针，因为它同时要求多入口、多出口、共享资源、响应归属和 ordering；当前
已经形成第一条可执行纵向切片。`ScheduledAddressCrossbarBackend` 是一个协议无关的 constructed backend，
AXI4-Lite recipe 把具体五通道 attachment 装到它的端口上，SystemProtocol 再用普通 point-to-point connections
连接 manager、crossbar 与 subordinate。它仍是一个多端口 VirtualDut，不因为内部含有仲裁就自动成为新的
系统层级。

### 7.1 组合对象与状态来源

| 对象 | 当前职责 | 边界 |
|---|---|---|
| `AddressRoute` | window decode、egress 选择与 address remap | 所有 ingress 共享一张静态、无重叠地址图 |
| `QueuedRoutedAddressRequest` | 保存已组成但尚未 grant 的 operation | route miss 也进入同一 ingress FIFO |
| `RoutedAddressRequest` | 保存 active request 的 ingress、egress、转换前后 access 与 reply context | completion 返回后释放 |
| `ScheduledAddressCrossbarState` | 汇总端口 attachment state、FIFO、owner table、round-robin cursor | 是 crossbar 运行事实的唯一状态来源 |
| `round_robin_grant()` | 在稳定 ingress 顺序中选择 eligible owner | 每个 egress 保存独立 cursor |
| address attachments | 终止单端口协议运输并交接 `AddressAccess` | AXI4-Lite AW/W fragment 仍由各 ingress attachment 隔离保存 |
| `DutAdvanceAction` | 提供一次显式 service opportunity | 不自动表示时钟周期或 RTL combinational/sequential 边界 |

`round_robin_grant()` 与动态 batch 使用的 `round_robin_select()` 已收敛到
`virtual_dut/arbitration.py`。它们是无协议字段知识的纯选择函数：address crossbar 使用固定 port
order/cursor，stepped response backend 使用当前 live batch order/last accepted token。Round-robin 只是局部
arbiter policy；它不读取 `AxQOS`，也不单独承诺 bandwidth、maximum wait 或端到端 fairness。

Typed bridge 的 protection/shape/route stages 仍适合异构单路径转换；当前 crossbar 没有把多个独立 serial
executor 并排后假定它们会共享仲裁。N×M dispatch、egress ownership 与 response return 由同一个 backend
统一决定。

### 7.2 调度与完成流程

每个完整 `AddressAccess` 先进入所属 ingress 的有限 FIFO。一次 `advance()` 固定本轮各空闲 ingress 的
队首，然后按稳定 egress 顺序执行：

1. 队首 route miss 在该 ingress 空闲时形成有序 `DECODE_ERROR`，不会越过它前面的 active request；
2. 每个空闲 egress 从指向自己的 eligible ingress 中执行一次 round-robin grant；
3. 同一 service opportunity 可以同时向不同 egress 发射，但一个 ingress 本轮至多被服务一次；
4. grant 建立内部 request ID 与 owner entry，并同时占用该 ingress 和 egress；
5. downstream completion 依据 owner entry 回到原 ingress，随后释放两侧 active slot。

这个 profile 通过“每 ingress、每 egress 最多一笔 active”保持严格 ingress 顺序。FIFO capacity 只统计已经
组成的 complete operation；尚未配对的 AXI4-Lite AW/W fragment 仍属于 attachment partial transaction state。容量满
默认形成 typed `BLOCK` 并由 `SystemSession` 回滚本次外部 action。可选 `ERROR_COMPLETION` 为每个 ingress
保留一个有序应急 marker，旧请求完成后才返回 `SLVERR`；正常 FIFO 仍满且 marker 已占用时，再次 overflow
仍会 `BLOCK`。显式 `FAULT` 用于把超限视为模型/使用合同违规的场景。这些策略尚未 lowering 为
READY/backpressure，也尚未投影成 system wait-for edge。

### 7.3 AXI4-Lite recipe 与 System 地址闭合

`build_axi4_lite_address_crossbar_vdut()` 显式接收 ingress names、egress names、`AddressRoute` tuple 和
per-ingress queue capacity。当前 AXI4-Lite profile 要求所有端口使用同一个 interface profile/data width，支持
静态地址重映射、独立 AW/W join、不同出口并行、共享出口轮转以及 owner return。

组网时，`AddressRouterContract` 保存 ingress、egress 和同一份 route tuple；
`SystemProtocolBuilder.construct_address_router()` 把完整 contract 交给注入的 VirtualDut factory。构造出的
backend 还会公开不可变 `AddressRouterBoundaryProjection`，Builder 在注册前比较端口顺序和规范化 route；
因此 factory 忽略 contract 或把窗口接到另一 egress 时会在 construction 阶段失败。AXI4-Lite witness 的
factory 直接把 `contract.routes` 传入 recipe，projection 则从 backend 的实际配置派生。
elaboration 随后把每个 ingress×route 闭合到该 egress connection 上唯一、覆盖重映射后窗口的 direct-neighbor
`AddressClaim`。这项 resolution 当前只证明显式一跳关系，不搜索多跳路径，也不从 N×M topology 猜测
crossbar 行为。

当前 2×2 witness 覆盖不同出口同时 grant、共享出口的单 owner 与依次 grant、按序 decode miss、每入口
AW/W join 隔离和 completion owner return。它验证的是 single-access transaction 模型，不是 RTL cycle
model。更广的 endpoint latency 组合与长期 fairness 属于后续 scenario/property 覆盖。

## 8. AXI4 AR/R N×M crossbar

`build_axi4_read_crossbar_vdut()` 保留 AXI4 AR/R burst 和 RID，接受任意非空 ingress/egress
tuple，因而 N 和 M 不需要相等。它是一个多端口 interconnect `VirtualDut`；SystemProtocol
仍显式保存每条 manager↔crossbar 和 crossbar↔subordinate `InterfaceConnection`，不从拓扑外观
推测路由行为。

该 recipe 要求 `build_axi4_read_only_profile()` 或等价的 read-only InterfaceProtocol。这个 profile
保留 AXI4 五通道 interface shape，但在构造期可见地禁止 AW/W/B event；因而系统不会把一个
只路由 AR/R 的 backend 误当成五通道 crossbar。

### 8.1 一份 pending ledger，两个归属视图

Backend 使用有界、稀疏的 accepted-burst ledger：

```text
pending burst = {
  serial,
  ingress port, upstream RID,
  egress port,  downstream RID,
  remaining beats
}

(ingress, upstream RID)  -> egress + outstanding burst count
(egress,  downstream RID) -> FIFO[pending burst owner]
```

第一个派生视图是 manager-local destination lock。同一 ingress 的同一 RID 可以向同一 egress
追加多个 outstanding burst；它在未完成时改投其他 egress，新 AR 以 `BLOCK` 返回，直到
旧路径的最后一个 RLAST 释放该 ordering domain。这避免 fabric 内存放并重排 RDATA。

第二个派生视图是 subordinate-local return-owner FIFO。多个 manager 向同一 egress 使用同一
downstream RID 时，R beat 依据 `(egress, RID)` 取得最早 accepted burst，RLAST 后再转向下一
owner。两个视图都从同一 pending tuple 派生，没有维护两份可能分歧的可变表。

Route-table profile 的 `active_id_capacity` 按 ingress 分别计算，
`outstanding_bursts_per_id` 限制一个 `(ingress, RID)` 内的 pending burst 数。它们是 VirtualDut
运行资源的可配置边界，不要求 Python 数据结构模仿某种 RTL table 实现。

### 8.2 `raw-ID-serialized` profile

当前 profile 原样保留 ARID，即 `downstream RID == upstream RID`。不同 manager 在同一 subordinate
使用同一 RID 时，会被并入一条合法的 downstream same-ID ordering stream。这会给原本独立的请求
增加串行关系，但对普通 `lock=0` read 不会丢失返回归属。不同 manager 的同名 RID 若位于
不同 egress，它们仍是独立 ordering domain，可以按任一合法顺序完成。

多 ingress exclusive read 暂时拒绝，因为仅保留 raw RID 不足以向 downstream 传递 source-qualified
exclusive identity。后续可增加 `{ingress, RID}` prefix 或 allocator/remap profile；`Axi4PendingRead` 已分开
`upstream_id` 与 `downstream_id`，因此新策略可继续使用同一 return-owner lifecycle。
同宽 allocator/remap 可直接使用这两个字段；如果 prefix 需要扩大 downstream ID width，recipe 还需
允许 ingress/egress 使用不同但兼容的 interface profile，不只是替换 ledger 策略。

### 8.3 事务接纳与 1×M 特化

Canonical AR event 在进入 backend 时已表示一笔 accepted transfer，因而调用方提交这些 event 的
顺序就是该 execution witness 的 grant 顺序。当前切片不额外规定同时 ARVALID 的仲裁、ACLK
周期或 RREADY 停顿；这些需要在 pin/cycle observation 或具体调度 profile 中表达。整个 burst 未落在
同一 route window 时，backend 在原 ingress 生成 ARLEN+1 个有序 DECERR beat。

`build_axi4_read_demux_vdut()` 是通用 N×M backend 的 1×M recipe 配置，不再维护另一套 demux subclass 或
路由算法。`CanonicalEventRelayAttachment` 只复用端口方向和 schema 检查，RID 解释、
destination lock 和 return owner 仍属于 interconnect VirtualDut backend。AXI InterfaceProtocol 用自己的
monitor ledger 检查 beat count、RLAST 和 same-ID ordering，不与 backend 共享一份可变状态。

2×4 executable witness 选择两个 manager 和四个 memory target，覆盖同 egress/raw RID 的 owner
队列、不同 manager 的 RID namespace、同 manager/RID 跨目标 `BLOCK` 以及 RLAST 后重试。这个实例
用来证明 N 与 M 可独立配置；写侧使用下面的独立 AW/W/B slice。

## 9. AXI4 AW/W/B N×M crossbar

`build_axi4_write_crossbar_vdut()` 使用保留五通道 shape、禁止 AR/R 的
`build_axi4_write_only_profile()`。每个 ingress 独立保存尚未配对的 AW descriptor、完整的 pre-AW W burst
以及当前未到 WLAST 的 W prefix，因此允许协议规定的 W-before-AW。AW 被接纳时即取得该 ingress/BID 的
destination slot；同一 ordering domain 尚未退休时改投另一 egress，或超过 active-ID/per-ID capacity，返回
`ResourceDemand`，整个外部 action 由 SystemSession 回滚。

当最老 AW 与最老完整 W burst 配对后，当前 profile 按 `AW → W[0..WLAST]` 把整笔 burst 作为一个
store-and-forward emission batch 送往选定 egress。它保留 AWID，并为每个 `(egress, downstream BID)` 从
accepted write ledger 派生 B owner FIFO；B 返回后转回原 ingress 并退休该 owner。多个 ingress 在同一
egress 使用相同 BID 时，因而按下游 AW 接纳顺序恢复归属。不同 ingress 或不同 egress 的 ordering domain
仍可独立完成。

地址未命中不会在只看到 AW 时提前返回 B。Backend 先按 FIFO 消费与该 AW 对应的完整 W burst，再在原
ingress 产生一个普通 `DECERR` completion，避免遗留的无 ID W burst 错配给下一笔 AW。跨窗口 burst 同样按
decode miss 处理；地址重映射还要求保持 WDATA/WSTRB 所对应的物理 byte lane，因为 W 本身不携带地址。

`Axi4BurstAssemblyProfile` 分别限制 pending AW、pre-AW complete W burst 和 buffered W beat；
`Axi4WriteRouteTableProfile` 限制每 ingress 的 active BID 数以及每 BID accepted burst 数。前者描述 port-local
assembly storage，后者描述 route/ordering ownership，两者不会合并成一个含义模糊的 FIFO depth。

Canonical action 的提交顺序仍是这一 execution witness 的 grant 顺序。当前 slice 没有声称实现逐拍
AW/W arbiter、cut-through forwarding、WREADY pin 生成或 cycle-level round-robin。后续 streaming profile
需要在 downstream AW 接纳时建立 W-route token，并把选中 egress 的 W ownership 保持到 WLAST。

## 10. 当前实现边界

当前 fabric profiles 尚未覆盖：

- 把现有 AXI4 AR/R 与 AW/W/B slice 组合成一个五通道 Full AXI crossbar backend；
- AXI4 write cut-through、逐 W beat egress ownership 与 pin/cycle AWREADY/WREADY admission；
- AXI4 downstream ID prefix/remap、多 ingress exclusive identity、同时 pin offer 仲裁与 R-channel
  cycle-level admission；
- QoS/priority、broadcast、动态 route、width conversion 与通用 atomic policy；
- FIFO full 对 AXI READY 的 cycle-accurate backpressure，以及 APB/AHB wait-state 的 RTL 周期投影；
- round-robin 的 system fairness/maximum-wait monitor、held-resource/wait-for/deadlock 分析；
- scheduled address crossbar 多 egress 同次 advance 的 emission-level admission；当前任一
  destination `BLOCK` 会回滚同批其他出口，形成保守的跨出口耦合；
- deferred grant emission 到原 ingress event 的跨 connection provenance；
- 外部/opaque crossbar 的 assertion 与 boundary projection 核对，以及多跳 address resolution；
- 内部 SystemProtocol 展开、boundary refinement 和 downstream fault 后整个系统宏步的原子回滚。

单入口 AddressFabric、scheduled N×M address crossbar、AXI4 AR/R 与 AW/W/B N×M slices，以及 AMBA serial bridge
解决的是不同边界的问题。统一 AMBA
serial builder 继续负责 AXI4/AXI4-Lite/AHB/APB 的跨协议 operation translation；scheduled crossbar recipe
把 AXI4-Lite 单访问 attachment 装到共享调度 backend 上，AXI4 read/write crossbar 则分别保留原始
AR/R 或 AW/W/B burst 与 ID，read 1×M demux 从同一读算法特化。
这些切片的后续交汇点是 typed capability、boundary projection 与系统资源分析；当前仍不是完整、
cycle-accurate 的 Full AXI crossbar。
