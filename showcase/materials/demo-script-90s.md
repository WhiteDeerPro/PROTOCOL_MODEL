# Protocol Model 90 秒演示录屏脚本

本脚本提供两条各约 90 秒的旁白，不要求在同一视频中连续播放两种语言。画面右下角始终显示状态标签：
绿色 `CURRENT` 表示当前实现，蓝色 `PROPOSED` 表示已经规划但尚未达到公开运行门槛。

录制前必须核对 [claims-and-evidence.md](../strategy/claims-and-evidence.md)。统一 AXI4 介绍集当前包含 24 个
场景，每案都有波形与因果图，其中两个增加详细解说；bridge 展示仍用线框、标题卡或明确标注的
设计预览，不剪辑成已经通过公开演示验收的终端画面。

## 中文版

| 时间 | 画面 | 旁白与屏幕文字 | 状态 |
|---:|---|---|---|
| 0–8s | 项目标题；背景由五条 AXI lane 简化成一条事务线 | **旁白：**“一条 AXI 规则，通常会被写进生成器、检查器和报告很多次。Protocol Model 想让它们共享同一份语义构造。” | 主题 |
| 8–21s | 三个简洁方框依次出现：Link、Module、System | **旁白：**“LinkProtocol 说明一条连接上允许怎样通信；VirtualDut 说明一个具体 module 怎样响应；SystemProtocol 说明多个 module 接起来后整体要满足什么。” | CURRENT |
| 21–36s | 展示统一 AXI4 scenario matrix；五个主题分组和 24 张 case 卡片依次高亮 | **旁白：**“先看广度：24 个可执行场景分布在生命周期、burst 几何、ordering/interleave、observation/reset 和 exclusive/profile。其中 10 个合法输入、14 个预期违规都符合声明期望；这表示场景证据，不等于规范条款覆盖率。” | CURRENT |
| 36–55s | 从同一 matrix 选中 legal narrow/unaligned 与红色 early `WLAST`；展开标注 `ARESETn` 的协议波形和因果图 | **旁白：**“每个场景都能打开波形和因果图，其中两个再讲透。这里是合法四拍窄传输，以及只改变首拍 WLAST 的预期违规。展开的 AW/W/B 字段、因果关系和结构化结果帮助解释判定。” | CURRENT detail |
| 55–70s | requester → AXI4 → bridge → APB4 → regbank；一个 parent 展开为四个 child，再逐个完成 | **旁白：**“下一个故事越过单条 link：AXI burst 在 bridge 中拆成 APB child，按当前 profile 串行执行，再把 completion 折回原请求。” | CURRENT witness / PROPOSED presentation |
| 70–82s | 画面左侧保留当前能力，右侧灰化 VCD、formal、crossbar 图标 | **旁白：**“它现在还不是完整 compliance suite、RTL 波形工具或形式化证明系统。我们先把可执行边界和证据说清楚。” | CURRENT boundary |
| 82–90s | GitHub/项目链接；三个入口：requirement、scenario、visualization | **旁白：**“如果你熟悉协议、验证或可视化，欢迎从校正一条规则、贡献一个场景或改进一张图开始。” | 邀请 |

### 中文屏幕收尾文案

```text
Protocol Model
Construct protocol semantics. Replay behavior. Explain evidence.

Executable first slice · technical preview in preparation
```

## English version

| Time | Visual | Voice-over and on-screen copy | Status |
|---:|---|---|---|
| 0–8s | Project title; five simplified AXI lanes converge into one transaction line | **Voice-over:** “One AXI rule is often rewritten in a generator, a checker, and a report. Protocol Model asks whether they can share one semantic construction.” | Theme |
| 8–21s | Three clean blocks appear: Link, Module, System | **Voice-over:** “A LinkProtocol defines legal communication on one connection. A VirtualDut describes how one concrete module responds. A SystemProtocol states what must hold after modules are connected.” | CURRENT |
| 21–36s | Show the unified AXI4 scenario matrix; five theme groups and 24 case cards highlight in sequence | **Voice-over:** “Start with breadth: 24 executable scenarios span lifecycle, burst geometry, ordering/interleave, observation/reset, and exclusive/profile behavior. Ten legal inputs and fourteen expected violations all match their declared expectations. This is scenario evidence, not a specification coverage percentage.” | CURRENT |
| 36–55s | Select legal narrow/unaligned and red early `WLAST` from the same matrix; expand the `ARESETn` protocol waveform and causal graph | **Voice-over:** “Every case opens into a waveform and causal graph; two add a deeper walkthrough. Here are a legal four-beat narrow transfer and an expected violation made only by changing first-beat WLAST. Expanded AW/W/B fields, causal relationships, and structured results explain the verdict.” | CURRENT detail |
| 55–70s | requester → AXI4 → bridge → APB4 → register bank; one parent expands into four children that complete serially | **Voice-over:** “The next story crosses a link boundary. An AXI burst becomes APB child operations, executes serially in the current profile, and folds completion back into the parent request.” | CURRENT witness / PROPOSED presentation |
| 70–82s | Current capabilities remain bright; VCD, formal, and crossbar icons are greyed out | **Voice-over:** “This is not yet a complete compliance suite, an RTL waveform tool, or a formal proof system. The preview starts by making its executable boundary and evidence explicit.” | CURRENT boundary |
| 82–90s | Project link and three entry points: requirement, scenario, visualization | **Voice-over:** “If you work on protocols, verification, or visualization, start by correcting one rule, contributing one scenario, or making one diagram clearer.” | Invitation |

### English closing card

```text
Protocol Model
Construct protocol semantics. Replay behavior. Explain evidence.

Executable first slice · technical preview in preparation
```

## 制作约束

- `AtomicFrame` 场景的 waveform 标注 `Model-generated virtual-interface waveform`；`CanonicalEvent` 场景的
  事件图标注 `Model-generated link-event sequence`，并明确它不是 pin/cycle timing；
- `AtomicFrame` AXI 波形展示 `ARESETn`，并在图注中说明它是模型内部 active-high `reset` 的取反投影；
- 任何终端命令都从干净 checkout 实际录制，不用静态文本冒充运行；
- 违规场景显示 manifest `metadata.run_status: success`、case `observed: FAIL`、`expectation: MET` 三个不同概念；
- bridge 动画显示“4 个 child obligations，1 个 active child”，不画成四笔 APB 并发；
- 视频说明中链接具体场景、版本和生成命令；若 asset 尚未发布，保留 `PROPOSED` 标签。
