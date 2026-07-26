# Concrete protocol families

这个目录收纳具体通信标准和项目协议族。它们位于构造依赖图的叶端，不是比 `interface`、`virtual_dut`
或 `system` 更高的一层。

一个协议族只创建真实场景需要的切面：

```text
protocol family
├── interface contract       一个完整逻辑接口内可判定的语言与 lifecycle
├── representation          可选的 message / packet / flit forms 与 codec
├── transport               可选的 hop、credit、activation 与传输资源
├── observation             pin/frame 到 typed fact 的协议专用 lowering
└── system refinements      多 participant 的 identity、route、coherence、progress
```

AXI、AHB 和 APB 目前主要使用 interface、observation 与 integration；不必为它们制造空的 packet/flit
层。CHI 明确定义 Protocol、Network 和 Link 分工，因此会横跨多个切面。通用设施分别留在
`protocol_model.semantics`、`interface`、`observation`、`virtual_dut`、`integrations` 和 `system`，
并且不反向依赖本目录。

目录名表达源码所有权，不代替规范术语。规范中的 TileLink link、CHI Link layer、PCIe link 等原词应在
对应协议族中保留。
