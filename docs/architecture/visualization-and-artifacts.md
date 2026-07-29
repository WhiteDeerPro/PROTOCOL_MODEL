# 可视化视图与 Artifact 管理

可视化用于把模型中的结构、运行证据和解释投影成适合人阅读的视图；artifact 管理负责保存这些投影、
渲染结果、报告及其来源。两者协作，但回答不同问题：前者决定“这张图表达什么”，后者回答“这个文件从哪里来、
怎样重建、属于哪次运行”。

本页定义视图分类和管理边界。运行目录、写入安全和 manifest 的具体规则见
[运行产物、可视化与文档发布架构](run-output-management.md)。

## 1. 先按所表达的事实分类

DOT、WaveJSON、SVG 和 HTML 提供表示或渲染格式；view kind 定义读者看到的语义。相同的 DOT 可以表达
topology、因果关系或消息序列，因此每个 artifact 都应标记具体 view kind。当前工程中的图和报告归入以下
六类。

| 视图族 | 回答的问题 | 常见投影 | 适合的表示/渲染 |
|---|---|---|---|
| 静态结构 | 有哪些 module、port、attachment 和 connection？ | system topology、总线长条视图、VirtualDut 展开图 | typed structure view → DOT → SVG |
| 信号时序 | 每个 pin/frame 在各时钟周期是什么值？ | ready/valid、reset、AXI 五通道波形 | WaveJSON → WaveDrom |
| 语义时间轨 | operation、event、队列占用在模型步骤或时间戳上怎样变化？ | event waveform、execution-step view、frequency/occupancy view | lane view → WaveJSON，规模增大后可投影到 trace viewer |
| 交互与事务时空 | 哪些参与者依次交换了什么；一次事务跨过哪些阶段？ | MSC、message sequence、transaction path、transaction time-space | sequence/interval view → DOT、Mermaid 或专用 SVG |
| 因果、状态与分析 | 一个结果由什么触发；状态怎样迁移；谁在等待谁？ | causal DAG、lineage、coherence state、wait-for/deadlock graph | typed graph/state view → DOT → SVG |
| 报告与索引 | 本次运行覆盖了什么、结论是什么、文件如何追溯？ | result、constraint、coverage、manifest、provenance、gallery | JSON/Markdown/HTML/table |

最后一类属于文本/数据 artifact。宣传用 overview、architecture explanation 和 decision view 可复用结构图或
分析图的投影模型，同时标记为解释性材料，并继续引用原有协议语义。

### 容易混淆的边界

- **拓扑图与 VirtualDut 展开图**都属于结构视图，但缩放层级不同。前者把 module 当作节点，显示接口连接；
  后者打开一个 module，显示 attachment、FIFO、transform、route/owner 等内部实现构造。一个页面可以从前者链接
  到后者，但不宜默认把整个网络全部展开在一张图中。
- **信号波形与事件波形**都可以由 WaveDrom 绘制，但横轴含义不同。信号波形通常以 clock tick/cycle 为基准；
  事件波形可能使用 timestamp、model step 或 event index。图例必须显式写出时间基准，使读者能够区分
  model event 与 RTL 周期。
- **MSC 与因果图**都包含箭头。MSC 主要表达参与者之间的消息顺序；因果图表达 partial order 和派生关系，
  页面纵向位置用于布局，精确时序来自明确的时间坐标。
- **事务时空图与 MSC**共享 participant/message 引用，但前者还可以显示 operation lifetime、等待区间、资源占用
  和 split/fold。简单交互使用 MSC 即可，只有生命周期本身是验证对象时才展开时空视图。

## 2. 一张图需要的正交描述

当前 `ViewDescriptor` 用正交字段表达视图类型、作用域和证据来源：

