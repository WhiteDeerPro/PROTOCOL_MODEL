# Topology

## 定位

`topology` 保存 `VirtualDut`、端口、connection 和 system boundary 组成的弱结构图。
`SystemProtocol.connections` 是两类连接共同使用的 canonical 注册表：

- `InterfaceConnection` 把一份完整 `InterfaceProtocol` 的 roles 绑定到 `InterfacePort`；
- `DirectedTransportConnection` 把一个 `TransportPort` transmitter 指向一个 receiver，具体 transport
  family 解释其 profile。

拓扑形状表达“谁连接到谁”。decode、arbitrate、broadcast、route 和 response return 等行为由中央
`VirtualDut` backend 与 system contract 声明。

## 输入

- 具名 `VirtualDut` 及其 `InterfacePort`、`TransportPort`；
- caller 提供的 connection 名称、端口引用、协议或 transport family；
- 需要暴露给外层系统的 boundary 名称和端口引用。

## 输出与状态归属

| 对象 | 持有的事实 |
|---|---|
| `VirtualDutPortRef` | 一个具名 VirtualDut port 的稳定引用 |
| `InterfaceConnection` | 完整逻辑接口的 role→port 绑定与接口参数 |
| `DirectedTransportConnection` | 单向 transmitter→receiver hop、family 和 profile |
| `PortOwnerRef` | elaboration 后 connection 或 boundary 对端口的 typed ownership |

[`elaboration.py`](../elaboration.py) 校验端口存在性、role/protocol、direction/family、唯一 ownership 和连接
完整性。transport resolution 从同一注册表派生只读 hop plan。

## 公共入口

对象可从子包或根 facade 导入：

```python
from protocol_model.system.topology import (
    DirectedTransportConnection,
    InterfaceConnection,
    PortOwnerRef,
    VirtualDutPortRef,
)
```

实现文件：

- [`model.py`](model.py)：`VirtualDutPortRef`、`InterfaceConnection`；
- [`transport.py`](transport.py)：`DirectedTransportConnection`；
- [`ownership.py`](ownership.py)：`PortOwnerKind`、`PortOwnerRef`。

## 相邻链接

- [SystemProtocol 源码导航](../README.md)
- [Construction](../construction/README.md)
- [Contracts](../contracts/README.md)
- [Resolution](../resolution/README.md)
- [SystemProtocol 组网架构](../../../docs/architecture/network-construction.md)
