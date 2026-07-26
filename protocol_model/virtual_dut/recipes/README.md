# Protocol-neutral VirtualDut recipes

本目录保存协议无关的装配根。每个 recipe 将已经准备好的 `InterfaceAttachmentBinding`、operation domain 与
backend 组合成一个 constructed `VirtualDut`。它们不选择 AXI、AHB、APB 等具体 InterfaceProtocol。

当前构造件按作用分为：

- `empty.py`：idle source 与 blackhole sink fixture；
- `queued_address.py`、`sensor_fifo.py`、`memory_copy.py`：地址 endpoint 与主动 copy engine；
- `interrupt.py`：notification/EOI 控制组件；
- `address_translation.py`：single-access 与 grouped-operation bridge；
- `address_crossbar.py`：带队列、仲裁和 owner return 的 N→M address fabric。

通常用户不直接准备 AMBA binding，而是从
[`protocol_model.integrations.recipes`](../../integrations/recipes/README.md) 选择协议绑定后的成品 recipe。
本层主要服务于新的 integration、非 AMBA 协议接入，以及需要自定义 attachment 的项目。

这里的 recipe 是 construction function，不是设备类型树。bridge、crossbar、DMA 等名称说明一次装配出的
行为形状；最终 module 的协议身份来自它公开的 `InterfacePort`。
