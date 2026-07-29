# Protocol-neutral VirtualDut recipes

## 定位

本目录保存协议无关的装配根。每个 recipe 接收已经准备好的 `InterfaceAttachmentBinding`、operation domain
与 backend，并返回一个 constructed `VirtualDut`。AXI、AHB、APB 等具体 `InterfaceProtocol` 由上游
integration recipe 选择并形成 bindings。

## 公共入口

| 源文件 | 公共 factories | 构造出的行为形状 |
|---|---|---|
| `empty.py` | `build_idle_source_vdut()`、`build_blackhole_sink_vdut()` | source/sink fixture |
| `queued_address.py` | `build_queued_address_responder_vdut()` | queued address endpoint |
| `sensor_fifo.py` | `build_sensor_fifo_vdut()` | sensor FIFO endpoint |
| `memory_copy.py` | `build_serialized_memory_copy_vdut()` | 主动 serialized copy engine |
| `interrupt.py` | `build_explicit_eoi_interrupt_target_vdut()`、`build_priority_interrupt_controller_vdut()` | notification/EOI 控制组件 |
| `address_translation.py` | `build_address_translation_vdut()`、`build_address_operation_translation_vdut()` | single/grouped-operation bridge |
| `address_crossbar.py` | `build_scheduled_address_crossbar_vdut()` | 带 queue、arbitration 和 owner return 的 N→M address fabric |

## 产出与状态 owner

| 构件 | 持有的事实 |
|---|---|
| `InterfaceAttachmentBinding` | port、具体接口合同与 interface-local state 的绑定 |
| operation domain | protocol-neutral request/completion form |
| backend | module 局部执行状态、queue、route、owner 或 controller lifecycle |
| recipe | construction-time 参数校验和构件组合 |
| 返回的 `VirtualDut` | 具名 module 边界、ports、bindings 与 backend |

bridge、crossbar、DMA 等名称描述一次装配的行为形状；最终 module 的协议身份来自公开的 `InterfacePort`。

## 相邻交接

常规使用者从 [`protocol_model.integrations.recipes`](../../integrations/recipes/README.md) 选择协议绑定后的成品
recipe。本层直接服务新的 integration、非 AMBA 协议接入和自定义 attachment；公共构造面的发现入口见
[`recipe catalog`](../../integrations/recipes/catalog/README.md)，VirtualDut 的完整职责见
[`virtual_dut/README.md`](../README.md)。
