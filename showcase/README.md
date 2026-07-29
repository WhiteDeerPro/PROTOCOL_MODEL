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
多跳路径。较大的 mesh 扩展结构与路径规模；opcode、Retry/error、容量替换策略和
deadlock/fairness 仍按各自 profile 与证据记录。

更多 bridge、fabric、VirtualDut 和异步握手示例见
[可执行示例目录](demos/README.md)；生成树中的精选浏览入口见
[生成证据目录](generated/README.md)，其余发布 leaf 可从各 Demo 导航进入。

## 怎样阅读一份 Showcase

每份公开场景把以下内容连接到同一次确定性执行：

1. `demos/` 中的输入、装配代码和具名 runner；
2. 预期与实际 verdict，以及相应的规则或状态断言；
3. `generated/` 中的拓扑、波形、时空、序列或因果视图；
4. 机器可读结果、可检查的 DOT/WaveJSON 等 source IR；
5. `manifest.json` 与 `provenance.json` 中的生成入口和能力边界。

各类产物对应明确的证据范围：

| 产物 | 时间或数据来源 | 支持的结论 |
|---|---|---|
| topology | publication 的 elaborated/resolved construction；按场景逐案生成或显式共享，具体方式见 provenance | 实际装配的 module、connection，以及存在时的协议专用 forwarding abstraction |
| timeline / time-space | 语义事件或具名 model step | lifecycle、correlation、状态提交和逻辑顺序 |
| waveform | 场景声明的 observation basis | event/frame 输入或模型 post-state 随采样点变化 |
| verdict / machine result | 当前 profile 的 monitor 与断言 | 该输入在已声明边界内的结果 |

raw RTL/VCD、cycle timing、完整协议 compliance 和条款覆盖需要各自的输入与验证证据。场景数描述公开
示例的广度。

## 源码与生成结果的边界

- `showcase/demos/` 保存场景编排、runner 和展示投影；协议规则来自 `protocol_model/`；
- `showcase/generated/` 由拥有相应子树的具名发布脚本重建；
- 发布脚本保存 SVG 及其 DOT/WaveJSON/JSON 源、manifest 和 provenance；
- 普通运行写入临时目录或调用方指定的 run root；发布树更新使用具名发布入口；
- Showcase 模型可以由调用方重复执行以检查示例是否腐化；可复用实现仍属于 `protocol_model/`。

重建统一 AXI4 Gallery：

```bash
npm ci
dot -V
python3 showcase/demos/axi4/run.py
```
