# 社区推广与采用计划

## 总体判断

现在适合准备“小范围 technical preview”，还不适合宣传成成熟验证产品。协议语义、VirtualDut、微小
SystemProtocol 和产物基础已经足以讲出完整方法论；统一的 24 场景 AXI4 介绍集已经落地，每案都有波形和
因果证据，其中两案增加详细讲解。项目已经具备 Python package 元数据和本地隔离构建记录，但非维护者从
干净 checkout 完成复现的证据、requirement catalog 和外部 DUT 接入仍然不足。推广的近期目标不是获得尽可能多的关注，而是
取得三类高质量反馈：

- 第一次接触者是否能在没有维护者讲解时跑通并读懂结果；
- 协议工程师是否能指出 requirement、profile 或 corner case 的真实缺口；
- 外部贡献者能否添加一个场景或修正文档，而不先理解整个代码库。

这形成两条需要并行建设的路径：

```text
体验路径：看懂结果 → 一条命令运行 → 制造错误 → 修改参数并重放
信任路径：查看 requirement → 查看派生 witness → 核对支持边界 → 贡献修订
```

只有体验路径，项目容易被理解为漂亮的固定 demo；只有信任路径，项目又会成为难以进入的架构论文。

## 对外建议中的保留与修正

收到的外部建议有几项值得保留：选择 AXI/bridge 作为说明故事、同时展示 topology/trace/wave/因果关系、
把复现性作为发布条件、尝试教学和研究合作、以后与现有 RTL/IR 生态连接。

首轮执行需要做几处修正：

1. 首页先给统一 AXI4 场景矩阵，让验证用户先判断行为覆盖面；每案都能继续查看波形与因果图，其中 2–3 个
   增加详细讲解。AXI4→APB 作为第二阶段故事，避免第一次就同时解释两种协议、转换、queue 和 completion。
2. 一个 4-beat AXI burst 转成 APB 时，可以产生四个 child operations；在当前串行 bridge profile 中，
   同一时刻只有一个 active/pending APB transfer，不能描述成四笔 APB 访问并发执行。公共 translation
   `CapacityLease` 接入后，才使用 lease 术语解释同一事实。
3. 当前能生成 WaveDrom/SVG 的基础设施，但没有 raw RTL/VCD adapter。先发布明确标注的模型波形；VCD/FST
   接入是独立后续里程碑。
4. 主路径应是可复制的一条 CLI 命令和 Markdown tutorial。Notebook 可以作为教学材料，但不作为唯一入口，
   以免隐藏环境、执行顺序和复现边界。
5. Hackathon、课程和论文都应建立在可复现 artifact 之后。早期先找少量协议工程师走通统一示例入口，比组织
   大型活动更有信息量。
6. 不使用“没有直接竞争者”或“替代现有验证体系”作为卖点。项目应说明与相邻生态的互补边界。

## 发布里程碑

以下是工作包估算，不是承诺日期。若由一位维护者完成，跨层切换和文档打磨会显著增加日历时间；引入一位
协议 reviewer 和一位首次体验测试者，即使不写核心代码，也能明显减少盲区。估算不包含等待外部规范评审的
日历时间，完成与否仍以 evidence gate 为准。

### M0：准备边界（当前工作包）

产物：

- 对外定位、宣称证据表和已知限制；
- Demo 分层与 scenario catalog；
- 生成产物与长期宣传资源的生命周期；
- public-preview release gate。

完成标准：团队能回答“现在展示什么、暂时不展示什么、需要什么证据才升级宣称”。本目录、双语材料和
claims/evidence 表已经完成 M0 的首版。

### M1：定向 AXI4 可用性预览（总量约 2–4 人周，当前已完成首个切片）

需要实现：

- 已有 Python package 配置和单一示例命令；仍需记录依赖版本并由非维护者验证干净安装；
- 将当前 demo-local scenario/result schema 收敛为可复用 schema，并补 replay；
- 让统一 presentation 接口根据场景输入选择投影：`AtomicFrame` 生成 ready/valid 协议波形，
  `CanonicalEvent` 生成明确标注的事件顺序波形；不把后者伪装成 pin/cycle timing；
- 当前统一的 24 个 AXI4 scenarios，覆盖多类 lifecycle/geometry/ordering/observation 行为；
  双语 coverage matrix 已从同一批运行结果生成；
