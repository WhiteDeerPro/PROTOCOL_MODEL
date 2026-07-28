# AXI protocol-family assets

本目录按接口语义而不是 Python 继承关系保存三个 AXI variant：

```text
axi/
├── axi4/          memory-mapped burst、ID、ordering、exclusive 与 observation/generation
├── axi4_lite/     原生 single-beat interface，以及到 AXI4 的显式 embedding
└── axi4_stream/   stream packet、byte qualifier、interleave 与 continuous-packet profile
```

AXI4-Lite 和 AXI4-Stream 都有自己的 `InterfaceProtocol`。它们可以复用 AXI4 或公共 pattern，但不需要伪装成
“AXI4 减字段”的运行时对象。跨 variant 的转换应使用显式 embedding 或 bridge/stream adapter，并说明被保留、
默认、拆分或拒绝的语义。

本目录只定义接口合同及协议专用 observation/generation。把 AXI event 转成 VirtualDut operation 的代码位于
[`integrations/attachments/amba/axi`](../../../integrations/attachments/amba/axi/)，完整 endpoint、bridge 和
fabric 构造位于 [`integrations/recipes/amba`](../../../integrations/recipes/amba/README.md)。

当前覆盖与缺口统一见[实现状态](../../../../docs/architecture/implementation-status.md)。
