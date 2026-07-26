# Protocol-bound translations

本目录保存必须理解具体协议字段含义、但可以表示为 typed `TranslationStage` 或 plan fragment 的可复用转换。
执行引擎、容量 lease、parent/child correlation 与通用 address/burst stages 仍位于
`protocol_model.virtual_dut.translation`；这里不复制它们的运行状态。

当前 `amba/address_attributes.py` 把 AXI/AHB/APB 的 protection 表示解码成协议中立 `AccessProtection`，并按
目标协议重新编码。single-access 与 burst bridge recipe 使用同一组 stages，因此它们不再藏在任一成品 recipe
文件中。

源码边界为：

- 可以依赖具体 `protocols` 与协议中立 `virtual_dut.translation`；
- 不导入 execution backend 或最终 recipe；
- stage 声明 lower/lift、semantic effect 与拒绝条件，但不拥有跨事务 mutable state；
- 若转换需要 FIFO、child owner 或 completion lifecycle，由通用 translation executor 或 protocol-bound backend
  拥有相应状态。
