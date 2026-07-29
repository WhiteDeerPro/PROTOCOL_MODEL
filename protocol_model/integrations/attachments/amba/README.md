# AMBA attachment implementations

## 定位

每个 leaf package 将一种 AMBA interface family 的 events 转换为小型 VirtualDut operation contract，并把
operation completion 编码回接口 events。一个 attachment 绑定一个 port。

## 输入、产出与状态 owner

| leaf package | 主要输入与产出 | attachment 持有的接口侧状态 |
|---|---|---|
| `ahb/` | AHB transfer events ↔ address operations | address/data phase context |
| `apb/` | APB transfer events ↔ address operations | SETUP/ACCESS 与 pending completion |
| `axi/` | AXI variant events ↔ address/burst/stream operations | AW/W join、request/reply context 与 optional-field mapping |

Attachment 持有单端口 codec 和 interface-local state。跨端口 route、FIFO、owner table 与 completion correlation
由 [`integrations/backends`](../../backends/README.md) 持有；协议中立 operation 和 backend 合同由
[`virtual_dut`](../../../virtual_dut/README.md) 提供。

## 公共入口与相邻交接

公共对象从具体 leaf package 导入，使 import path 同时表达 family 和 variant：

- `protocol_model.integrations.attachments.amba.ahb`
- `protocol_model.integrations.attachments.amba.apb`
- `protocol_model.integrations.attachments.amba.axi.<variant>`

[`protocols/amba`](../../../protocols/amba/README.md) 提供具体接口合同，
[`integrations/recipes`](../../recipes/README.md) 选择 attachment、backend 和 policy，并构造完整 module。
