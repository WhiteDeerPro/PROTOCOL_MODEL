# Monitors

## 定位

`monitors` 消费多个 connection 上的系统事件，维护跨连接 reference ledger，并产生 system-scope verdict。
monitor 对 DUT 执行路径是只读消费者，自身可保存判定所需的在线聚合状态。

## 输入

典型输入包括：

- `SystemEvent`/`SystemTrace`；
- resolved topology、address/home/identity authority；
- transaction correlation、资源占用与 progress observation。

## 输出与状态归属

monitor ledger 保存 request owner、response return、coherence aggregation、ordering 和 progress 等参考状态，
并输出 verdict 或诊断证据。真实 directory、owner table、FIFO 和仲裁状态属于相应 `VirtualDut` backend；
协议事件也由 backend 发出。

## 公共入口

本包当前为职责入口，`__all__` 为空。首个公共 monitor 应随可执行 system vertical slice 一起定义事件输入、
ledger 生命周期和 verdict 类型；实现范围以
[实现状态](../../../docs/architecture/implementation-status.md)为准。

## 相邻链接

- [SystemProtocol 源码导航](../README.md)
- [Runtime](../runtime/README.md)
- [Analysis](../analysis/README.md)
- [InterfaceProtocol、VirtualDut 与 SystemProtocol](../../../docs/architecture/system-protocol.md)
