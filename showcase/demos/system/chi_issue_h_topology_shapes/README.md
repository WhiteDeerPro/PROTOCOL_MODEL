# CHI Issue H：两种调用方拓扑的可执行见证

本示例把同一条受限 `ReadNoSnp → CompData` 生命周期放进两种由调用方明确构造的
`SystemProtocol` topology：

1. 四 router 双向 ring backbone；R1 挂两个 leaf，R3 只做 transit；
2. 16 router 的 4×4 双向 mesh；四个 endpoint 位于四角，采用确定性 X-then-Y exact route。

两案复用 `protocol_model` 中的 CHI participant、finite store-and-forward router、transport connection、
Link Credit 和 transaction session。`model.py` 只保存用户可读的参考装配；它不是 CHI package 的内建
ring/mesh recipe。

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
`chi-issue-h-topology-shapes/` 叶级目录。

## 生成内容

- `heterogeneous-ring-star.svg`：双向 ring backbone、非均匀 leaf attachment，以及本次 REQ/DAT 路径；
- `four-by-four-mesh.svg`：4×4 mesh、四角 endpoint、全部声明连接与角到角执行路径；
- `route-comparison.svg`：两案的规模、actual route 和共同能力边界；
- `result.json`：紧凑的 topology、transaction、route、runtime 摘要与断言；
- `README.md`：从本次执行结果生成的阅读导航；
- `provenance.json`：构造入口、renderer、时间基准与宣称边界；
- `sources/*.dot`：三张 SVG 的可检查 Graphviz 源；
- `manifest.json`：发布脚本实际拥有的文件、case 和结果。

图中的固定位置属于示例级 presentation metadata；节点、连接、exact route 和执行路径均从同一次实际装配读取。
灰色连接表示已声明但本次 read 未经过的 topology，不表示已经覆盖相应 traffic 组合。

## 能力边界

这里的 ring 和 star 描述点到点 topology 外观，不表示 shared bus、broadcast 或共享介质仲裁。本示例也不宣称
完整 CHI、RSP/SNP coherence、adaptive routing、QoS/fairness、性能结论或 deadlock freedom。图中的路径是
模型级 transport/correlation 证据，不是 raw pin waveform，也不约束 RTL 周期距离。

## 文件职责

- `model.py`：构造两种 topology 并执行相同的 direct read；
- `presentation.py`：只从 assembly/result 投影三张图和生成版说明；
- `run.py`：管理 staging、渲染、provenance、manifest 与显式发布。

测试可以导入 `model.py` 的 public builder/executor 检查结构和行为，但 showcase 不依赖 `tests/`。
