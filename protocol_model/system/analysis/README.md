# Analysis

## 定位

`analysis` 只读消费 system 声明、resolved plan、trace 或资源快照，派生跨连接的结构与行为证据。分析结果
服务诊断、验证报告和 boundary refinement。

## 输入

可分析输入包括：

- canonical topology 与 resolved address/transport plan；
- `SystemTrace` 及因果关系；
- runtime 提供的 blocked reason、held lease、未完成 obligation 和资源占用快照。

wait-for/deadlock 分析以后三类 runtime 投影为前置事实。

## 输出与状态归属

预期产物包括 address reachability、wait-for graph、deadlock/livelock witness、coverage 和 boundary
refinement 证据。analysis 读取执行快照并返回派生值；session state 与 DUT backend state 保持各自的运行
ownership。

## 公共入口

本包当前为职责入口，`__all__` 为空。公共分析对象将在对应 runtime 投影和 system property 形成时加入；
实现范围以[实现状态](../../../docs/architecture/implementation-status.md)和
[Roadmap](../../../docs/architecture/technical-route/08-roadmap.md)为准。

## 相邻链接

- [SystemProtocol 源码导航](../README.md)
- [Runtime](../runtime/README.md)
- [Monitors](../monitors/README.md)
- [SystemProtocol 组网架构](../../../docs/architecture/network-construction.md)
