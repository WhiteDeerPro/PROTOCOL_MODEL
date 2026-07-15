# Protocol Model

## 从总线规则到可解释微系统

**Protocol Model 是一个面向片上通信的组合式语义建模与验证研究原型。** 它尝试让协议规则、场景生成、
运行检查和诊断证据共享同一条构造路径，而不是在 driver、monitor、assertion、reference model 和报告中
分别重写同一份协议知识。

### 它从什么问题出发？

AXI 等片上协议的难点通常不在单个字段，而在跨通道、跨事务和跨模块的关系：一次写请求怎样把 AW、W 和 B
关联起来，两个 ID 的响应怎样交织，一次 burst 经过 bridge 后怎样拆分、排队并折回 completion。传统工程可以
分别解决这些问题，但同一关系容易散落在生成器、检查器和调试脚本中，后续难以确认它们是否仍表达同一语义。

Protocol Model 的核心尝试是从小型、可组合的通信事实逐层构造：

```text
基础事件、关系与资源
        ↓ 组合与细化
LinkProtocol：一条逻辑连接上允许怎样通信
        ↓ 绑定到具名模块端口
VirtualDut：一个虚拟 module 的通信相关行为
        ↓ 连接并加入全局契约
SystemProtocol：多条 link 与多个 module 组成的通信系统
        ↓ 观察、执行与投影
可重放场景、波形、因果关系与诊断报告
```

### 当前已经建立了什么？

当前源码树已经包含组合式语义单元、`AtomicFrame` 观察边界、ready/valid 与 reset 处理，以及 AXI4、
AXI4-Lite、AXI4-Stream、AHB-Lite/AHB5 profile、APB3/APB4/APB5 和 ACE-Lite ordinary-data subset 的
LinkProtocol 实现。AXI4 当前覆盖的非平凡行为包括 burst、narrow/unaligned、read interleave、AW/W/B
correlation、单 link 可判断的 exclusive eligibility 和状态驱动生成。

项目也已经提供具名 `VirtualDut`、typed protocol ports、AMBA attachment、地址空间 endpoint、同步
`SystemProtocol` session，以及 AXI4→APB 等 bridge witness。类型化事务转译内核已经具备 operation
signature、stage contract、plan closure、fan-out lifecycle 和 serial capacity lease；现有 full AXI bridge
仍在向这个公共内核迁移。

这些是**当前实现范围内的工程证据**，并不等同于完整 AXI compliance、任意 RTL 验证或形式化证明。

### 对外展示怎样兼顾广度和理解？

技术预览按两个阶段组织；第一阶段已有公开运行证据，第二阶段已有受限 bridge witness，但展示入口仍在规划：

1. **统一 AXI4 介绍集（CURRENT）**：24 个可执行场景按 lifecycle、geometry、ordering/interleave、
   observation/reset、exclusive/profile 五个主题排列。每案都有目标、判定、模型波形、因果图和机器结果；其中
   4-beat narrow/unaligned INCR write 与只改变首拍 `WLAST` 的预期违规增加逐步精讲。二者仍属于同一集合。
2. **AXI4→APB 微系统（PROPOSED presentation）**：计划把当前受限 witness 整理为 requester、bridge 和
   memory/regbank endpoint 通过两条 link 连接的故事，展示 burst split、AW/W join、completion fold、
   route miss 与串行容量。

统一导航先回答“有哪些行为”，再允许从任意场景进入证据，其中两个重点场景回答“怎样读懂它”；bridge 随后
检验方法能否清楚解释跨 link 行为。场景数量用于展示行为广度，不代替 requirement catalog。Crossbar、
raw RTL/VCD adapter 和 wait-for/deadlock 分析属于后续阶段，不作为第一版演示的前提。

### 为什么值得共同验证？

项目提出了三个可检验的问题，而不是预先宣布结论：

- 一份组合式协议构造能否同时服务 generator、monitor 和 evidence，减少知识重复？
- typed operation 与 translation stage 能否让 bridge 复用从“协议对代码”转向“codec + semantic stage”？
- LinkProtocol、VirtualDut、SystemProtocol 的作用域划分能否让单 link 规则和网络级责任更容易审计？

回答这些问题需要协议工程师、验证工程师、RTL 集成者和可视化贡献者共同提供反例、需求校正和真实案例。
项目当前定位是 **technical preview in preparation, with an executable first slice**：欢迎从统一导航扫读
24 个场景，再选择任意单案检查波形与因果图，或沿两个重点场景深入阅读，然后参与 requirement 校正、bridge
展示与外部 DUT 接入。

进一步阅读：[架构地图](../../docs/architecture/technical-route/README.md) ·
[当前实现边界](../../docs/architecture/migration-status.md) ·
[演示编排策略](../strategy/demo-program.md) ·
[统一 AXI4 示例](../generated/axi4/README.zh-CN.md) ·
[宣称与证据](../strategy/claims-and-evidence.md)