- 在同一导航中为 2–3 个重点场景加入 constraint/trace 聚焦讲解；已有两案足以作为首版，
  只在新案例能说明不同观察边界或语义时增加长讲解；
- 在干净环境由非维护者完成的安装记录。

评审门槛：从 clone 到统一摘要不超过约 10 分钟；合法场景和 `expected_violation` 都以稳定命令结束；
至少覆盖 6 个不同知识主题，而不是同一规则的参数排列；波形开关只影响 observation/output，不改变场景语义。
M1 面向 5–10 位受邀测试者，不作为公开 release。

### M2：公开、可审计的 AXI4 technical preview（追加约 3–5 人周起）

需要实现：

- M2a 校正当前 24 个 scenario families，并公开最小 catalog 和贡献入口；
- M2b 根据 requirement 缺口增量调整场景，不以继续增加数量作为完成条件；
- requirement ID、规范文档 ID/revision/章节、适用 profile、执行 monitor 和状态的最小 catalog；
- tutorial、how-to、reference、explanation 四种文档入口；
- 6–8 个精选故事的静态页面；具名脚本可以确定性重建 `showcase/generated/`，其余结果按需生成；
- 已有 contributor guide、两类定向 issue form 和 release checklist；公开前仍需决定 code of conduct、
  security policy 与最小 CI 是否进入本次 preview。

