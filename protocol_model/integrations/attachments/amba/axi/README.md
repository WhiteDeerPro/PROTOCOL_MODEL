# AXI attachment implementations

## 定位

本目录保存 AXI4、AXI4-Lite 和 AXI4-Stream 单端口的 event↔operation 转换。具体
[`InterfaceProtocol`](../../../../protocols/amba/axi/README.md) 提供 roles、channels 和 event schemas，
attachment 将其接入 VirtualDut operation SPI。

## 公共入口

| leaf package | 主要 attachment | operation 与接口侧状态 |
|---|---|---|
| `axi4/` | `Axi4AddressSpaceAttachment`、`Axi4RequesterAttachment`、`Axi4BurstTranslationAttachment` | burst-aware address operation、serialized request、AW/W assembly 与 reply context |
| `axi4_lite/` | `Axi4LiteCompleterAttachment`、`Axi4LiteRequesterAttachment` | single-access operation 与 requester/completer state |
| `axi4_stream/` | `Axi4StreamReceiverAttachment`、`Axi4StreamTransmitterAttachment` | `StreamTransfer` 与 optional-field mapping |

公共类型从 `protocol_model.integrations.attachments.amba.axi.<variant>` 导入。

## 状态 owner 与相邻交接

每个 attachment 持有一个 port 的 codec 与 interface-local state。跨端口 parent/child 调度、completion fold、
route、FIFO 和 owner table 由 [`bridge/fabric backend`](../../../backends/README.md) 持有；完整 module 由
[`integrations/recipes/amba`](../../../recipes/amba/README.md) 装配。
