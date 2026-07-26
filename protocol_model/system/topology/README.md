# Topology

本包负责 VirtualDut、端口、连接和 system boundary 的弱结构图，以及 ownership/连接查询。
一个 canonical topology 同时可容纳两种边：

- `InterfaceConnection` 将一份完整 `InterfaceProtocol` 的 roles 绑定到 `InterfacePort`；
- `DirectedTransportConnection` 将一个 `TransportPort` transmitter 指向一个 receiver，其 profile 由具体 transport family 解释。

transport resolution 只从这份 topology 派生只读 hop plan，不创建第二份连接权威。

Topology 只回答“谁连接到谁”。它不根据星形、树形或 N×M 外观推断中央 VirtualDut 会执行 decode、
arbitrate、broadcast 或 response return；这些行为来自该 VirtualDut backend，跨节点正确性由 system
contracts 和 monitors 判断。

`VirtualDutPortRef` 和 `InterfaceConnection` 位于 `model.py`，`DirectedTransportConnection` 位于
`transport.py`，typed `PortOwnerRef` 位于 `ownership.py`；`protocol.py` 与 `protocol_model.system`
继续重导出公共名称。端口解析、方向/family 校验、ownership 和连接完整性检查由根
`elaboration.py` 编排。
