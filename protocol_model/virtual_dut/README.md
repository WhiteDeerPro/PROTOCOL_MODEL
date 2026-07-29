# VirtualDut 源码导航

`VirtualDut` 表示 topology 中具体、具名的 module 边界。端口声明建立它的外部通信身份；realization 决定
内部行为来自 RTL、RPC、trace、外部 oracle，还是由本项目构造的 attachment、backend 与行为组件。

外部实现与 constructed realization 共用同一种 module 身份。二者的区别是内部可观察深度：

```text
VirtualDut boundary
├── InterfacePort(s)          对外协议、role、clock/reset domain
├── InterfaceAttachmentBinding   可选：port 与 attachment 的静态关联
└── realization
    ├── opaque/external     内部状态由外部实现持有
    ├── constructed         attachment + backend + 可复用行为组件
    └── composite           内部封装一个 SystemProtocol
```

constructed realization 由 integration recipe 把 `InterfacePort`、binding、attachment 与 backend 组合为
完整 module。backend 在其中持有功能状态和状态转移。

## 1. 选择构造入口

| 目标 | 入口 | 产物 |
|---|---|---|
| 构造已绑定协议的 endpoint、bridge、fabric 或 control module | [`integrations/recipes/`](../integrations/recipes/README.md) | 可直接加入系统的 concrete `VirtualDut` |
| 开发协议无关的装配方法 | [`virtual_dut/recipes/`](recipes/README.md) | 接收已准备 binding 的 core recipe |
| 声明外部 RTL、RPC、trace 或 oracle module | `VirtualDutBuilder` 与 `boundary/` | opaque/external `VirtualDut` |
| 查看 CHI participant 的组合入口 | [CHI Issue H 源码导航](../protocols/amba/chi/issue_h/README.md) | transport-boundary module 与 family participant facet |
| 查看当前覆盖范围 | [实现状态](../../docs/architecture/implementation-status.md) | 唯一的当前能力矩阵 |

`integrations/recipes` 提供按用途分类的公共 facade 和机器可读 catalog，可按 `kind="bridge"`、
`kind="fabric"` 等条件查询。system、scenario 或调用方 project 持有构造出的具名实例；showcase 提供用法和
运行证据。

## 2. 源码职责

源码按事实所有权划分：

| 包 | 权威事实 | 交接 |
|---|---|---|
| `boundary/` | module identity、`InterfacePort` 与 transport boundary | 供 binding、recipe 和 system topology 引用 |
| `binding/` | port 与 attachment 的静态关联、构造期一致性 | 由 builder 固化到 `VirtualDut` |
| `attachments/` | 协议无关的单端口 operation SPI | 由具体协议 integration 实现 |
| `backend/` | module 功能状态、转移、显式推进与 emission | 由 recipe 选择并装配 |
| `address/` | `AddressAccess`、burst、AddressSpace 与 reference region | 供 endpoint、fabric 和 translation 使用 |
| `fabric/` | module 局部 route、仲裁、owner 与多端口 correlation | 向 system 投影公开边界与 capability |
| `translation/` | typed stage、plan、resource ledger 与 bridge executor | 由 protocol-bound translation/recipe 参数化 |
| `recipes/` | 协议无关 endpoint、fabric、translation 和 control 装配 | 供 `integrations/recipes` 绑定具体协议 |
| `arbitration.py` | pure round-robin selection primitive | 供局部 backend 组合 |

具体 APB、AHB、AXI 转换位于 `integrations/attachments/`；受协议 channel、ID 或 ordering 约束的跨端口执行位于
`integrations/backends/`；可直接使用的成品位于 `integrations/recipes/`。

## 3. 三段构造过程

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

各阶段分别产生：

- `build_queued_address_responder_vdut()`：使用已准备的 binding 完成协议无关装配；
- `build_amba_queued_address_responder_vdut()`：选择 AMBA attachment，形成 concrete endpoint；
- `InterfaceConnection`：把双方 role 连接成一条具体 interface instance；
- `SystemProtocol`：闭合最小可执行通信实例；
- `SystemSession`：保存一次运行的 state 与 trace。

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

