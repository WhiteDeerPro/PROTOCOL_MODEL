---
marp: true
theme: default
paginate: true
size: 16:9
title: Protocol Model — 从总线规则到可解释微系统
description: Protocol Model technical preview 中文演示稿
---

# Protocol Model

## 从总线规则到可解释微系统

面向片上通信的组合式语义建模与验证研究原型

**Technical preview in preparation**

---

# 同一条协议知识，为什么被写很多遍？

```text
规范条款 ─┬─→ scenario / driver
          ├─→ monitor / assertion
          ├─→ reference model
          └─→ waveform / report explanation
```

- AXI 的复杂性主要来自跨通道、跨事务、跨模块的关系；
- 同一关系被多次编码后，生成、检查和报告可能逐渐分叉；
- 失败时常能看到“哪里不对”，却难以追溯“违反了哪段生命周期”；
- Protocol Model 研究的是：能否让这些用途共享一份可组合语义。

---

# 核心假设：构造一次，多处投影

```text
事件 + 关系 + 资源
       ↓ compose / refine
  通信协议模型
   ↙      ↓       ↘
生成场景   检查行为   投影证据
```

目标不是把规范复制成代码，而是选择对验证有意义的关系：

- 哪些事件可以出现；
- 它们如何关联和排序；
- 哪些资源在生命周期中被占用；
- 失败怎样保留规则、事务和因果来源。

<small>状态：RESEARCH QUESTION — 是否显著减少重复，需要由公开案例检验。</small>

---

# 三种作用域，三个白话问题

| 对象 | 它先回答什么？ | 典型责任 |
|---|---|---|
| **LinkProtocol** | 一条连接上允许怎样通信？ | channel、event schema、ordering、completion |
| **VirtualDut** | 一个具体 module 收到通信后做什么？ | 地址操作、转换、路由、队列和 owner |
| **SystemProtocol** | 多个 module 接起来后整体怎样成立？ | topology、link ownership、端到端契约 |

attachment 把协议事件翻译成模块操作；observation 把采样帧降低成协议事件。

这不是按 AXI/APB 建立“设备继承树”，而是把协议端口装配到具名的虚拟 module。

---

# 当前已经有可执行工程证据

- **语义与观察**：typed event、constraint/resource/obligation、因果图、`AtomicFrame`、stall 与 reset；
- **LinkProtocol**：AXI4、AXI4-Lite、AXI4-Stream、AHB-Lite/AHB5 profile、APB3/4/5、ACE-Lite ordinary-data subset；
- **AXI4 行为**：burst、narrow/unaligned、read interleave、AW/W/B correlation、link-local exclusive eligibility；
- **模块与系统**：typed ports、AMBA attachments、地址 endpoint、同步微网络和 AXI4→APB bridge witness；
- **证据基础**：managed run store、manifest、DOT/WaveDrom renderer。

<small>状态：CURRENT — 范围见 implementation-status；这不是完整 compliance 声明。</small>

---

# 一套 AXI4 导航，多种阅读深度

![w:1050](../generated/axi4/coverage.svg)

**CURRENT：24 个实际执行场景、5 个主题；10 个合法输入与 14 个预期违规均满足声明期望。**

每个场景都可打开模型波形、因果图和机器结果；合法 narrow/unaligned 与 early-WLAST 是同一集合中增加逐步
源码、资源和诊断解释的两个重点场景，不另建 Quick Start 产品。

<small>场景数量说明行为广度，不自动等于官方 requirement coverage。</small>

---

# 第二个故事：一个最小 bridge 系统

```text
AXI4 requester
      │ AXI4 link
      ▼
Bridge VirtualDut
      │ APB4 link
      ▼
memory / regbank endpoint
```

- 一个 burst 产生多个 APB child operations；
- 当前 profile 逐笔串行执行，不暗示 APB 并发；
- AW/W join、错误聚合和 completion return 属于 bridge 生命周期；
- 三个 module、两条 link 已经构成微小 `SystemProtocol`，无需先加入 crossbar。

<small>状态：CURRENT witness + PROPOSED public story。</small>

---

# Bridge 普适化：已经到哪里？

```text
protocol events
  → attachment / codec
  → typed operation
  → TranslationStage + executor
  → target codec
  → target protocol events
```

**当前内核**：operation signature、stage contract、plan closure、fan-out ledger、capacity lease、serial executor。

**接入中**：让现有 full AXI4→APB bridge 使用 attachment-aware 公共 executor。

**待验证假设**：多个协议能否通过少量 codec 与可复用 stage，减少每个协议对各写一套 backend 的需求。

这是一条有工程依据的研究路线，还不是“任意协议自动桥接”。

---

# 边界比口号重要

当前不宣称：

- 完整符合 AXI4 官方规范；
- 验证任意 RTL、VCD、UVM transaction 或 simulator；
- 提供模型检查、定理证明或完整形式化验证；
- 已经自动生成任意协议对 bridge；
- 优于或取代 UVM、cocotb、商业 VIP、SVA/formal 工具。

模型生成的 waveform 会明确标注来源。强宣称只有在 requirement catalog、外部 DUT 和公开复现证据完成后才升级。

---

# 我们邀请社区共同回答问题

| 参与方式 | 一个可完成的首项贡献 |
|---|---|
| 协议工程师 | 校正一条 AXI requirement、profile 或 corner case |
| 验证工程师 | 提交一个可重放合法/违规场景 |
| RTL 集成者 | 提供一个公开小 DUT 与 observation mapping |
| 可视化贡献者 | 改进一张波形、因果图或术语解释 |

近期目标：**让少量外部用户从统一 AXI4 导航扫读 24 个场景，再独立打开、读懂并质疑其中两个重点场景。**

[架构地图](../../docs/architecture/technical-route/README.md) ·
[当前实现边界](../../docs/architecture/implementation-status.md) ·
[AXI4 示例](../generated/axi4/README.zh-CN.md)
