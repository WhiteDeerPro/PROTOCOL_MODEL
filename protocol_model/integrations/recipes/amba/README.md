# AMBA-bound VirtualDut recipes

AMBA recipe 是 integration composition root：选择具体 AMBA `InterfaceProtocol` 与 attachment，将它们绑定到
`InterfacePort`，组合适用的 backend，并返回具名 `VirtualDut`。AMBA 描述 module 的端口协议，module 本身继续
以边界、operation 和 backend 行为定义身份。

## 分组与公共入口

| 分组 | 构造角色 | 代表性公共入口 |
|---|---|---|
| [`endpoints/`](endpoints/) | 单边界 address/stream endpoint、主动 initiator 与 fixture | `build_axi4_address_space_vdut()`、`build_axi4_stream_capture_vdut()`、`build_amba_serialized_memory_copy_vdut()` |
| [`fabrics/`](fabrics/) | 同 family 的单入口 route/mux、scheduled N×M crossbar 和 AXI channel slice | `build_apb_address_fabric_vdut()`、`build_axi4_lite_address_crossbar_vdut()`、`build_axi4_read_crossbar_vdut()` |
| [`bridges/`](bridges/README.md) | 双边界 translation、correlation 与 completion return | `build_amba_serial_bridge_vdut()` 及收紧协议对的 convenience presets |
| [`chi/`](chi/) | transport-bound VirtualDut 与 CHI participant facet 装配 | `build_chi_issue_h_cache_vdut()`、cache/Home bind 与 attach 入口 |

完整公共名称以 [`protocol_model.integrations.recipes.amba` facade](__init__.py) 为准；按 module role、layer 和
tier 查询时使用 [`recipe catalog`](../catalog/README.md)。

## Core → integration 装配

```text
protocols/amba ───────────────┐
attachments/amba ─────────────┤
protocol-bound translations ──┼──> AMBA integration recipe ──> constructed VirtualDut
protocol-bound backends ───────┤
virtual_dut/recipes ───────────┘
```

[`virtual_dut/recipes`](../../../virtual_dut/recipes/README.md) 接收已经准备好的 bindings、protocol-neutral
operation domain 和 backend，负责 core 装配。本目录补齐具体协议选择、attachment、profile、route 和
capability，并调用相应 core recipe。

单端口 event↔operation 状态来自 [`attachments/amba`](../../attachments/amba/README.md)。AXI ID/channel
直接塑造跨端口 controller 时，本目录选择
[`protocol-bound backend`](../../backends/README.md)；可复用的保护属性等 typed stages 来自
[`translations`](../../translations/README.md)。Recipe 在 construction 阶段完成选择和参数校验。

## 关键 recipe 与 profile

| recipe | 输入 profile | 构造出的行为与准入条件 |
|---|---|---|
| `build_axi4_address_space_vdut()` | 完整 AXI4；可选 `SteppedEmissionProfile` | address endpoint；stepped profile 用有限 event FIFO 和显式 `DutAdvanceAction` 调度已计算的 R/B events |
| `build_apb_address_fabric_vdut()`、`build_ahb_address_fabric_vdut()`、`build_axi4_lite_address_fabric_vdut()` | 单入口、同 family address interface | decoder/response-mux，持有一个 completion owner |
| `build_axi4_lite_address_crossbar_vdut()` | 同一 AXI4-Lite profile 与 data width | scheduled N×M `AddressAccess` route、per-egress round-robin 与 completion return |
| `build_axi4_read_crossbar_vdut()` / `build_axi4_read_demux_vdut()` | `build_axi4_read_only_profile()` 或等价 AW/W/B prohibition profile | AR/R N×M slice；`Axi4ReadRouteTableProfile` 限制 RID domain 与每 RID pending bursts |
| `build_axi4_write_crossbar_vdut()` | `build_axi4_write_only_profile()` 或等价 AR/R prohibition profile | AW/W/B store-and-forward slice；`Axi4BurstAssemblyProfile` 与 `Axi4WriteRouteTableProfile` 限制 assembly/BID state |
| `build_amba_serial_bridge_vdut()` | 支持的 AMBA ingress/egress 与显式 routes | 按 ingress shape 选择 single-access 或 AXI4 burst→access strict-serial profile |
| CHI cache/Home recipes | Issue H participant declaration、transport ports 与 behavior facet | 将 VirtualDut assembly 交给 CHI family construction/runtime 继续组合 |

这些 profiles 运行在 canonical-event/service-opportunity 时间域。ACLK、READY/VALID 与 payload-hold 由
observation/driver adapter 投影。AXI read/write 当前使用 `raw-ID-serialized` policy；多 ingress exclusive read
需要 source-qualified identity 或 ID-remap profile。Serial bridge 的 width、shape 与 attribute 准入条件见
[`bridges/README.md`](bridges/README.md)。

## 状态 owner

| 事实 | owner |
|---|---|
| 单 port codec、phase、AW/W assembly 与 optional fields | attachment |
| protocol-neutral address route、queue、arbiter cursor 与 completion owner | core backend |
| AXI RID/BID destination lock、downstream owner FIFO 与 channel lifecycle | AXI protocol-bound backend |
| stepped output FIFO、prepared offer 与接纳状态 | stepped-emission backend |
| immutable profile、route 和 capability 选择 | recipe 输入与 compiled plan |
| module 名称、ports、bindings 和 backend 引用 | constructed `VirtualDut` |
| interface legality 与 ordering verdict | 各连接的 `InterfaceSession` monitor |

该归属让 backend 执行账本与协议 monitor 账本分别服务 execution 和 verdict，并通过 canonical events 对接。

## System construction 交接

`SystemProtocolBuilder.construct_address_router()` 将 `AddressRouterContract` 交给注入的 AMBA factory。Recipe 使用
`contract.routes` 构造 fabric，backend 随后投影实际 ingress、egress 和 route 配置；builder 在注册前核对投影
与合同，并在 elaboration 中闭合每个 route window 到直接相邻 egress endpoint 的唯一 address claim。

System construction 持有 module identity、`InterfaceConnection`、全局 address claim 和 router contract；
VirtualDut backend 持有 queue、grant、owner 及 AXI read/write ledger。Crossbar 通过显式 fabric VirtualDut
进入 topology，runtime 执行 resolution 后固定的连接与 backend 行为。

逐项覆盖、容量边界和后续 profile 统一见
[`implementation-status.md`](../../../../docs/architecture/implementation-status.md)。系统地址构造的设计理由见
[`address-fabric.md`](../../../../docs/architecture/address-fabric.md)，SystemProtocol 入口见
[`system/README.md`](../../../system/README.md)。
