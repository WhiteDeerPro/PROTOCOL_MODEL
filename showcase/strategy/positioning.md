# 对外定位与宣称边界

## 项目试图解决的问题

协议验证工作经常散落在几种彼此难以对照的表达里：规范文字说明“应该怎样”，driver 说明“怎样发”，
monitor 或 assertion 说明“怎样判错”，reference model 说明“数据应变成什么”，测试则用局部脚本把这些内容
临时连起来。维护成本往往不只来自协议复杂，也来自同一条通信语义被重复表达后逐渐分叉。

Protocol Model 的核心尝试是把这些内容放回一条可追踪的构造路径：

```text
基础 event / relation / resource
            ↓ compose and refine
局部通信 pattern
            ↓ protocol-specific construction
LinkProtocol
            ↓ attach to concrete virtual modules
VirtualDut
            ↓ connect and add global contracts
SystemProtocol
            ↓ observe / generate / check / explain
可重放场景与证据
```

这里的特色不只是对象名称，而是希望同一份构造结果能同时支撑：合法输入生成、非法行为定位、资源生命周期
解释、协议变体派生，以及从单 link 进入微小系统。项目价值是否成立，应由这些路径的可执行证据来判断，
不能只由架构图或代码量判断。

## 初始受众

首轮技术预览优先面向三类人：

1. 正在调试 AXI/AHB/APB bridge、ordering、outstanding 或 narrow corner case 的验证工程师；
2. 正在维护协议 VIP、reference model、形式化 property 或开源 SoC 互连的人；
3. 需要解释“协议约束怎样从小关系组成系统行为”的研究者和教学者。

不建议第一轮把项目包装成通用硬件入门工具。新用户仍需要理解 ready/valid、burst、ID 等基础概念；先服务
有真实协议问题的人，更容易得到能够改进模型的反馈。

## 与相邻生态的关系

| 相邻方向 | 主要强项 | Protocol Model 当前切入点 | 更可能的关系（拟议） |
|---|---|---|---|
| UVM/VIP、cocotb | 驱动和观察真实 RTL，接入现有仿真流程 | 构造通信语义、场景和可解释诊断 | 为 driver/monitor/property 提供更统一的语义来源 |
| SVA、形式化验证 | 对明确 property 做穷举或证明并产生反例 | 组织 property 之前的协议模型、场景族和因果说明 | 输出候选 property/assumption，消费形式化反例 |
| Chisel/Diplomacy、SpinalHDL | 参数化硬件构造、协商和互连生成 | 验证构造结果的 link/system 通信契约 | 从硬件生成配置派生模型或做边界校验 |
| CIRCT/Handshake/ESI | 硬件 IR、typed channel 和 lowering | 更靠近协议要求、运行约束与证据 | 未来交换 typed interface/transaction 描述 |
| SystemC TLM、gem5 | 系统级功能和性能模拟 | 强调具体 link 行为、资源生命周期和违规定位 | 在事务级和 pin observation 之间提供协议语义层 |
| 手写 Python 脚本 | 上手快、为单点问题高度定制 | 把反复出现的关系提炼为可组合、可审计构造 | 吸收稳定语义，保留脚本作为场景外壳 |

这张表描述的是作用域差异和可能的未来连接，不是已经完成的集成，也不是优劣排序。CIRCT 的 ESI 也采用
typed channels 来降低互连集成成本，说明 typed communication 并非本项目独有；Protocol Model 需要用
“约束如何派生并生成证据”证明自己的具体价值，而不是声称没有相邻方案。参见
[CIRCT ESI rationale](https://circt.llvm.org/docs/Dialects/ESI/RationaleESI/)。

## 当前可以支撑的宣称

| 宣称 | 当前证据 | 使用时的限定 |
|---|---|---|
| 从基础语义组合 LinkProtocol | semantic fragment、pattern 和 AMBA link builders | 以当前实现的协议行为为范围 |
| AXI4 模型覆盖多种非平凡行为 | burst、narrow/unaligned、read interleave、AW/W/B、link-local exclusive eligibility、observation | requirement catalog 尚未逐条闭合；exclusive 不包含跨 link 冲突失效 |
| VirtualDut 可以装饰具体协议端口 | typed port、binding、AMBA attachment 和 endpoint recipe | external RTL/RPC backend 尚未接入 |
| 可以构造微小协议系统 | SystemProtocol、同步 session、AXI4→APB bridge witness | 异步 emission、复杂 crossbar progress 尚未闭合 |
| 可以生成受管理的 AXI4 展示证据 | 统一的 24 场景介绍集；每案含模型波形、因果图与机器结果，其中两案精讲 | 场景矩阵不是规范覆盖率；仍不是 RTL/VCD，通用 CLI 与 replay 继续收敛 |

## 当前不应使用的宣称

- 不写“已经完整符合 AXI4 官方规范”；应链接 requirement/coverage catalog，并说明当前支持行为。
- 不写“验证任意 RTL DUT”；当前没有 raw RTL pin、VCD、UVM transaction 或 simulator adapter。
- 不写“统一取代 UVM、cocotb 或 formal”；这些工具拥有本项目当前没有的仿真和证明能力。
- 不把模型生成的 virtual-interface waveform 称为 RTL 实测波形。
- 未使用形式化求解时，把错误产物称为“违规 replay trace”或“诊断反例”，不暗示数学证明。
- 在两个独立 bridge 尚未复用同一 translation kernel 前，不把“普适 bridge 自动生成”写成完成能力。

强宣称以后可以升级，但升级条件应是公开证据发生了变化，而不是宣传措辞发生了变化。

## 对外建议用语

当前可用短版：

> Protocol Model 是一个面向片上通信的组合式语义模型与参考实现。它从小型约束和资源关系构造 AXI 等
> LinkProtocol，再把协议附着到 VirtualDut 并连接为 SystemProtocol；当前统一的 24 场景 AXI4 介绍集陈列五类
> 代表性行为，每案都生成波形和因果证据，其中两案进一步解释合法行为与单点违规。统一 CLI、
> replay schema 和 bridge 展示继续收敛。

M2/M3 完成后的技术预览建议用语：

> 这个 technical preview 以 AXI4 为主要样例。单 link 场景集覆盖 burst、ID ordering、read interleave、
> AW/W/B correlation、narrow/unaligned 和 link-local exclusive eligibility；独立的同宽、对齐
> AXI4→APB 示例展示同步微网络。它还不是 RTL simulator 或完整 compliance suite；我们优先邀请社区校正
> requirement、提交真实场景，并验证这种 bottom-up 构造方法是否能减少协议知识在 generator、monitor 和
> 报告之间的重复。

## 名称与发布前检查

“Protocol Model”在协议工程中也是通用术语，PyPI 上还存在名为
[`protocolmodel`](https://pypi.org/project/protocolmodel/) 的其他项目。无需在当前架构工作中立即改名，
但公开发布 Python package 前应完成 GitHub、PyPI、域名和商标检索，选择可区分的 package/CLI 名称。
方法论仍可继续称为 Protocol Model。
