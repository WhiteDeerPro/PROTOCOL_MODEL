# 手工宣传视觉资源

本目录属于可直接发布的 `showcase/materials/`，保存人工维护的总览图，以及经过人工选择、需要随版本长期
阅读的图片或短媒体资源。可执行 Demo 的 WaveJSON、DOT、SVG、trace、结果和 manifest 由具名脚本发布到
`showcase/generated/`；普通运行不会隐式写入这两个受版本控制的目录。

当前人工维护资源：

- [`overview/protocol-model-overview.zh.svg`](overview/protocol-model-overview.zh.svg)：中文 16:9 项目总览；
- [`overview/protocol-model-overview.en.svg`](overview/protocol-model-overview.en.svg)：English 16:9 project overview。
- [`overview/protocol-model-overview.zh.png`](overview/protocol-model-overview.zh.png) / [`overview/protocol-model-overview.en.png`](overview/protocol-model-overview.en.png)：
  由同目录具名脚本从 SVG 显式生成，适合不接受 SVG 的发布平台。

发布资源时应同时记录：

- 来源 scenario ID 和 release/commit；
- 生成命令、profile 和 seed；
- 这是说明性手绘图、模型生成的 virtual-interface waveform，还是外部 RTL observation；
- 必要的裁剪或标注步骤；
- 对应 source artifact 的位置或可重新生成方式。

首页只选择能独立说明一个概念的手工资源。完整 scenario set 的波形和因果图由 runner 统一发布到
`showcase/generated/`；它们可以随技术预览进入版本控制，但不复制到本目录，也不作为手工视觉源维护。
