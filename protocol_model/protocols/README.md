# Concrete protocol families

这个目录收纳具体通信标准和项目协议族。协议族位于通用设施依赖图的叶端，并按标准需要组合
`interface`、representation、transport、observation、VirtualDut integration 和 system refinement。

## 协议族切面

一个协议族按已支持场景创建以下切面：

```text
protocol family
├── interface contract       一个完整逻辑接口内可判定的语言与 lifecycle
├── representation          可选的 message / packet / flit forms 与 codec
├── transport               可选的 hop、credit、activation 与传输资源
├── observation             pin/frame 到 typed fact 的协议专用 lowering
└── system refinements      多 participant 的 identity、route、coherence、progress
```

AXI、AHB 和 APB 当前交付 interface、observation 与 integration 切面。CHI 按规范中的 Protocol、Network 和
Link 分工交付 interface transaction、network representation、transport 与 system progress 切面。新的切面在
标准合同与真实场景需要时加入。

## 输入与交接

- `protocol_model.semantics`、`interface`、`observation`、`virtual_dut` 和 `system` 提供通用构件；依赖方向从
  本目录中的具体协议指向这些通用包。
- 每个 family 包拥有标准字段、角色、状态机、codec 及协议专用 observation/generation。
- `protocol_model.integrations` 汇合具体协议对象与 VirtualDut SPI，形成 attachment、backend 和 recipe。
- 目录名表达源码所有权；TileLink link、CHI Link layer、PCIe link 等规范术语继续用于对应协议族。