| 字段 | 示例 | 作用 |
|---|---|---|
| `view_kind` | `topology`、`signal_timing`、`transaction_sequence`、`causal_graph` | 图在语义上表达什么 |
| `scope` | `interface`、`transport_link`、`virtual_dut`、`system`、`scenario` | 图覆盖的判定或展示范围 |
| `evidence_basis` | `declared`、`resolved`、`observed` | 内容来自声明、闭合结果还是运行观察 |
| `projection_intent` | `direct`、`derived`、`explanatory` | 图是直接呈现事实、分析派生结果还是用于解释设计 |
| `time_basis` | `none`、`clock_tick`、`timestamp`、`model_step`、`event_index`、`causal_rank` | 横轴或排序的真实含义 |
| `source_schema` | `protocol-model.topology/v1` | 投影数据的可演进格式 |
| `detail` | `overview`、`standard`、`diagnostic` | 选择显示密度；ViewIR 继续保存完整事实 |

这些字段互不替代。例如 `system + observed + derived + event_index + transaction_sequence` 描述一张从系统运行
派生的事务序列；`virtual_dut + declared + direct + none + virtual_dut_structure` 描述一个尚未执行的设备构造展开图。
renderer 由 publishing composition 选择，source 与 rendered artifact 分别注册；provenance 记录生成入口和
声明边界，并可按 publisher 保存参数、工具和 source/render 信息。更换 renderer 时，`ViewDescriptor` 的语义
字段保持稳定。

## 3. 数据链

```text
authoritative model / resolved plan / run trace
                    │
                    ▼
              typed ViewIR
      structure / timing / sequence / causal
                    │ serialize
                    ▼
         source artifact (DOT/WaveJSON/...)
                    │ render
                    ▼
             SVG / HTML / PNG
                    │ register
                    ▼
       manifest + report/gallery projection
```

每一步降低一种表示，并保持模型为上游权威：

1. projector 读取协议、VirtualDut、SystemProtocol 或 trace，产生 typed ViewIR；
2. serializer 产生可检查、可版本化的 DOT、WaveJSON 等 source artifact；
3. renderer 只负责排版与格式转换；
4. artifact store 分别保存 source、rendered 文件及其 kind、path、media type、case 和 source 标记；
5. report/gallery 从 manifest 选取材料，沿用上游 verdict 与 evidence。

source artifact 与 rendered artifact 都应保留。SVG 适合直接阅读，DOT/WaveJSON 则保留可重建性，也便于判断差异
来自模型、投影还是渲染工具。

## 4. 源码职责

目标代码依赖关系是：

```text
protocol / VirtualDut / system / trace
                 │
                 ▼
          visualization
    ViewIR + projector + serializer + renderer
                 ▲
                 │
showcase / publishing composition root
                 │
                 ▼
             artifacts
        record + store + manifest inventory

showcase / publishing 拥有组合生命周期与 provenance 内容
```

- `protocol_model.visualization` 拥有视图模型和投影规则；运行目录和发布目录由组合入口选择。
- `protocol_model.artifacts` 使用协议中立 record，拥有文件持久化、写入生命周期和 manifest inventory。
- showcase/publishing 同时依赖二者，是组合入口：它决定为一个场景生成哪些视图、把哪些结果注册进运行目录，
  如何形成导航和宣传页面，并选择 provenance 中的生成参数、工具和 source/render 关系。

当前实现已经具备 DOT/WaveJSON 渲染、运行目录、manifest 和显式发布。system topology、bus strip 和
VirtualDut structure 共享 `overview / standard / diagnostic` 三档显示密度：默认 standard 只显示语义标签和主要
路径，diagnostic 才加入实现类型、完整 connection ID、回程及控制流。投影数据仍保留完整事实，因此切换显示档位
保持同一模型与证据来源。

N×M address interconnect 已有第一条 typed projection：它从显式 `AddressRouterContract` 或 constructed backend 的
`AddressRouterBoundaryProjection` 读取 ingress、egress 和 route window；传入 elaborated system 时再附加 resolved
receiver/claim。生成的 interface map 在两侧显示真实 port/role，并保留 `dut:`、`port:`、`connection:`、`route:`
引用。中央 rectangle 表示一个多端口 VirtualDut 的边界投影；物理共享总线、crosspoint 数量和内部并行通道
需要独立结构证据。

