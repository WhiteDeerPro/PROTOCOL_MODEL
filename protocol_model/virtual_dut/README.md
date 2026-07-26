# VirtualDut source layout

`VirtualDut` 始终表示一个具体、具名的 module 边界。这个边界可以只有端口声明，把真实实现留给 RTL、RPC、
trace 或外部 oracle；也可以由本项目把 attachment、队列、状态机、地址空间、route 或 translation executor
组合成一个可执行实现。两种情况使用同一种 module/topology 身份，但可观察到的内部深度不同。

```text
VirtualDut boundary
├── InterfacePort(s)          对外协议、role、clock/reset domain
├── InterfaceAttachmentBinding   可选：端口事件与内部 operation 的转换
└── realization
    ├── opaque/external     内部状态不由本项目展开
    ├── constructed         attachment + backend + 可复用行为组件
    └── composite           内部封装一个 SystemProtocol
```

`backend` 只是 constructed realization 中执行状态转移的部分，不等于整个 VirtualDut，也不包含
`InterfacePort`、binding 或具体协议 attachment。更完整的说法是：integration recipe 组合出一个
**AMBA-bound constructed VirtualDut realization**。

## 0. 先从哪里找到一个 VirtualDut

如果目标是直接构造一个已经绑定协议的 endpoint、bridge、fabric 或 control module，从
[`protocol_model/integrations/recipes/`](../integrations/recipes/README.md) 开始。那里有按用途分类的公共 facade
和机器可读 catalog；例如可以按 `kind="bridge"` 或 `kind="fabric"` 查询，而不必先猜 builder 名称。

CHI coherent cache 是一个稍宽的 integration 产物。协议中立 `CacheLineStore` 先持有 resident line
presence/data，`CacheCore` 先于协议选择提供具名 backend/core 身份（尚不是 topology module），
`attach_chi_issue_h_coherence()` 再增加 RN
permission、pending transaction、具名
`VirtualDut` transport ports 和 family-local transaction facet；`build_chi_issue_h_cache_vdut()` 是按这个
顺序组合两步的便捷入口。当前 CHI runtime 直接执行 participant/facet，尚未把 packet 输入接到通用
`VirtualDutBackend`，也尚未声明 CPU-side port、replacement policy 或 MMU。

coherent Home 使用相同的构造方向，但 payload contract 不与 directory 混合：
`FullLineBackingCore` 保存固定 resident line，并提供 pure `prepare_write()` 与 line-local versioned
`commit_write()`；CHI participant 只保存 directory、pending transaction 和 prepared write obligation。
`attach_chi_issue_h_home()` 从 core 创建第一个 Home VirtualDut，
`bind_chi_issue_h_home_vdut()` 则把 core/participant facet 绑定到调用方已有的同一个 canonical boundary。
当前 binder 拒绝带独立 executable backend 的 Vdut，因为通用 backend runtime 与 CHI participant runtime
尚未共享一个 module state；可观察的 HN→SN physical commit 需要后续显式协议路径。

本目录中的 [`recipes/`](recipes/README.md) 是协议无关的构造基础，主要供 integration 开发者使用。某个
SystemProtocol 中已经构造出的 `VirtualDut` 实例由该 system/scenario/project 持有；test 只验证构造方法，
showcase 只给出实例用法，两者都不是 VirtualDut 产品清单。

## 1. 目录按职责组织

本目录按职责分层，不按 APB、AXI、Memory、Crossbar 等设备名称建立类型树：

