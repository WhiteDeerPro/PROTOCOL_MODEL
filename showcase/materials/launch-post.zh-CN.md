# Protocol Model：从总线规则到可解释微系统

我们发布 Protocol Model 的首轮 technical preview，并提供第一个可执行切片。它是一个面向片上通信
的组合式语义建模与验证研究原型，尝试让协议规则、场景生成、检查与诊断共享一条构造路径。

**CURRENT｜当前已有：** 项目从 typed event、relation 和 resource 构造 AXI4 等 LinkProtocol，再通过具名
VirtualDut 与 typed port 组成同步微系统。当前 AXI4 范围包括 burst、narrow/unaligned、read interleave 与
AW/W/B correlation；也已有 AXI4→APB bridge witness、因果图和产物管理。这不代表完整 compliance、任意 RTL
验证或形式化证明。

**CURRENT｜统一介绍集：** 24 个具名场景分布在 lifecycle、geometry、
ordering/interleave、observation/reset 和 exclusive/profile 五个主题；10 个合法输入与 14 个预期违规均满足
声明期望。每案都有目标、判定、模型波形、因果图和 result JSON，场景数量不冒充规范覆盖率。

**CURRENT｜同集精讲：** 4-beat narrow/unaligned INCR write 与只把首拍 `WLAST` 改为 1 的预期违规在这
24 个场景中增加逐步说明。6 个 frame 输入场景的 `AtomicFrame` 波形使用 `ARESETn` 展示，18 个 event
输入场景使用明确标注的 `CanonicalEvent` 顺序图；两个精讲属于前一类。两种图都来自模型，不是 RTL/VCD。

**PROPOSED｜下一段：** 以 AXI4→APB 微系统解释拆分、completion 折返和串行容量。

欢迎从校正一条 requirement、贡献一个场景或改进一张图开始，共同检验这套方法能否减少语义重复。

进一步阅读：[统一 AXI4 示例](../generated/axi4/README.zh-CN.md) · [项目介绍](one-pager.zh-CN.md) ·
[当前实现边界](../../docs/architecture/implementation-status.md)
