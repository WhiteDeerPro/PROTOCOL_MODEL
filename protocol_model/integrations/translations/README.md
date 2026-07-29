# Protocol-bound translations

## 定位

本目录保存需要理解具体协议字段、同时可表达为 typed `TranslationStage` 或 plan fragment 的可复用转换。它连接
具体 [`protocols`](../../protocols/README.md) 与协议中立的
[`virtual_dut.translation`](../../virtual_dut/translation/)。

## 输入、产出与状态 owner

| 项目 | 输入 | 产出或 owner |
|---|---|---|
| protocol-bound stage | 具体 `InterfaceProtocol`、typed operation 和协议字段 | lower/lift、`StageContract`、semantic effect 与拒绝条件 |
| translation executor | 编译后的 plan、容量 profile 和 child completion | capacity lease、parent/child correlation 与 completion lifecycle |
| protocol-bound backend | 需要跨端口协调的转换结果 | FIFO、child owner 和其他跨事务 mutable state |
| recipe | stages、executor/backend 与 attachment bindings | 最终 translation plan 和 constructed `VirtualDut` |

Stage 持有不可变声明，并根据本次输入与 lift context 完成转换。跨事务运行状态由通用 translation executor 或
[`protocol-bound backend`](../backends/README.md) 持有；最终装配由
[`recipes`](../recipes/README.md) 完成。

## 公共入口

[`amba/address_attributes.py`](amba/address_attributes.py) 提供：

- `DecodeAmbaProtectionStage`：将 AXI/AHB/APB protection 表示解码为协议中立 `AccessProtection`；
- `EncodeAmbaProtectionStage`：按目标协议重新编码共同 protection intent；
- `amba_raw_address_signature()`：声明 family-specific `AddressAccess.attributes` 语义。

single-access 与 burst bridge recipe 复用同一组 stages。超出共同属性 profile 的输入产生带 policy key 的
`Rejected` 结果，调用方据此选择扩展 policy 或专用转换。
