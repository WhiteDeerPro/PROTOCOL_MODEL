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
决定访问结果。当前二者可能分别声明窗口；在 SystemProtocol address-closure 检查完成前，route table
负责选择出口，终点保留返回 decode/access error 的权利。

## 4. Port attachment 与跨端口 backend

`ProtocolPort` 与 attachment 先形成不可变 `PortAttachmentBinding`。同一个 binding 对象同时交给
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

Attachment state 保存一个端口内部尚未组成 operation 的运输状态，例如 APB requester 的唯一 pending
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

地址未命中时不产生下游事件，而是在 ingress 直接返回 `DECODE_ERROR`。completion 先接受单 link 与
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
一个 APB ingress，当前不需要 arbiter 或 FIFO。SystemProtocol 仍持有三条明确的 point-to-point link；
Fabric 不建立与 topology 并行的隐式总线。

该 recipe 位于 `protocol_model.integrations.recipes.amba.fabrics.apb`：它是 APB attachment 与通用
AddressFabric 之间的装配根。APB 定义本身不提供 `attach(vdut)`，VirtualDut 核心也不维护 AMBA
协议名单。

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

## 7. 当前实现边界

当前单入口 AddressFabric backend 尚未覆盖：

- 多 ingress arbitration 与 fairness；
- 多 outstanding owner table；
- blocked/deferred emission 和 APB 周期级 wait；
- route table 与 endpoint address claim 的 SystemProtocol 闭合；
- AXI4 exclusive-aware endpoint 与并发 manager requester；
- 内部 SystemProtocol 展开及 boundary refinement；
- downstream fault 后整个同步宏步的原子回滚。

AXI4-Lite→APB 与严格串行 full AXI4→APB 已作为独立 bridge witness 实现；它们的 typed stage/executor
重构记录在 [V1 实施计划](translation-v1-plan.md)。AddressFabric 近期的专属工作是 address capability/claim
闭合和多入口共享状态，不在本页重复 bridge 迁移顺序。
