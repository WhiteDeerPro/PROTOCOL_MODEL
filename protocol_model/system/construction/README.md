# Construction

## 定位

`construction` 把 module、connection、boundary 和 system contract 组装成显式 `SystemProtocol` 声明。
便捷构造在 elaboration/runtime 之前完成 lowering，生成的 `VirtualDut` 与 connection 随最终 topology
一起保存。

## 输入

`SystemProtocolBuilder` 接收：

- 已构造的 `VirtualDut`；
- `InterfaceConnection` 或 `DirectedTransportConnection`；
- system boundary 与补充 `SemanticFragment`；
- `AddressClaim`、`AddressRouterContract`；
- 生成式 address router 使用的 `AddressRouterFactory`。

`connect()` 绑定完整逻辑接口，`connect_transport()` 声明单向 hop，`expose()` 声明外层 boundary。

## 输出与状态归属

`build()` 返回包含 canonical topology、boundary、semantics 和 address map 的 `SystemProtocol`。

`construct_address_router(contract, factory)` 将同一份 `AddressRouterContract` 交给 factory，并在注册前核对
返回 `VirtualDut` 的端口与 `AddressRouterBoundaryProjection`。factory 保存协议族配置和局部构造选择；
合同保存系统 address authority；router backend 保存 FIFO、仲裁和 owner 等运行状态。

`add_dut()` 与 `add_address_router()` 组合用于外部或 opaque router，并将合同记录为显式 boundary
assumption。

## 公共入口

```python
from protocol_model.system.construction import (
    AddressRouterFactory,
    SystemProtocolBuilder,
)
```

两个名称也由 `protocol_model.system` 根 facade 重导出。实现位于
[`builder.py`](builder.py)。

## 相邻链接

- [SystemProtocol 源码导航](../README.md)
- [Topology](../topology/README.md)
- [Contracts](../contracts/README.md)
- [Resolution](../resolution/README.md)
- [SystemProtocol 组网架构](../../../docs/architecture/network-construction.md)
