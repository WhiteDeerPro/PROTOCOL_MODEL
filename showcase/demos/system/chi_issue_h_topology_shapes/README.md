# CHI Issue H：两种独立的调用方拓扑见证

本源码目录共享装配和展示投影，但发布为两个彼此独立的 `SystemProtocol` topology 叶节点：

1. [`chi-issue-h-heterogeneous-ring-star`](../../../generated/system/chi-issue-h-heterogeneous-ring-star/README.md)：
   四 router 双向 ring backbone；R1 挂两个 leaf，R3 只做 transit；
2. [`chi-issue-h-four-by-four-mesh`](../../../generated/system/chi-issue-h-four-by-four-mesh/README.md)：
   16 router 的 4×4 双向 mesh；四个 endpoint 位于四角，采用确定性 X-then-Y exact route。

两案复用 `protocol_model` 中的 CHI participant、finite store-and-forward router、transport connection、
Link Credit 和 transaction session。`model.py` 只保存用户可读的参考装配；它不是 CHI package 的内建
ring/mesh recipe。

图中将 `ChiStoreForwardRouterNode` 简写为 **XP abstraction**。这是对 CHI
路由边界的简单拓扑表达：节点显式具有 ingress queue、exact NodeID route、
egress 与逐 hop Link Credit；它不等同于完整 XP 微架构，也不提供 pipeline
周期或物理延迟模型。

## 运行

显式重建正式发布子树：

```bash
.venv/bin/python \
  showcase/demos/system/chi_issue_h_topology_shapes/run.py
```

开发或复核时可以先写到临时目录：

```bash
.venv/bin/python \
  showcase/demos/system/chi_issue_h_topology_shapes/run.py \
  --publish-root /tmp/protocol-model-chi-topology-shapes
```

发布脚本先在目标目录旁完成执行、渲染、manifest 和 provenance，然后只替换
`chi-issue-h-heterogeneous-ring-star/` 与 `chi-issue-h-four-by-four-mesh/` 叶级目录。也可以只重建
其中一案：

```bash
.venv/bin/python \
  showcase/demos/system/chi_issue_h_topology_shapes/run.py \
  --case four-by-four-mesh
```

## 生成内容

- 每个 leaf 只包含本 case 的 topology/path SVG 与 `sources/*.dot`；
- `result.json`：本 case 的 topology、transaction、route、runtime 摘要与断言；
- `README.md`：从本次执行结果生成的阅读导航；
- `provenance.json`：构造入口、renderer、时间基准与宣称边界；
- `manifest.json`：该 leaf 实际拥有的文件、case 和结果。

图中的固定位置属于示例级 presentation metadata；节点、连接、exact route 和执行路径均从同一次实际装配读取。
灰色连接表示已声明但本次 read 未经过的 topology，不表示已经覆盖相应 traffic 组合。

## 能力边界

这里的 ring 和 star 描述点到点 topology 外观，不表示 shared bus、broadcast 或共享介质仲裁。本示例也不宣称
完整 CHI、RSP/SNP coherence、adaptive routing、QoS/fairness、性能结论或 deadlock freedom。图中的路径是
模型级 transport/correlation 证据，不是 raw pin waveform，也不约束 RTL 周期距离。

## 文件职责

- `model.py`：构造两种 topology 并执行相同的 direct read；
- `presentation.py`：从单案 assembly/result 投影 topology/path 图和生成版说明；
- `run.py`：共享 staging/渲染逻辑，但分别生成两个 leaf publication。

测试可以导入 `model.py` 的 public builder/executor 检查结构和行为，但 showcase 不依赖 `tests/`。
