# 运行产物、可视化与文档发布架构

本模块接收模型运行后的可观察结果，依次完成语义投影、渲染、保存和文档发布。协议层在上游完成
规则判定，可视化与存储层据此生成只读结果。

本页聚焦文件生命周期和发布契约；图所表达的事实、ViewIR 分类及 renderer 选择见
[可视化视图与 Artifact 管理](visualization-and-artifacts.md)。

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
           run manifest v4
                 │ explicit publish
                 ▼
        DocumentationStore
        docs / showcase assets
```

各阶段按下表交接：

| 阶段 | 输入 | 拥有的输出 |
|---|---|---|
| 协议与系统运行 | event、operation、trace、verdict | 权威语义事实 |
| projection | 权威对象或稳定 record | text、DOT、WaveJSON 等 source artifact |
| renderer | source artifact | SVG 等渲染结果 |
| artifact store | source、rendered artifact 与报告记录 | 原子保存的 run 目录和 manifest |
| documentation publish | 已 finalize 的 run 或确定性 source IR | 版本控制中的精选资源 |

这条依赖方向让存储层复用于 AXI、TileLink 和 ready-valid 等协议，同时让 renderer 专注格式转换。

## 四个职责边界

### `protocol_model.artifacts`

- `RunArtifactStore` 拥有一次运行目录、路径约束、原子写入、文件注册和 manifest。调用方可以显式提供目录；
  `out/` 只是省略目录参数时的临时默认。
- `RunBundle` 是供一次验证运行使用的薄门面，组合存储与可视化发布；协议对象在上游提供投影输入。
- `ProtocolRecord` 进入 manifest 的 `protocols`，`ConstraintRecord` 进入 `constraints.json/.md`；两者为
  运行边界提供稳定报告 schema。约束从协议声明导出时状态为 `declared`；附着具体 trace、case 或 proof
  witness 后成为验证证据。
- records projection 负责把 `InterfaceProtocol`、`SystemProtocol` 显式降低为稳定报告记录，形成运行对象
  与持久化 schema 之间的展示边界。
- `DocumentationStore` 管理被版本控制的发布树；目标既可以是 `docs/`，也可以是 `showcase/generated/`。
  具名发布动作显式发起覆盖、删除和子树重建。

### `protocol_model.visualization`

- projection 把语义对象转换成文本、DOT 或 WaveJSON。
- `GraphvizRenderer` 和 `WaveDromRenderer` 只做源格式到 SVG 的转换。
- `VisualizationPublisher` 同时保存可检查的源文件和渲染结果，并向 `RunArtifactStore` 注册二者。
- `system_topology_dot()` 与 `system_trace_dot()` 是当前架构的系统级视图，只依赖 record/trace 投影。

事务消息、状态变化与显式因果关系采用独立的
[transaction time-space view](../visualization/transaction-time-space-view.md)。当前 v1 保存
message/state/causal IR；operation lifetime、阻塞区间和资源占用将在相应 lifecycle/progress projection
稳定后扩展。该视图与 topology、waveform 和 causal graph 共享 event/operation 引用，各自保留适合其问题的
布局与证据粒度。

### 协议局部投影

协议包拥有其特有的波形布局。例如，AXI 投影定义五通道分组和字段宽度，TileLink 投影定义自身
lane/field 布局；具体 profile 落地时在相应 family 包生成 WaveJSON/DOT IR，再交给通用 publisher。

### 场景报告

场景层选择 case、标题、HTML 排版和待发布视图。对应基础设施负责运行目录、`dot` 调用、文档资源发布
和 manifest 构造，使不同调用方共享同一存储合同。

## 两种存储生命周期

| 存储 | 生命周期 | 更新方式 | 入口 |
|---|---|---:|---|
| run artifacts | 一次运行的 sealed 快照 | finalize 后关闭 store API 写入 | `RunArtifactStore`，目录由调用方选择 |
| maintained docs/assets | 被维护的发布树 | 由具名发布动作替换 | `DocumentationStore` 或等价发布脚本 |

调用方式决定存储生命周期。普通交互运行可以使用 `out/<subject>/<run-id>/`、临时目录或用户指定的
workspace；测试优先使用临时目录。`docs/` 和 `showcase/generated/` 保存经过选择、随版本阅读的内容。
发布动作从已经 finalize 的 run 或确定性 source IR 中选择内容，保存生成参数和来源，再由
`DocumentationStore` 或专用脚本替换其拥有的子树。

当前 provenance 中的“来源”表示具名生成入口、命令、模型版本、参数和解释边界，用来回答资源怎样重建；它
与 release/tag、仓库版本共同定位历史输入。在同一 checkout 和声明工具链下，具名脚本重建语义等价的结果；
时间戳、无语义顺序和 renderer 版本允许产生字节差异。签名或 content-addressed publication 进入需求后，
再为该用途增加可验证的 source digest。

宣传 Demo 可以把“运行 + 发布”封装成一个具名命令，因为用户调用该命令的目的就是重建公开资源。这个例外
适用于该具名发布入口。普通测试仍写临时目录；生成脚本先在 staging 中完成全部渲染，成功后再原子发布。

## Manifest v4

`manifest.json` 使用 `protocol-model.run/v4`，包含：

- `subject` 和 `run_id`；
- 顶层 verdict、cases、state 与 metadata；
- 通用 `protocols` 记录，可同时描述 interface、transport 和 system scope；
- 每个 artifact 的 kind、media type、case 和 source 标记。

manifest 直接保存 `ProtocolRecord`；`RunBundle.write_constraints()` 生成的 `constraints.json/.md` 作为
artifact 进入清单。Python 类型路径和运行时对象保持在进程内。point-to-point 场景提升为
`SystemProtocol` 后，可以同时记录 system protocol 与实际使用的 interface protocols。

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

路径合同接受安全的 POSIX 相对路径，case 使用单个路径段，artifact 位于本次 run root 内。每个路径注册一次；
finalize 封闭 store 的注册与写入 API，使该 store 实例的报告索引保持稳定。调用方若需要文件系统级只读，
再为 run root 配置相应权限或内容寻址策略。
