# 演示编排策略

本页决定示例怎样被看见和讲解，不承担逐场景导航。当前可运行集合、每个场景的波形、因果图和机器结果以
[`showcase/demos/axi4`](../demos/axi4/README.md) 为 canonical 入口；本页不复制 case 清单，以免实现与宣传计划分别
维护两套事实。

## 核心决策：一套 AXI4 介绍集，多种阅读深度

首轮 AXI4 内容应呈现为一个统一的介绍例，而不是“Gallery”和“Quick Start”两个产品：

```text
统一导航
├── 快速扫读：按主题浏览全部场景及 verdict
├── 单案检查：每案都可打开波形、因果图和机器结果
└── 重点讲解：同一集合中的少数场景附加逐步说明
```

当前编排以 24 个场景为基线，其中 2 个在同一导航中标记为重点讲解。重点场景使用更多文字，不因此成为
另一套场景体系或独立宣传入口。数量只描述发布样本，不代表 AXI4 规范条款覆盖率。

## 为什么先给广度

验证工程师第一次评估工具时，通常先问它能否覆盖自己遇到的行为类型，而不是先阅读一个案例的全部实现。
因此统一首页应先展示主题、场景名、合法或预期违规、实际判定和命中规则，使读者在数十秒内建立范围认识。

广度之后仍需要深入入口。模型的差异不只在于给出 PASS/FAIL，还在于把 transfer、事务生命周期、资源状态和
违规原因连接起来。重点场景负责解释这条路径，但不应遮蔽其余场景也具有可检查证据。

## 所有场景的共同证据

每个公开场景都应由同一具名发布流程生成至少以下内容：

- 一段简短目标，以及 expected/observed verdict；
- 模型波形，明确标注它来自 `AtomicFrame` 还是 `CanonicalEvent`；有 reset observation 时同时说明 reset 语义；
- 因果图，展示本案实际接受的事件及关键关系；
- 机器可读结果，保留输入、fault、资源峰值和 provenance；
- 一个稳定的导航锚点，使帖子、deck 和 issue 可以直接链接到该案。

不要求每个场景再生成一篇长报告。统一导航可以提供一次集合级说明和统计，普通场景依靠短摘要、图和 JSON
完成自证；只有首次引入新的观察边界、资源关系或组合语义时，才增加解释段落。

## 重点场景怎样选择

重点讲解控制在 2–3 个，并满足不同的学习任务：

1. 至少一个合法轨迹，能展示 AXI 特有而非普通 request/response 的行为；
2. 至少一个只改变单一因素的预期违规，便于读者把输入变化、规则和因果窗口对应起来；
3. 若增加第三个，应说明新的 observation 或资源边界，而不是重复已有结论。

重点页可以逐步解释源码、字段展开、波形和因果关系。普通场景不复制这些固定教学段落，但仍生成同类图像，
因此读者可从矩阵平滑地进入任意一案，而不是被迫只看维护者挑选的两个例子。

## 一套导航的三个层次

| 层次 | 读者问题 | 页面内容 | 目标时间 |
|---|---|---|---:|
| 概览 | “有哪些行为？” | 主题矩阵、verdict、规则与状态说明 | 30–60 秒 |
| 单案 | “这个判断从哪里来？” | 输入摘要、波形、因果图、result/provenance 链接 | 2–5 分钟 |
| 重点讲解 | “我怎样读懂并修改它？” | 逐步代码、字段变化、资源/constraint 解释 | 约 10 分钟 |

这一结构既服务“先看广度”的用户，也避免为全部场景编写重复长文。公开视频可以先扫过矩阵，再进入一个合法
场景和一个预期违规；one-pager 与 launch post 指向同一个导航页。

## 第二故事：bridge 微网络

AXI4→APB bridge 适合作为统一 AXI4 介绍之后的第二故事，用来展示两种 LinkProtocol、bridge VirtualDut 和
SystemProtocol 的协作：

```text
requester VirtualDut
        │ AXI4
        ▼
AXI4→APB Bridge VirtualDut
        │ APB4
        ▼
memory/regbank VirtualDut
```

它应解释 burst 拆分、AW/W join、串行 child transfer、response fold 和 route miss，但不进入首个导航页来
稀释 AXI4 单 link 的学习路径。公共 translation executor 稳定后，再把 typed operation/stage 作为主要叙事；
在此之前只描述当前 witness 实际证明的边界。

多入口 crossbar 继续作为后续研究故事。它会同时引入仲裁、return ownership、fairness 和系统地址归属，适合
在系统级观察能力更成熟后单独组织。

## 图像与文字规则

- `AtomicFrame` 投影写作 **Model-generated virtual-interface waveform**；`CanonicalEvent` 投影写作
  **Model-generated link-event sequence**，两者都不称 RTL/VCD 实测；
- `AtomicFrame` 中存在 AXI reset observation 时，线路图使用协议名称 `ARESETn`，并说明它由内部规范化
  active-high `reset` 取反而来；事件顺序图不虚构没有被观察的 reset 或 pin/cycle；
- pin/cycle transfer 相关字段应足以看清 VALID/READY/FIRE、ID、地址或 beat、响应，不用装饰性空白压缩
  有效信息；
- 因果图只保留本案需要的事件和关系，避免把完整运行时对象图当作教学图；
- `expected_violation` 的运行成功与协议 verdict 分开表达，不用一个含糊的 PASS 覆盖两者；
- 主题颜色、图例和术语在全部场景间保持一致，重点场景只增加注释层，不更换证据格式。

## 发布门槛

统一介绍集公开前至少满足：

- 每个列入导航的场景都能从具名脚本重建波形、因果图和机器结果；
- 聚合页的数量、verdict 和链接来自本次 manifest，而不是手写第二份统计；
- 两个重点场景与普通场景共享执行内核和 artifact schema；
- 非维护者能从统一入口找到一个主题、打开任意单案，并解释一个预期违规；
- claims/evidence 表保留“场景证据不等于规范覆盖率”“模型波形不等于 RTL trace”等限定。

实现细节、运行命令和场景导航属于 [`showcase/demos/axi4`](../demos/axi4/README.md)；发布用文案和录屏脚本属于
[`showcase/materials`](../materials/README.md)。本页只在编排原则或发布门槛变化时更新。
