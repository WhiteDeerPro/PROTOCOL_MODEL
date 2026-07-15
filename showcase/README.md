# Protocol Model Showcase

本目录是项目的公开展示工作区，但不同内容具有不同生命周期。稳定架构定义仍以
[`docs/architecture`](../docs/architecture/README.md) 为准，当前实现边界以
[`implementation-status.md`](../docs/architecture/implementation-status.md) 为准。

## 三个入口

| 入口 | 内容 | 何时修改 |
|---|---|---|
| [可直接发布材料](materials/README.md) | 双语 one-pager、deck、launch post、录屏脚本和手工总览图 | 准备网页、帖子、演讲或录屏时 |
| [统一 AXI4 示例](demos/axi4/README.md) | 场景声明、运行方法，以及同一集合内由概览到重点讲解的入口 | 示例实现或教学导航变化时 |
| `generated/` | 具名脚本发布的波形、因果图、机器结果、source IR、provenance 和 manifest | 只由对应发布脚本重建 |

宣传稿不定义实现状态，生成结果也不由人工改写。三个入口通过链接协作，不复制逐场景清单或手写第二套统计。

## 一句话定位

> Protocol Model 是一种从基础通信属性逐层构造 LinkProtocol、VirtualDut 和 SystemProtocol，并把构造结果
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
