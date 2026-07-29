# VirtualDut construction catalog

这里是公共 `VirtualDut` recipe 的统一入口。每个 recipe 接收协议、端口名、地址空间、route、容量等参数，
并返回一个具名 `VirtualDut`。机器可读 catalog 定义当前公共构造面。

完整的机器可读清单位于 [`catalog/`](catalog/README.md)，也可以直接查看：

```bash
python -m protocol_model.integrations.recipes.catalog
```

或在 Python 中按角色查找：

```python
from protocol_model.integrations.recipes import list_virtual_dut_recipes

for recipe in list_virtual_dut_recipes(kind="bridge", tier="primary"):
    print(recipe.id, recipe.factory_name, recipe.protocol_scope)
```

catalog 显式记录 foundation recipe 与绑定 AMBA/control 协议的成品 recipe。命令行和 Python 查询都读取同一
份 entry 集合，因此清单数量与支持范围以 catalog 输出为准。

## 目录如何划分

```text
integrations/recipes/
├── catalog/                 面向人、脚本和未来 GUI 的构造索引
├── amba/
│   ├── endpoints/           单边界角色：AddressSpace、DMA、Sensor FIFO、stream capture、空 fixture
│   ├── bridges/             两端口 translation、调度、correlation 与 completion return
│   └── fabrics/             1→N decoder/mux 与 N→M crossbar
└── control/                 notification/EOI 等控制链路成品
```

目录按 module 的通信角色划分。`endpoints/` 表示网络边界处的 module，其中既有 passive address/stream
endpoint，也有主动发起访问的 memory-copy engine。

`protocol_model/virtual_dut/recipes/` 是再下一层的协议无关装配根。它接收已经准备好的 attachment binding，
以 operation、binding 和 backend 完成 core 装配。这里的 integration recipe 选择具体 InterfaceProtocol
attachment，再调用对应 core recipe。新 family integration 沿同一路径加入，VirtualDut 核心保持协议中立。

当 AXI ID、channel ordering 等具体规则直接塑造跨端口 controller 时，执行实现位于
[`integrations/backends/`](../backends/README.md)，本目录选择并装配它。endpoint/fabric 可以按行为需要直接
组合协议无关 backend，或选择 protocol-bound backend。

AMBA protection 等已被多个桥计划复用的 typed stage 位于 `integrations/translations/`。Recipe 负责选择这些
stage 并编译 plan，不再把 stage 实现藏在 `bridges/` 产品目录中。

## 产物归属

| 对象 | 归属 | 原因 |
|---|---|---|
| 协议无关、可复用的装配方法 | `virtual_dut/recipes/` | 只组合 operation、binding 与 backend |
| 绑定具体协议的可复用成品方法 | `integrations/recipes/` | 同时理解 InterfaceProtocol 与 VirtualDut |
| 某个网络中的具名 VirtualDut 实例 | System construction、scenario 或调用方 project | 实例的名称、连接、地址 claim 和 policy 属于该网络 |
| 用于讲解的一次实例 | `showcase/demos/` | 展示构造、连接与运行证据 |
| 调用方的定向验证 fixture | 调用方工程 | 验证调用方选择的具体组合 |

项目专用的外部 RTL/RPC module 可由调用方声明为 opaque `VirtualDut`。装配方式在多个场景复用后可提升为
project recipe；具备跨项目价值后再进入公共 catalog。

## bridge 与 crossbar 的动态构造

AMBA bridge 的主入口是 `build_amba_serial_bridge_vdut()`。它根据两个 InterfaceProtocol 的 interface shape
选择已有 single-access 或 burst 路径；三个带固定协议对名称的 builder 是收紧参数的 convenience preset，
它们共享同一组 translation/executor 核心。新增协议组合通过 capability、policy 与 preset 扩展。

crossbar 是另一种参数化 recipe。它可以复用 bridge 使用的 transform、store、correlate 等构造件，但还
拥有多入口仲裁、route、owner-return 和共享容量。GUI 可以把用户操作表现为扩展连接；lowering 产物是一个
明确的 fabric VirtualDut 和一组明确的 InterfaceConnection。

未来 GUI 的稳妥流程是：

```text
选择两个端口
  → 查询 recipe catalog
  → 检查 capability / policy 是否闭合
  → 形成可检查的 construction plan
  → 显式创建 bridge 或 fabric VirtualDut
  → 注册端口和 InterfaceConnection
```

catalog 负责发现 factory。translation capability/policy resolver 负责判断协议对与 policy 是否闭合。任何
自动插桥都在 construction/elaboration 阶段形成显式 module、ports 和 connections，随后交给
SystemProtocol runtime 执行已固定的 topology。
