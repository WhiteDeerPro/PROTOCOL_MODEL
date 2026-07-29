# Contracts

## 定位

`contracts` 声明需要在系统作用域闭合的 authority、边界事实和验证性质。当前公共实现覆盖 address vertical
slice；后续合同沿 capability、identity、clock/reset、security、coherence membership 和 system property
等真实场景扩展。

## 输入

address contract 接收：

- 接收端口及其本地 `AddressWindow`；
- routing `VirtualDut` 的 ingress/egress port 集合；
- 显式 `AddressRoute` 表及地址转换；
- topology 中的稳定 `VirtualDutPortRef`。

## 输出与状态归属

| 对象 | 持有的事实 |
|---|---|
| `AddressWindow` | 半开地址区间 `[base, base + size)` |
| `AddressClaim` | receiver boundary 对本地窗口的接收声明 |
| `AddressRouterContract` | 一个 routing VirtualDut 的端口集合与 route authority |
| `AddressMapContract` | receiver claims 与 router contracts 的系统级聚合 |

`AddressMapContract` 是当前地址事实的系统权威。生成式 router backend 从同一合同建立本地配置；外部或
opaque router 以合同作为 boundary assumption。backend 继续持有 FIFO、仲裁、lease、owner table 等局部
执行状态。

## 公共入口

```python
from protocol_model.system.contracts import (
    AddressClaim,
    AddressMapContract,
    AddressRouterContract,
    AddressWindow,
)
```

这些名称也由 `protocol_model.system` 根 facade 重导出。实现位于
[`address.py`](address.py)。

## 相邻链接

- [SystemProtocol 源码导航](../README.md)
- [Topology](../topology/README.md)
- [Construction](../construction/README.md)
- [Resolution](../resolution/README.md)
- [SystemProtocol 组网架构](../../../docs/architecture/network-construction.md)
