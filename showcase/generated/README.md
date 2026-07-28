# 生成的 Showcase 证据

本目录保存经过选择、适合随仓库阅读的执行证据。除本索引外，各叶级发布目录由
[`showcase/demos`](../demos/README.md) 中的具名脚本拥有，不作为人工编辑的图片或报告源。

## 浏览入口

| 发布集 | 证据边界 |
|---|---|
| [AXI4 场景集](axi4/README.zh-CN.md) | 合法/违规 transaction、verdict、pin-level 波形与因果图 |
| [CHI Issue H flow gallery](chi/issue-h-flow-gallery/README.md) | 5 个实际执行 coherence/progress 流程的 resolved XP topology、transaction 时空图、显式因果图与语义事件时间线 |
| [CHI 异构 ring + star](system/chi-issue-h-heterogeneous-ring-star/README.md) | 非均匀 attachment、方向化 exact route 和 quiescence 证据 |
| [CHI 4×4 mesh](system/chi-issue-h-four-by-four-mesh/README.md) | 16-router 构造、角到角 exact route 和 quiescence 证据 |

CHI flow gallery 的 topology 只声明各案实际构造并执行的 XP forwarding boundary，timeline 不是 pin/cycle RTL
波形；独立 topology leaf 也不以网络规模声明 opcode 覆盖。

## 所有权与重建

- 每个发布目录的 `provenance.json` 记录源码入口、重建命令和展示边界；
- `manifest.json` 列出本次发布实际拥有的文件、source IR 和渲染结果；
- 发布脚本先在 staging 目录完成执行和渲染，再只替换自己拥有的叶级目录；
- 普通运行应写入临时目录、调用方指定的 scratch 目录或默认运行目录，不隐式改写这里；
- 修改图像或说明时，应修改对应 Demo 的场景或 presentation 源，再运行其具名脚本，不直接修补生成文件。

例如，`axi4/` 由 [`demos/axi4/run.py`](../demos/axi4/run.py) 发布；CHI、异步握手和
VirtualDut/SystemProtocol 示例的入口可从 [Demo 导航](../demos/README.md) 找到。源码目录使用 Python
标识符，发布目录可使用适合链接的连字符 slug，两者以 `provenance.json` 的记录为准。

这里保存的是模型运行和教学投影证据。波形或时空图只有在各自 README 和 provenance 明确声明时，才表示
pin/cycle observation、transport tick 或 CanonicalEvent 序列；不能仅凭 SVG 外观推断为 RTL/VCD 实测。