公开发布门槛：至少三位目标用户无需维护者操作即可完成统一 AXI4 示例；所有公开宣称都能落到一个 case、
constraint 或明确的 status 页面。M3 可以在 M2a 后并行准备。文档四分法
可参考 [Diátaxis](https://diataxis.fr/start-here/)。

### M3：bridge 微网络故事（追加约 3–6 人周）

目标结构：

```text
AXI4 requester → AXI4 link → Bridge VirtualDut → APB4 link → memory/regbank endpoint
```

需要实现：

- 将当前 AXI4→APB witness 收敛到稳定的 translation/attachment API；
- read burst split、AW/W join、response fold、route miss 和串行 capacity 的四个故事；
- topology、跨 link causal trace、parent/child obligation 和 lease 状态视图；
- 明确区分协议规则、bridge 调度策略和系统 route contract。

发布门槛：演示能解释一个 burst 为什么变成多个 child operations、为什么当前 profile 串行执行，以及错误如何
折叠回 AXI response。Crossbar 不属于本里程碑。

### M4：外部 DUT 接入（约 6–12+ 人周，适合协作）

候选顺序应区分离线导入与在线闭环：

1. 离线导入结构化 transaction log；
2. 离线导入 VCD/FST pin observation；
3. cocotb/Verilator 在线 driver/observation adapter；
4. UVM transaction 或 simulator feedback bridge；
5. 与 Chisel/Diplomacy/CIRCT 交换 interface/profile 描述。

这个工作包会接触 simulator、时钟/reset、四态值、采样区间和大型 trace 性能，已经明显超过简单展示层。
它适合作为社区合作主题，不应为了宣传而临时伪造“RTL 波形”。cocotb 的 Quickstart 说明了小型完整 DUT
入口的重要性，First Steps 另行展示了波形反馈；Verilator 则指出大型 VCD 成本较高，可考虑 FST、trace depth
和时间窗控制。参见 [cocotb Quickstart](https://docs.cocotb.org/en/stable/quickstart.html)、
[cocotb First Steps](https://docs.cocotb.org/en/development/first_steps.html) 和
[Verilator waveform FAQ](https://verilator.org/guide/latest/faq.html)。

### M5：研究与教学传播（在 M2/M3 artifact 稳定之后）

- 一篇 10–15 分钟可复现的技术文章；
- 一个 2–3 分钟录屏，演示合法场景、单点变异和诊断定位；
- 一个 workshop/tutorial，主题是“从关系构造 AXI transaction lifecycle”；
- 寻找一个公开 bridge 或 endpoint 作为外部案例；
- artifact 达到可审计和可重放后，再考虑 JOSS、EDA/体系结构 workshop 或 FOSSi/ORConf 分享。

RFC 4101 关于协议模型的经验仍很适用：模型应回答协议解决的问题、消息意义和不直观的重要特征，并选择性
保留细节，而不是复制整份规范。参见 [RFC 4101](https://www.rfc-editor.org/info/rfc4101/)。学术发布则应把
每个图表和结论对应到可执行脚本；可参考 [ACM artifact evaluation 指南](https://sigsim.acm.org/conf/pads/2024/blog/artifact-evaluation/)。

## 社区协作角色

项目瓶颈不一定要求立即组建大团队，但需要把不同判断交给不同视角复核：

| 角色 | 首轮可交付内容 | 不要求 |
|---|---|---|
| 协议 reviewer | 校正 5–10 条 AXI requirements、profile 边界和反例 | 理解整个 runtime |
| 首次体验测试者 | 记录安装时间、困惑点、无法解释的图 | 修改核心代码 |
| 场景贡献者 | 提交一个固定 seed、单一学习目标的 case | 新建协议类 |
| RTL integration contributor | 提供一个公开小 DUT 和 pin mapping | 接管协议方法论 |
| 文档/可视化 contributor | 改进一张图、术语和错误解释 | 掌握所有 AMBA 细节 |

因此第一批 `good first issue` 应是边界清晰的 requirement 修订、场景元数据、图例或文档，不应把“实现 CHI”
之类的跨层工作贴成新手任务。GitHub 的开源指南也建议先设计可获得小成功的贡献漏斗，参见
[Building Communities](https://opensource.guide/building-community/)。

## 渠道顺序

1. 私下邀请 5–10 位验证、bridge 或开源 SoC 开发者完成 M1 统一示例，并只问具体问题；
2. M2 达到公开门槛后发布 GitHub technical preview、短文章和录屏，issue/discussion 作为可搜索的主反馈入口；
3. 在 cocotb、Chisel/Chipyard、RISC-V/open-source silicon 社区以“征集场景和 requirement 校正”方式分享；
4. 与一个公开 DUT 项目共同制作外部案例；
5. Demo 和叙事稳定后，再进入 FOSSi/ORConf 等更广渠道，参见
   [FOSSi events](https://fossi-foundation.org/events)。

不建议首轮同时经营多个即时聊天群。个人维护阶段，公开、可搜索、可异步回复的 issue/discussion 更可持续。

## 发布基础设施清单

当前仓库已有 MIT license、`0.3.0` 候选版本、package 配置、`CHANGELOG.md`、release notes、
`CONTRIBUTING.md` 和两类定向 issue form。本地隔离环境已经完成 sdist/wheel 构建与 wheel 安装；这证明
发布结构可用，但不能替代首次用户从干净 checkout 的复现。公开 preview 前还需要：

- 写清 Python/Node/Graphviz 依赖版本，并由非维护者验证统一 AXI4 命令；
- 决定是否在本次 preview 加入 `CODE_OF_CONDUCT.md`、安全报告方式和最小 CI；
- 创建正式 technical-preview tag 与可引用的 release artifact；commit、tag 和 push 仍由维护者控制；
- 继续补 known limitations 和 requirement status；
- 若增加 CI，只运行具名 showcase sanity 与必要定向验证，不要求新用户先跑全回归；
- 若进入论文或教学合作，再增加 `CITATION.cff`。

社区健康文件的作用和检查方式可参考
[GitHub community profiles](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/about-community-profiles-for-public-repositories)。

## 衡量采用，而非热度

优先记录：

- 新用户从 clone 到首个可读 artifact 的时间；
- 无维护者同步帮助时的统一示例完成比例；
- 外部提交的真实 scenario 和 requirement 修订；
- 第二次回来使用或贡献的人数；
- 外部 DUT/协议组合的可复现案例；
- issue 首次响应时间，以及同类问题是否在文档中收敛。

Stars、页面访问量和回归执行次数可以观察，但不作为主要完成标准。GitHub 的开源指标指南也建议区分发现、
使用、留存和维护响应，参见 [Open Source Metrics](https://opensource.guide/metrics/)。

## 暂停或调整条件

以下情况出现时，应先修正产品边界而不是继续扩大宣传：

- 三位目标用户都无法在统一导航帮助下解释重点场景的违规原因；
- scenario runner 开始复制协议 runtime，形成第二套语义；
- 为生成漂亮波形而改变正常 observation 或执行语义；
- bridge 示例只能依赖专用硬编码，无法说明 attachment/translation 的所有权；
- 外部反馈主要要求 raw RTL 接入，而维护资源仍只够修核心模型。

推广不是核心开发之外的装饰。它是用外部用户检验“方法能否被理解、复现和复用”的一轮架构验证。
