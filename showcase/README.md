# Protocol Model Showcase

这里汇集可运行的场景与由同一次执行生成的证据。稳定架构定义仍以
[架构文档](../docs/architecture/README.md)为准；当前支持范围和缺口以
[实现状态](../docs/architecture/implementation-status.md)为准。

## 精选 Gallery

| 场景 | 学习目标 | 可浏览结果 | 重建入口 |
|---|---|---|---|
| AXI4 场景集 | 从事务生命周期、字节几何、ordering、observation 与 exclusive/profile 五个主题检查合法和违规输入 | [中文](generated/axi4/README.zh-CN.md) / [English](generated/axi4/README.en.md) | [`demos/axi4/run.py`](demos/axi4/run.py) |
| CHI Issue H flow gallery | 比较 5 个 coherence/progress 流程的 resolved XP topology、transaction 时空、显式因果关系与语义事件时间线 | [生成证据](generated/chi/issue-h-flow-gallery/README.md) | [`demos/chi/issue_h_flow_gallery/`](demos/chi/issue_h_flow_gallery/README.md) |
| CHI 异构 ring + star | 检查非均匀 attachment、方向化 exact route 与最终静止 | [生成证据](generated/system/chi-issue-h-heterogeneous-ring-star/README.md) | [`demos/system/chi_issue_h_topology_shapes/`](demos/system/chi_issue_h_topology_shapes/README.md) |
| CHI 4×4 mesh | 检查 16-router 构造、角到角长路径、route-table closure 与最终静止 | [生成证据](generated/system/chi-issue-h-four-by-four-mesh/README.md) | [`demos/system/chi_issue_h_topology_shapes/`](demos/system/chi_issue_h_topology_shapes/README.md) |

flow gallery 的重点是已执行事务、状态闭合与局部 progress 组合；两个 topology leaf 的重点是结构和
多跳路径。较大的 mesh 不会自动覆盖更多 opcode、Retry/error、容量替换策略或 deadlock/fairness 性质。

更多 bridge、fabric、VirtualDut 和异步握手示例见
[可执行示例目录](demos/README.md)；所有已发布结果按职责列在
[生成证据目录](generated/README.md)。

## 怎样阅读一份 Showcase

每份公开场景把以下内容连接到同一次确定性执行：

1. `demos/` 中的输入、装配代码和具名 runner；
2. 预期与实际 verdict，以及相应的规则或状态断言；
3. `generated/` 中的拓扑、波形、时空、序列或因果视图；
4. 机器可读结果、可检查的 DOT/WaveJSON 等 source IR；
5. `manifest.json` 与 `provenance.json` 中的生成入口和能力边界。

图是模型执行的投影，不是 raw RTL/VCD 采样。CHI flow gallery 五案的 topology 都来自各案 resolved
construction，并显式包含实际执行的 XP forwarding abstraction。timeline 以语义事件为时间基准，
不是 pin/cycle 波形。场景通过并不表示完整协议 compliance；场景数也不能换算成规范条款覆盖率。

## 源码与生成结果的边界

- `showcase/demos/` 保存场景编排、runner 和展示投影，不重新实现协议规则；
- `showcase/generated/` 只由拥有相应子树的具名发布脚本重建；
- 发布脚本保存 SVG 及其 DOT/WaveJSON/JSON 源、manifest 和 provenance；
- 普通运行写入临时目录或调用方指定的 run root，不隐式改写发布材料；
- 测试可以执行 Showcase 模型以防止示例腐化，但可复用实现仍属于 `protocol_model/`。

重建统一 AXI4 Gallery：

```bash
npm ci
dot -V
make showcase-axi4
```