```text
virtual_dut/
├── arbitration.py        pure round-robin selection primitives
├── boundary/
│   ├── module.py           VirtualDut module boundary
│   └── port.py             InterfacePort
├── binding/
│   ├── port.py             InterfaceAttachmentBinding
│   └── builder.py          VirtualDutBuilder
├── attachments/
│   ├── base.py             单端口 attachment SPI
│   ├── address.py          AddressAccess requester/completer contract
│   ├── address_operation.py  grouped address-operation contract
│   ├── notification.py     edge notification/completion operation contract
│   ├── relay.py            stateless canonical-event boundary validation
│   ├── stream.py           StreamTransfer contract
│   └── empty.py            idle/blackhole boundary intent
├── backend/
│   ├── base.py             VirtualDutBackend execution contract
│   ├── transition.py       PortInput/Emission、DutTransition、DutEffect
│   ├── advance.py          caller-owned explicit progress contract
│   ├── stepped_emission.py bounded deferred output + per-event gaps
│   ├── simple.py           NoOp/Capture/Function fixtures
│   ├── address_space.py    immediate AddressSpace endpoint
│   ├── queued_address.py   finite FIFO + delay/service FSM
│   ├── sensor_fifo.py      显式采样、有限 FIFO、overrun policy
│   ├── memory_copy.py      单 outstanding、固定 descriptor copy engine
│   ├── interrupt.py        edge 汇聚、priority、target EOI fixture
│   ├── cache.py            resident-line store；协议 permission 由 attachment/facet 持有
│   ├── backing.py          fixed full-line backing；pure prepare + line-local commit
│   └── stream.py           ordered stream capture
├── address/
│   ├── access.py           AddressRead/Write/Result
│   ├── burst.py            grouped AddressBurst
│   ├── attributes.py       protocol-neutral access attributes
│   ├── target.py           stateful AddressAccess execution contract
│   ├── space.py            address dispatch
│   ├── memory.py           sparse reference memory region
│   └── register.py         reference register region
├── fabric/
│   ├── route.py            AddressRoute 与静态窗口检查
│   ├── ownership.py        跨端口 active-request owner record
│   ├── single_ingress.py   单入口 state + 立即 decoder/response mux
│   ├── crossbar_state.py   per-ingress FIFO、cursor 与 owner snapshot
│   └── crossbar.py         显式推进的 N×M address crossbar backend
├── translation/            typed stage/plan/executor 与 bridge backend
└── recipes/                 endpoint、translation、crossbar、DMA、interrupt 的协议无关装配根
```

APB、AHB、AXI 等具体转换不属于本目录的核心类型。单端口实现位于
`protocol_model/integrations/attachments/`，协议约束下的跨端口执行位于
`protocol_model/integrations/backends/`，成品构造位于 `protocol_model/integrations/recipes/`；它们同时依赖
InterfaceProtocol 定义和这里的 attachment/backend 契约，通用 VirtualDut 层不反向导入协议名单。

## 2. 三段构造过程

以 queued APB responder 为例：

```text
virtual_dut core recipe
  QueuedAddressResponderBackend + prepared InterfaceAttachmentBinding
                         │
                         ▼
AMBA integration recipe
  select ApbCompleterAttachment + APB4 InterfacePort
                         │
                         ▼
AMBA-bound VirtualDut
  port + binding + attachment + FIFO/FSM + AddressSpace
                         │
                         ▼
SystemProtocol construction
  source VirtualDut + InterfaceConnection(APB4) + target VirtualDut
```

因此：

- `build_queued_address_responder_vdut()` 接收已经准备好的 binding，是协议无关装配；
- `build_amba_queued_address_responder_vdut()` 选择具体 AMBA attachment，返回 integration 后的 VirtualDut；
- 单个 AMBA-bound VirtualDut 只是一个 AMBA endpoint module；双方 role 绑定到一个
  `InterfaceConnection` 后，才形成一条具体 AMBA interface instance；
- `SystemProtocol` 拥有最小可执行通信实例，`SystemSession` 拥有该实例的一次运行状态与 trace。

Scheduled crossbar 使用同样的三段构造，只是一个成品拥有多组 binding：

```text
prepared AddressCompleter/Requester bindings
                    │
                    ▼
build_scheduled_address_crossbar_vdut()
  per-ingress FIFO + per-egress round-robin + owner return
                    │
                    ▼
AXI4-Lite integration recipe
  N subordinate ports + M manager ports
                    │
                    ▼
SystemProtocolBuilder + AddressRouterContract
  explicit connections + direct-neighbor AddressClaim resolution
```

Core crossbar 只处理 `AddressAccess`、route 与本地调度，不导入 AXI4-Lite。Integration recipe 为每个端口
创建独立 attachment；System construction 则负责端口连接和地址声明闭合，不持有 FIFO、cursor 或 owner。

当前还提供三组面向组网实验的工具型 realization：

- `SensorFifoBackend` 通过显式 service opportunity 生成确定性样本，并从固定地址寄存器弹出 FIFO 头部；
- `SerializedMemoryCopyBackend` 用一个 requester port 交替发出 read/write，支持固定源地址和递增目标地址；
- `PriorityInterruptControllerBackend` 汇聚多个 edge notification，按优先级向一个 target 投递并等待 EOI。

