# VirtualDut construction catalog

这里是当前工程中“可以构造哪些 VirtualDut”的统一入口。源码并不保存一排预先创建好的设备对象；它保存
参数化 recipe，调用者为 recipe 提供协议、端口名、地址空间、route 或容量后，得到一个具名
`VirtualDut`。

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

当前目录记录 39 个构造入口：10 个协议无关 foundation recipe，以及 29 个已经绑定 AMBA 或 control
协议的成品 recipe。清单是显式维护的支持面，不通过扫描文件或 import 副作用猜测哪些 helper 可以调用。

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

这个划分依据 module 的通信角色，而不是设备名称或协议继承关系。`endpoints/` 中也可能有主动发起访问的
memory-copy engine；endpoint 在这里表示网络边界处的 module，不等于“被动外设”。

`protocol_model/virtual_dut/recipes/` 是再下一层的协议无关装配根。它接收已经准备好的 attachment binding，
不知道 AXI、AHB 或 APB。这里的 integration recipe 选择具体 InterfaceProtocol attachment，再调用那些 core
recipe。保持这条依赖方向后，增加 TileLink integration 不需要让 VirtualDut 核心认识一份新的协议名单。

当 AXI ID、channel ordering 等具体规则直接塑造跨端口 controller 时，执行实现位于
[`integrations/backends/`](../backends/README.md)，本目录仍只选择并装配它。Protocol-bound backend 并非每个
recipe 的必经层；能用协议无关 backend 表达的 endpoint/fabric 继续直接组合 core recipe。

AMBA protection 等已被多个桥计划复用的 typed stage 位于 `integrations/translations/`。Recipe 负责选择这些
stage 并编译 plan，不再把 stage 实现藏在 `bridges/` 产品目录中。

## recipe、实例和测试分别放在哪里

| 对象 | 归属 | 原因 |
|---|---|---|
| 协议无关、可复用的装配方法 | `virtual_dut/recipes/` | 只组合 operation、binding 与 backend |
| 绑定具体协议的可复用成品方法 | `integrations/recipes/` | 同时理解 InterfaceProtocol 与 VirtualDut |
| 某个网络中的具名 VirtualDut 实例 | System construction、scenario 或调用方 project | 实例的名称、连接、地址 claim 和 policy 属于该网络 |
| 用于讲解的一次实例 | `showcase/demos/` | 展示如何构造和连接，不定义公共产品面 |
| 调用方的定向验证 fixture | 调用方工程 | 只证明具体组合，不充当本项目的公共产品目录 |

一个只在某个项目中使用的外部 RTL/RPC module 可以由调用方直接声明 opaque `VirtualDut`。当它的装配方式
在多个场景复用时，再提升为 project recipe；只有具备跨项目价值时才进入本目录的公共 catalog。

## bridge 与 crossbar 的动态构造

AMBA bridge 的主入口是 `build_amba_serial_bridge_vdut()`。它根据两个 InterfaceProtocol 的 interface shape
选择已有 single-access 或 burst 路径；三个带固定协议对名称的 builder 是收紧参数的 convenience preset，
并非三套不同的桥核心。这样协议种类增加时不必静态扩张成 N² 个类。

crossbar 是另一种参数化 recipe。它可以复用 bridge 使用的 transform、store、correlate 等构造件，但还
拥有多入口仲裁、route、owner-return 和共享容量，因此不是“在原 bridge 对象上添加几个通道”。GUI 可以把
用户操作表现为扩展连接，lowering 后仍应产生一个明确的新 fabric VirtualDut 和一组明确的 InterfaceConnection。

未来 GUI 的稳妥流程是：

```text
选择两个端口
  → 查询 recipe catalog
  → 检查 capability / policy 是否闭合
  → 形成可检查的 construction plan
  → 显式创建 bridge 或 fabric VirtualDut
  → 注册端口和 InterfaceConnection
```

当前 catalog 负责发现 factory，不负责证明任意协议对都可转译，也不会在 SystemProtocol 运行时隐式插桥。
自动插桥需要单独的 translation capability/policy resolver，构造结果仍应在 elaboration 前对用户可见。
