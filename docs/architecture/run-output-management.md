# 运行产物、可视化与文档发布架构

本模块管理的是模型运行之后的可观察结果，不参与协议判定。核心原则是：语义、视图、渲染、
存储和文档发布分别拥有清晰边界，任何一种图形工具都不能反向塑造协议模型。

## 数据流

```text
SemanticRun / SystemTrace / SystemProtocol
                 │
                 ▼
       semantic projection
       text / DOT / WaveJSON
                 │
        ┌────────┴────────┐
        ▼                 ▼
  source artifact      renderer
  (可检查、可复现)    Graphviz / WaveDrom
        │                 │
        └────────┬────────┘
                 ▼
          RunArtifactStore
   caller-selected path / atomic write / index
                 │
                 ▼
           run manifest v3
                 │ explicit publish
                 ▼
        DocumentationStore
        docs / showcase assets
```

推荐依赖方向向下：协议对象不承担图表职责；投影函数不承担文件系统职责；渲染器不承担
manifest 职责；存储层保持对 AXI、TileLink 或 ready-valid 的无关性。

## 四个职责边界

### `protocol_model.artifacts`

- `RunArtifactStore` 拥有一次运行目录、路径约束、原子写入、文件注册和 manifest。调用方可以显式提供目录；
  `out/` 只是省略目录参数时的临时默认。
- `RunBundle` 是供一次验证运行使用的薄门面，只组合存储与可视化发布，不实现协议知识。
- `ProtocolRecord`、`ConstraintEvidence` 是稳定的报告记录，避免 manifest 直接序列化运行时对象。
- records projection 负责把 `LinkProtocol`、`SystemProtocol` 显式降低为报告记录。它是展示边界，
  不是兼容层。
- `DocumentationStore` 管理被版本控制的发布树；目标既可以是 `docs/`，也可以是 `showcase/generated/`。
  覆盖、删除和重建子树都必须由具名发布动作显式调用。

### `protocol_model.visualization`

- projection 把语义对象转换成文本、DOT 或 WaveJSON。
- `GraphvizRenderer` 和 `WaveDromRenderer` 只做源格式到 SVG 的转换。
- `VisualizationPublisher` 同时保存可检查的源文件和渲染结果，并向 `RunArtifactStore` 注册二者。
- `system_topology_dot()` 与 `system_trace_dot()` 是当前架构的系统级视图，只依赖 record/trace 投影。

### 协议局部投影

协议特有的波形布局仍属于该协议。例如 AXI 五通道如何分组、字段宽度如何显示，不应进入通用
可视化包。AXI lane/field 投影后续位于 `protocol_model/link/amba/axi/axi4/visualization.py`；TileLink 也应在
自身协议包中产生 WaveJSON/DOT IR，再交给 publisher。

### 场景报告

场景层可以决定 case、标题、HTML 排版和要发布哪些图。运行目录、`dot` 调用、文档资源发布和
manifest 构造交给对应基础设施，从而减少不同调用方形成不同存储契约的机会。

## 两种存储生命周期

| 存储 | 生命周期 | 是否可原地替换 | 入口 |
|---|---|---:|---|
| run artifacts | 一次运行的不可变快照 | finalize 后不可写 | `RunArtifactStore`，目录由调用方选择 |
| maintained docs/assets | 被维护的发布树 | 可以，但必须显式 | `DocumentationStore` 或等价发布脚本 |

存储生命周期不由顶层目录名决定。普通交互运行可以使用 `out/<subject>/<run-id>/`、临时目录或用户指定的
workspace；测试优先使用临时目录。`docs/` 和 `showcase/generated/` 面向经过选择、需要随版本阅读的内容。
写入后两者必须是显式发布动作：从已经 finalize 的 run 或确定性 source IR 中选择内容，保存生成参数和来源，
再由 `DocumentationStore` 或专用脚本替换其拥有的子树。

宣传 Demo 可以把“运行 + 发布”封装成一个具名命令，因为用户调用该命令的目的就是重建公开资源。这个例外
不授权普通测试顺带更新图片；生成脚本仍应先在 staging 中完成全部渲染，成功后再发布，避免留下半套资源。

## Manifest v3

`manifest.json` 使用 `protocol-model.run/v3`，包含：

- `subject` 和 `run_id`；
- 顶层 verdict、cases、state 与 metadata；
- 通用 `protocols` 记录，可同时描述 link 和 system scope；
- 每个 artifact 的 kind、media type、case 和 source 标记。

manifest 当前不保存 Python 类型路径，也不暴露运行时对象。即使 point-to-point 场景被提升为
`SystemProtocol`，也可以同时记录其 system protocol 与实际使用的 link protocols。

## 一次运行的目录约定

```text
<caller-selected-run-root>/
├── manifest.json
├── constraints.json
├── constraints.md
├── report.html
├── network.svg
├── cases/<case>/...
└── sources/
    ├── network.dot
    └── cases/<case>/waveform.json
```

例如，临时运行可以选择 `out/axi4-demo/01/`；宣传脚本则可以在临时 staging 中创建同样结构，再显式发布到
`showcase/generated/axi4/`。两者使用相同 manifest 和安全路径规则，不维护两套 artifact schema。

路径只接受安全的 POSIX 相对路径，case 只能是一个路径段；artifact 必须位于本次 run root 内。
同一路径不能重复注册，finalize 后不能继续写入，从而避免报告索引与磁盘内容悄悄分叉。