`TransactionTimeSpaceView` 也已提供 typed message/state/causal IR、共同 descriptor、JSON source 以及
time-space/causal DOT 和 WaveJSON source serializer。当前迁移边界是：`AddressInterconnectView` 与
`TransactionTimeSpaceView` 使用共同 `ViewDescriptor`；`DutStructureView` 已有 typed IR，普通 topology、
trace 和 bus strip 仍直接生成 DOT；`VisualizationPublisher` 同时接触 renderer 与 `RunArtifactStore`。

## 5. 工具选择依据

- WaveDrom 的 WaveJSON 本来就是数字时序图描述，wave lane 的字符按时间 period 展开，适合 pin/cycle 和小型
  lane 视图；事件视图使用它时应补充 `time_basis`。
- Graphviz `dot` 面向有方向的层次图，并尝试减少交叉和边长，适合 topology、因果关系和设备展开的默认自动
  排版。特别重要的宣传图可以在稳定 source 上少量人工调参，而不把人工坐标变成全工程义务。
- Sequence diagram/MSC 面向 participant 之间按顺序发生的消息，适合把事务传播从结构图中分离出来。
- 当 trace 大到静态 SVG 难以浏览时，可参考 Perfetto 一类 track/slice/flow 模型提供缩放、筛选和跨轨关联；
  这是 renderer 的后续扩展方向，协议核心继续提供稳定 trace/view input。
- provenance 可以借鉴 W3C PROV 的 entity/activity/agent 与 derivation 思路。当前通用 manifest 记录
  artifact inventory；showcase 等组合入口另行发布 `provenance.json`，共同保存生成入口和声明边界，参数、
  工具版本与 source/render 字段由各 publisher 选择。统一 provenance schema、renderer inventory 与 manifest
  linkage 属于后续扩展。
- 同一模型按不同缩放层级提供 topology 与 VirtualDut 展开图，符合 C4 一类“按受众和问题选择图”的做法；
  图应当自带标题、scope/time basis 和必要图例。

参考：[WaveDrom tutorial](https://wavedrom.com/tutorial.html)、[Graphviz dot](https://graphviz.org/docs/layouts/dot/)、
[Mermaid sequence diagram](https://mermaid.js.org/syntax/sequenceDiagram)、
[Perfetto track events](https://perfetto.dev/docs/instrumentation/track-events)、
[W3C PROV overview](https://www.w3.org/TR/prov-overview/)、[C4 diagrams](https://c4model.com/diagrams)。

## 6. 当前迁移与下一步

已经进入源码：

1. `ViewKind`、`ViewScope`、`EvidenceBasis`、`ProjectionIntent`、`TimeBasis` 与 `ViewDescriptor`；
2. address interconnect 与 transaction time-space 的 typed IR、descriptor 和 source schema；
3. VirtualDut structure typed IR；
4. DOT/WaveJSON source serializer、Graphviz/WaveDrom renderer、source/rendered artifact 注册、run
   manifest 与具名发布入口。

下一步沿现有对象补齐：

1. 为 `DutStructureView`、普通 system topology、trace 和 bus strip 接入共同 descriptor；
2. 在 `ArtifactRecord`/manifest 中持久化 descriptor 与 source→rendered derivation；
3. 定义通用 provenance schema 与 renderer inventory，并把组合入口生成的 provenance 与 manifest 建立显式
   关联；
4. 让报告和 gallery 只读 manifest 自动生成导航；
5. 在第二个 composition consumer 出现后评估 `VisualizationPublisher` 的独立组合包；
6. 真实大规模 trace 场景出现后，再评估交互式 viewer。

迁移期间继续支持现有 DOT/WaveJSON 与 SVG，优先统一 view 含义，再按使用需要调整文件格式。
