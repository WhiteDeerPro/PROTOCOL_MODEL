# AMBA-bound bridge recipes

## 定位与公共入口

`build_amba_serial_bridge_vdut()` 构造普通的双端口 `VirtualDut`，可直接作为 `SystemProtocol` topology node。
入口接收 module 名称、ingress/egress `InterfaceProtocol`、`AddressRoute`，以及 port 名称、容量、byte order 和
capability 等 policy。

| factory | 选择或固定的 profile |
|---|---|
| `build_amba_serial_bridge_vdut()` | 根据 ingress operation shape 选择 single-access 或 full-AXI burst |
| `build_amba_serial_address_bridge_vdut()` | AXI4-Lite、AHB、APB single-access ingress |
| `build_amba_serial_burst_bridge_vdut()` | full AXI4 burst ingress |
| `build_axi4_lite_to_apb_bridge_vdut()` | AXI4-Lite→APB convenience preset |
| `build_axi4_to_ahb_lite_bridge_vdut()` | AXI4→AHB-Lite convenience preset |
| `build_axi4_to_apb_bridge_vdut()` | AXI4→APB convenience preset |

协议绑定由 ports 上的 `InterfaceProtocol` 表达；共享的 route、typed stages、serial executor、capacity 与
completion fold 支持按参数组合协议对。

## 构造 profiles

- AXI4-Lite、AHB 和 APB 将一次 ingress transaction 解码为一个 `AddressAccess`，使用 single-access profile。
- full AXI4 先把 AW/W 或 AR 组装为 parent burst，再展开为有序 `AddressAccess` children。
- 两种 profile 共用 AMBA requester factory 处理 egress；AXI4、AXI4-Lite、AHB 和 APB 可按支持范围用于目标端。

## 产出与状态 owner

| 事实 | owner |
|---|---|
| 单端口 codec、AW/W 或 phase context | ingress/egress attachment |
| route、shape 与 protection effect | 编译后的 immutable translation plan |
| parent/child owner、completion fold 与 capacity lease | strict-serial executor |
| ports、bindings、backend 和 module 边界 | 返回的 constructed `VirtualDut` |

Strict-serial executor 持有 parent 和一个 child owner，直到 downstream completion 返回。`parent_capacity`
限制已准入的完整 operations，默认值为 8。Full AXI4 assembly 另行限制 pending AW descriptors、pre-AW W bursts
和 buffered W beats。容量耗尽当前投影为 VirtualDut fault；pin/cycle READY backpressure 属于后续 observation
projection。

## Translation boundary

single-access profile 和当前已审计的 pair-named presets 要求 ingress/egress data width 相等。通用 full-AXI
burst profile 可构造异宽总线组合；每个 beat 必须能由 target shape 直接表示，否则 executor 在首个 child issue
前拒绝整个 parent。Beat split/merge 需要显式 width-translation stage。

Protection attributes 先解码为共同 `AccessProtection`，再按目标协议编码。目标 response vocabulary 较小时，
返回路径按目标可表达范围映射 error provenance：例如 APB decode error 经 bridge 返回 AXI 时成为 `SLVERR`，
因为 APB response 无法携带 AXI 的 `DECERR`/`SLVERR` 区分。

## Relation to a crossbar

Crossbar 可以复用 bridge path 的 transforms、attachments、route、storage 和 correlation。多个 ingresses 共享
egress 时，fabric backend 或展开后的内部 subsystem 统一持有 admission、arbitration-grant lifetime、response
ownership 和 per-ingress ordering；独立 bridge instances 各自保持一条串行路径。

相邻实现入口：

- [`AMBA attachments`](../../../attachments/amba/README.md)
- [`protocol-bound translations`](../../../translations/README.md)
- [`execution backends`](../../../backends/README.md)
- [`protocol-neutral VirtualDut recipes`](../../../../virtual_dut/recipes/README.md)
- [`address-fabric construction analysis`](../../../../../docs/architecture/address-fabric.md)
