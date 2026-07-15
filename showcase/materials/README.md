# Protocol Model 对外材料

本目录保存可以直接改编为网页、长图或演示文稿的双语源稿。它们面向第一次接触项目的人，因此先讲问题与
方法，再引入工程术语；稳定的技术定义仍以 [`docs/architecture`](../../docs/architecture/README.md) 为准。

## 材料入口

| 用途 | 中文 | English |
|---|---|---|
| 单页项目介绍 | [one-pager.zh-CN.md](one-pager.zh-CN.md) | [one-pager.en.md](one-pager.en.md) |
| 10 页演示文稿 | [deck.zh-CN.md](deck.zh-CN.md) | [deck.en.md](deck.en.md) |
| GitHub Discussion / 技术论坛发布帖 | [launch-post.zh-CN.md](launch-post.zh-CN.md) | [launch-post.en.md](launch-post.en.md) |
| 90 秒演示录屏脚本 | [demo-script-90s.md](demo-script-90s.md) | 同一文件双语维护 |
| 手工总览图（SVG/PNG） | [assets/overview](assets/overview/README.md) | 中文、English |

两份 deck 使用 Marp 兼容的 Markdown front matter 与 `---` 分页。即使不使用 Marp，也可以按普通 Markdown
阅读或逐页迁移到 PowerPoint、Keynote、Figma 等工具。

## 使用与复核

- Deck 可由 Marp 直接渲染，也可以逐页迁移到 PowerPoint、Keynote 或 Figma；
- SVG 是手工总览图的维护源，PNG 由 [`render_png.py`](assets/overview/render_png.py) 显式重建；
- 示例波形、因果图和运行结果不在本目录手工维护，统一从 [`generated/axi4`](../generated/axi4/) 引用；
- 准备发布时，对照[当前实现状态](../../docs/architecture/implementation-status.md)和
  [0.3.0 发布说明](../../docs/releases/0.3.0.md)复核所有 `CURRENT`、`PROPOSED` 和
  `RESEARCH QUESTION` 标签。

当前稿件采用“24 个 AXI4 场景，其中 2 个在同一导航内精讲”的时间快照。数字和状态变化时先更新可执行
场景及实现状态，再统一修改本目录的公开稿。