Core crossbar 处理 `AddressAccess`、route 与本地调度。Integration recipe 为每个端口创建独立
AXI4-Lite attachment；System construction 负责端口连接和地址声明闭合。FIFO、cursor 与 owner 继续由
crossbar backend 持有。

当前还提供三组面向组网实验的工具型 realization：

- `SensorFifoBackend` 通过显式 service opportunity 生成确定性样本，并从固定地址寄存器弹出 FIFO 头部；
- `SerializedMemoryCopyBackend` 用一个 requester port 交替发出 read/write，支持固定源地址和递增目标地址；
- `PriorityInterruptControllerBackend` 汇聚多个 edge notification，按优先级向一个 target 投递并等待 EOI。

这些 backend 用于检验容量、路由、完成返回和控制通知。它们的 profile 与覆盖范围由
[实现状态](../../docs/architecture/implementation-status.md) 维护；具体协议端口由 integration recipe 选择和
绑定。

`SteppedEmissionBackend` 包裹立即完成的 backend，把 `PortEmission` 批次放入有限 FIFO，并通过显式 advance
逐个释放。它为 AXI R beat 等 event witness 提供可配置间隔；内层 backend 决定请求执行时刻。非破坏式
offer/accept 接口让调度器持有所选事件，明确 accept 后再从 FIFO 移除。clock、VALID/READY 与 pin driver
属于后续 observation/driver 投影。

## 4. constructed realization 的只读投影

`VirtualDut` 公开 ports、bindings 和 backend。可视化层通过具名 projector 读取 constructed backend 的公开
结构，可显示 attachment codec、FIFO/FSM、AddressSpace、route/owner、TranslationPlan 及构造属性。opaque
backend 保持为单个边界节点。

`ScheduledAddressCrossbarBackend` 的 projector 展开 ingress FIFO、route/remap、逐出口 arbiter 与 owner
table。结构图表达构造关系；queue occupancy 与 grant 历史从 session trace 和运行视图投影。

例如 AXI→APB bridge 的可见内部关系是：

```text
AXI port
  → AXI ingress attachment / AW-W assembly
  → typed TranslationPlan
  → serial child scheduler + owner/fold table
  → APB requester attachment / driver
  → APB port
```

这些构件共同组成一个 bridge VirtualDut。验证目标覆盖内部 module、connection 或 hop 时，可以进一步展开为
子 SystemProtocol。

只读投影入口包括 `protocol_model.visualization.project_virtual_dut()`、
`virtual_dut_structure_dot()` 和 `expanded_system_topology_dot()`。scenario 持有随机 traffic controller，
视图将它放在 VirtualDut 边界之外。

## 5. 依赖规则

依赖沿以下方向汇合：

```text
boundary + attachments + backend + address/fabric/translation
                              │
                              ▼
                           recipes
                              │
                              ▼
             integrations/attachments|backends|recipes
                              │
                              ▼
                     system construction
```

以下护栏保持构造事实的唯一来源：

- 内部实现从叶模块导入；根 facade 服务公共使用者。
- `attachments` 定义单端口转换契约，不得导入 `fabric`、`binding` 或 `recipes`。
- `binding/port.py` 保存静态关联；backend state 保存运行状态。
- `fabric` 组合 backend foundation、address operation 与 binding，最终 `VirtualDut` 由 recipe 创建。
- `translation` 处理已 decode operation、跨端口转换和资源生命周期；具体协议由 integration 提供。
- `recipes` 是叶子装配层，下层不得反向导入 recipe。
- `SystemProtocol` 从 boundary/transition 叶模块构造显式连接。

常用构造对象仍从 `protocol_model` 或 `protocol_model.virtual_dut` 导入。实现或扩展 attachment/backend
时，从对应子包导入具体接口；运行状态 DTO 不提升为根公共 API。

## 6. 输出归属

Session 产生内存中的 state/trace，visualization projector 产生 DOT 或 WaveJSON，
`RunArtifactStore`/具名 demo 脚本选择目录并写入 SVG、JSON 与 manifest。只有显式发布入口写入
`docs/` 或 `showcase/generated/`。

稳定设计理由见 [VirtualDut 架构文档](../../docs/architecture/virtual-dut.md)，端口绑定与协议集成见
[Integration 与 binding](../../docs/architecture/technical-route/04-integration-and-binding.md)。
