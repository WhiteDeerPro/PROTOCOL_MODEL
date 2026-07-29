# AXI protocol-family assets

本目录按各自的接口语义保存三个 AXI variant，并通过显式 embedding 或 adapter 表达 variant 间转换：

```text
axi/
├── axi4/          memory-mapped burst、ID、ordering、exclusive 与 observation/generation
├── axi4_lite/     原生 single-beat interface，以及到 AXI4 的显式 embedding
└── axi4_stream/   stream packet、byte qualifier、interleave 与 continuous-packet profile
```

AXI4-Lite 和 AXI4-Stream 各自公开 `InterfaceProtocol`。实现可以复用 AXI4 或公共 pattern，同时保留每个
variant 的原生运行时对象。跨 variant 的 embedding、bridge 或 stream adapter 明确记录语义的保留、默认、
拆分和拒绝。

## 输入、产出与交接

- 通用 event schema、interface/session 和 observation 构件作为输入。
- 本目录拥有 AXI roles、channels、transaction lifecycle、接口合同和协议专用 observation/generation。
- AXI event 到 VirtualDut operation 的转换位于
  [`integrations/attachments/amba/axi`](../../../integrations/attachments/amba/axi/)，完整 endpoint、bridge 和
  fabric 构造位于 [`integrations/recipes/amba`](../../../integrations/recipes/amba/README.md)。

当前覆盖与缺口统一见[实现状态](../../../../docs/architecture/implementation-status.md)。
