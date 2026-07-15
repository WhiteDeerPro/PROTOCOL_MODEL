# VirtualDut source layout

本目录按职责分层，不按 APB、AXI、Memory、Crossbar 等设备名称建立类型树：

```text
virtual_dut/
├── boundary/       VirtualDut 与 ProtocolPort 的外部 module 边界
├── binding/        port ↔ attachment 的静态绑定与 VirtualDutBuilder
├── backend/        port-facing transition、backend contract 和简单 fixture
├── address/        协议无关 AddressAccess、AddressSpace 与 reference region
├── attachments/    attachment SPI 与协议无关 operation family
├── fabric/         同一 VirtualDut 内的 route、owner 和跨端口 backend
├── translation/    Bridge 的 operation signature、typed stage、plan 与 executor
└── recipes/        选择端口、attachment、backend，装配具体 VirtualDut
```

APB、AHB、AXI 等具体转换不属于本目录的核心类型。单端口实现位于
`protocol_model/integrations/attachments/`，成品构造位于 `protocol_model/integrations/recipes/`；它们
同时依赖 LinkProtocol 定义和这里的 attachment/backend 契约，通用 VirtualDut 层不反向导入协议名单。

## 依赖规则

- 内部文件从叶模块导入，不从 `protocol_model.virtual_dut` 根 facade 反向导入。
- `attachments` 不依赖 `fabric`、`binding` 或 `recipes`；它只定义一个端口的转换契约。
- `binding/port.py` 只组合 `ProtocolPort` 与 `ProtocolAttachment`，不保存运行状态。
- `binding/builder.py` 是本地装配层；最终产生的 `VirtualDut` 仍然不可变。
- `fabric` 可以组合 backend foundation、address operation 和 attachment binding，但不创建
  `VirtualDut`。
- `translation` 只处理已经 decode 的 operation、跨端口转换和资源生命周期，不导入具体 LinkProtocol；
  attachment-aware backend 负责把它的 operation emission 与端口 event 互换。
- `recipes` 是叶子装配层，可以组合上述职责；下层不导入 recipe。
- `integrations/attachments` 实现协议相关的单端口转换；`integrations/recipes` 装配 endpoint、fabric 和
  bridge。AddressAccess 与 StreamTransfer 仍留在协议无关核心。
- `SystemProtocol` 使用 boundary/transition 叶模块，不通过 recipe 或根 facade 建立隐式连接。

常用构造对象仍从 `protocol_model` 或 `protocol_model.virtual_dut` 导入。实现或扩展 attachment/backend
时，从对应子包导入具体接口；运行状态 DTO 不提升为根公共 API。