这些 backend 用于检验容量、路由、完成返回和控制通知。它们没有宣称覆盖完整传感器、DMA 寄存器模型或
GIC/PLIC 软件架构；具体协议端口仍由 integration recipe 选择和绑定。

`SteppedEmissionBackend` 是一个较小的 realization refinement：它包裹纯、立即完成的 backend，把已经产生的
`PortEmission` 批次放入有限 FIFO，并通过显式 advance 逐个释放。它适合给 AXI R beat 等 event witness
加入可配置间隔；请求执行时刻仍由内层 backend 决定，且没有自动获得 clock、VALID/READY 或物理时间语义。
非破坏式 offer/accept 接口允许调度器选中一个事件后继续持有，只有明确 accept 才从 FIFO 移除；
它是以后生成 ready/valid pin driver 的状态所有权边界，当前尚未自动映射到具体协议信号。

## 3. constructed realization 怎样展开

当前 `VirtualDut` 已公开 ports、bindings 和 backend。可视化层对已知 constructed backend 做显式 projector，
可以显示 attachment codec、FIFO/FSM、AddressSpace、route/owner、TranslationPlan，以及当前 Sensor、DMA、
interrupt controller 的公开构造属性；未知 backend 只显示为 opaque 节点。projector 不读取任意
`__dict__`，也不让 backend 依赖显示代码。

`ScheduledAddressCrossbarBackend` 的 projector 会展开 ingress FIFO、route/remap、逐出口 arbiter 与 owner
table。该图描述构造结构，不冒充某次运行的 queue occupancy 或 grant 历史；动态状态仍从 session trace 和
专门的运行视图投影。

例如 AXI→APB bridge 的可见内部关系是：

```text
AXI port
  → AXI ingress attachment / AW-W assembly
  → typed TranslationPlan
  → serial child scheduler + owner/fold table
  → APB requester attachment / driver
  → APB port
```

这些是一个 bridge VirtualDut 内部的 constructed components。只有把内部模块和 connections/hops 也作为验证对象时，
才进一步展开成子 SystemProtocol。

实现入口位于 `protocol_model.visualization.project_virtual_dut()`、
`virtual_dut_structure_dot()` 和 `expanded_system_topology_dot()`。随机 traffic controller 属于 scenario，
显示时放在 VirtualDut 盒外，不伪装成 source backend 的内部组件。

## 4. 依赖规则

- 内部文件从叶模块导入，不从 `protocol_model.virtual_dut` 根 facade 反向导入。
- `attachments` 不依赖 `fabric`、`binding` 或 `recipes`；它只定义一个端口的转换契约。
- `binding/port.py` 只组合 `InterfacePort` 与 `InterfaceAttachment`，不保存运行状态。
- `binding/builder.py` 是本地装配层；最终产生的 `VirtualDut` 仍然不可变。
- `fabric` 可以组合 backend foundation、address operation 和 attachment binding，但不创建
  `VirtualDut`。
- `translation` 只处理已经 decode 的 operation、跨端口转换和资源生命周期，不导入具体 InterfaceProtocol；
  attachment-aware backend 负责把它的 operation emission 与端口 event 互换。
- `recipes` 是叶子装配层，可以组合上述职责；下层不导入 recipe。
- `integrations/attachments` 实现协议相关的单端口转换；`integrations/backends` 保存无法协议中立化的
  跨端口执行状态；`integrations/recipes` 装配 endpoint、fabric 和 bridge。AddressAccess 与
  StreamTransfer 仍留在协议无关核心。
- `SystemProtocol` 使用 boundary/transition 叶模块，不通过 recipe 或根 facade 建立隐式连接。

常用构造对象仍从 `protocol_model` 或 `protocol_model.virtual_dut` 导入。实现或扩展 attachment/backend
时，从对应子包导入具体接口；运行状态 DTO 不提升为根公共 API。

## 5. 输出归属

VirtualDut 构造本身不创建输出目录。Session 产生内存中的 state/trace；visualization projector 产生 DOT 或
WaveJSON；`RunArtifactStore`/具名 demo 脚本才选择目录并写入 SVG、JSON 与 manifest。普通模型运行因此不会
因为创建一个 VirtualDut 就隐式改写 `docs/` 或 `showcase/generated/`。
