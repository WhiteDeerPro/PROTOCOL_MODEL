# 《从链路到互连：可组合通信协议建模》

这是 Protocol Model 的工程方法论讲义。它面向熟悉数字电路或基本总线握手、希望进一步理解协议建模、
桥接和片上互连的读者。正文从一次信号采样开始，逐步建立接口合同、虚拟模块、事务转译和系统组网的
完整认识。

`docs/architecture/` 保存项目的设计合同和实现状态；本目录围绕教学顺序重新讲述稳定概念。API、当前
profile 和未完成项以[工程文档入口](../docs/README.md)为准，讲义不维护第二份功能矩阵。

## 学习目标

读完并完成伴随练习后，读者应能：

- 从 pin/cycle observation 中辨认协议可见的通信事实；
- 判断一条约束属于 InterfaceProtocol、VirtualDut 还是 SystemProtocol；
- 为具体 module 划分 operation、attachment、backend 和状态所有者；
- 描述 bridge 中 parent/child 事务的拆分、调度、容量和 completion 回收；
- 为微型网络声明 topology，并区分节点状态、链路账本和系统级验证账本；
- 从 trace、因果关系和资源生命周期中形成可复查的验证结论。

## 全书路线

### 第一部分：从采样到通信事实

1. [从一次采样到通信事实](chapters/01-from-sampling-to-event.md)
2. 消息格式、约束与有限 trace
3. resource、obligation 与因果关系

### 第二部分：构造接口协议

4. 从重复行为中提取 Pattern
5. InterfaceProtocol、profile 与 InterfaceSession
6. APB、AHB、AXI 的接口局部案例

### 第三部分：构造具体模块

7. VirtualDut、backend 与状态所有权
8. operation、attachment、binding 与 integration
9. 地址空间与流式操作

### 第四部分：构造 Bridge

10. 两端事务语义如何对齐
11. operation form、TranslationStage 与 TranslationPlan
12. parent/child 生命周期、容量和 completion fold
13. AXI burst 到较窄访问的贯穿案例

### 第五部分：构造互连网络

14. route、owner、仲裁与 crossbar
15. SystemProtocol、elaboration 与递归组合
16. 地址闭合、ordering、coherence 和 wait-for

### 第六部分：运行、证据与实践

17. observation、execution、verdict 与 artifact
18. 综合实验：端点、bridge 与微型网络

## 与工程文档的分工

讲义安排认知顺序和练习；[架构索引](../docs/architecture/README.md)维护概念所有权，
[实现状态](../docs/architecture/implementation-status.md)维护当前能力，[Roadmap](../ROADMAP.md)维护后续方向。
每个章节优先使用一段概念说明、一个可执行 witness、一张聚焦关系的图和少量练习，不复制状态页中的清单。

## 阅读方法

初次阅读可以直接进入第一章。已经熟悉协议验证的读者可以先看第三、第四部分的目录，再结合
[术语卡片](glossary.md)定位本项目中各对象的精确定义。准备贡献正文时，请先阅读
[教材写作约定](WRITING.md)。
