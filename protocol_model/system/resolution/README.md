# Resolution

## 定位

`resolution` 读取已经构造的 topology 与 system contract，执行 structure、address、transport 以及后续
capability、identity、domain closure，并产生不可变 resolved plan。既有 `VirtualDut` 在这一阶段保持原样。

## 输入

当前 passes 接收：

- frozen `SystemProtocol` 与 elaboration 产生的 `owner_by_port`；
- canonical `InterfaceConnection`、`DirectedTransportConnection`；
- 显式 `AddressMapContract` 及 router/receiver 声明。

## 输出与状态归属

| pass | 当前闭合范围 | 输出 |
|---|---|---|
| `resolve_address_map()` | router ingress×route、egress connection、唯一 direct-neighbor claim | `ResolvedAddressPlan`、`ResolvedAddressPath` |
| `resolve_transport_connections()` | canonical directed connection 到具名 hop 及端口查询 | `ResolvedTransportPlan`、`ResolvedTransportHop` |

address V1 以 direct-neighbor closure 为解析范围；bridge-chain 选择属于后续 construction/resolution
能力。transport family session 读取 hop 的 family/profile 并负责具体运输执行。

结果由 `ElaboratedSystemProtocol.address_plan` 和 `transport_plan` 持有。plan 中的 route、connection、
claim 和 hop identity 提供从结果回到输入声明的来源信息。

## 公共入口

```python
from protocol_model.system.resolution import (
    ResolvedAddressPlan,
    ResolvedTransportPlan,
    resolve_address_map,
    resolve_transport_connections,
)
```

resolved value 类型也由 `protocol_model.system` 根 facade 重导出；resolver 函数从本子包导入。
实现位于 [`address.py`](address.py) 和 [`transport.py`](transport.py)。

## 相邻链接

- [SystemProtocol 源码导航](../README.md)
- [Topology](../topology/README.md)
- [Contracts](../contracts/README.md)
- [Runtime](../runtime/README.md)
- [SystemProtocol 组网架构](../../../docs/architecture/network-construction.md)
