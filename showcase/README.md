# Protocol Model Showcase

本目录是项目的公开展示工作区，但不同内容具有不同生命周期。稳定架构定义仍以
[`docs/architecture`](../docs/architecture/README.md) 为准，当前实现边界以
[`implementation-status.md`](../docs/architecture/implementation-status.md) 为准。

## 按生命周期分区

| 分区 | 内容 | 何时修改 |
|---|---|---|
| [可直接发布材料](materials/README.md) | 双语 one-pager、deck、launch post、录屏脚本和手工总览图 | 准备网页、帖子、演讲或录屏时 |
| [可执行示例源码](demos/README.md) | 场景声明、runner、运行方法和教学导航 | 示例实现或讲解路径变化时 |
| [生成证据](generated/README.md) | 波形、因果图、机器结果、source IR、provenance 和 manifest | 只由拥有对应子树的具名脚本重建 |

宣传稿不定义实现状态，生成结果也不由人工改写。这些分区通过链接协作，不复制逐场景清单或手写第二套统计。
面向维护者的传播计划、定位与宣称审计位于
[`docs/community`](../docs/community/README.md)，不与可直接发布的材料混放。

### 可执行故事导航

- [统一 AXI4 示例](demos/axi4/README.md)：点到点协议场景及由概览到重点讲解的统一入口；
- [异步四相与频差示例](demos/link/four_phase_handshake/README.md)：REQ/ACK observation、异步 FIFO
  高差频弹性与近同频长期漂移；
- [CHI Issue H direct-read 组件教程](demos/chi/issue_h_read_no_snp/README.md)：拆开观察
  `ReadNoSnp→CompData`、双向独立 link、L-Credit 与 transaction correlation；
- [AXI4-Lite 单管理端地址总线](demos/system/axi4_lite_single_manager_fabric/README.md)：一个 manager、
  三个 subordinate、地址译码/响应 mux，以及星形与传统 bus-strip 两种视图；
- [AXI4 read-only AR/R 单管理端读 fabric](demos/system/axi4_single_manager_read_demux/README.md)：两个 subordinate、
  不同 RID 的独立返回，以及同 RID 跨目标的 owner-table 锁定；
- [AXI4 read-only AR/R 2×4 crossbar](demos/system/axi4_read_2x4_crossbar/README.md)：两个 manager、
  四个 subordinate、raw-ID return-owner FIFO 与 manager-local RID destination lock；
- [CHI 两级 XP 路由读取](demos/system/chi_issue_h_routed_read/README.md)：调用方声明的六条 transport hop、
  两个有限 router、AddressTarget-backed Home 和端到端 `ReadNoSnp` lineage；
- [CHI 2×2 XP clean-coherence mesh](demos/system/chi_issue_h_clean_2x2_mesh/README.md)：四角 XP 方环、
  两路 Snoop fan-out、REQ/RSP/SNP/DAT 多跳路径和 `I/SC/UC` 稳定状态闭合；
- [VirtualDut 与其余微型网络示例](demos/README.md)：bridge、crossbar、Sensor-DMA 和 interrupt control。

## 一句话定位

> Protocol Model 是一种从基础通信属性逐层构造 InterfaceProtocol、VirtualDut 和 SystemProtocol，并把构造结果
> 用于场景生成、约束检查与可解释证据的方法及参考实现。

当前更适合称为“通信语义建模与验证研究原型”，而不是 RTL 模拟器、完整 AXI compliance checker，或
UVM、cocotb、形式化工具的替代品。具体能力和证据限定见
[当前实现状态](../docs/architecture/implementation-status.md)。

## 首轮阅读路径

```text
第一次接触
    ↓
双语项目总览 / one-pager
    ↓
统一 AXI4 导航：先扫主题和 verdict
    ↓
打开任意场景：波形 + 因果图 + 机器结果
    ↓
选择同一集合中的重点场景：逐步解释源码与诊断
    ↓
继续阅读架构或参与 requirement / scenario 校正
```

- [中文版总览 SVG](materials/assets/overview/protocol-model-overview.zh.svg) / [English overview SVG](materials/assets/overview/protocol-model-overview.en.svg)
- [中文版总览 PNG](materials/assets/overview/protocol-model-overview.zh.png) / [English overview PNG](materials/assets/overview/protocol-model-overview.en.png)
- [统一 AXI4 示例说明](demos/axi4/README.md)
- [异步四相握手与频差 Showcase](generated/link/four-phase-handshake/README.md)
- [AXI4-Lite 单管理端、多从设备](generated/system/axi4-lite-single-manager-fabric/README.md)
- [AXI4 read-only AR/R 单管理端、多从设备读返回](generated/system/axi4-single-manager-read-demux/README.md)
- [AXI4 read-only AR/R 2×4 crossbar](generated/system/axi4-read-2x4-crossbar/README.md)
- [CHI 两级 XP 路由读取](generated/system/chi-issue-h-routed-read/README.md)
- [CHI 2×2 XP Clean ReadUnique mesh](generated/system/chi-issue-h-clean-2x2-mesh/README.md)
- [VirtualDut 与微型网络示例](demos/README.md)
- [中文 one-pager](materials/one-pager.zh-CN.md) / [English one-pager](materials/one-pager.en.md)

AXI4 示例共 24 个场景，每个场景都提供模型波形、因果图和机器结果，其中两个场景增加逐步精讲。精讲只改变
阅读密度，不再作为与场景集合分离的“Quick Start 产品”。场景数量描述当前展示样本，不能直接换算为规范
条款覆盖率。

## 文件生命周期

- `showcase/materials/`：可直接发布的文字和手工视觉源；
- `showcase/demos/`：示例声明、runner 与教学导航；
- `showcase/generated/`：具名发布脚本拥有并显式重建的执行证据；
- 普通运行使用临时目录、调用方指定目录或默认 `out/`，不隐式改写发布树；
- 全量回归产物不进入 showcase，也不因一次普通运行改写文档。
