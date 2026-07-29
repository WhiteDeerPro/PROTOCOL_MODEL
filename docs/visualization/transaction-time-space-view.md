# 事务时空图：从协议消息到可追溯运行视图

事务时空图沿时间方向排列一次通信经过的消息，并沿空间方向排列参与通信的节点。它适合回答三个问题：

1. 一次 operation 经过了哪些参与者；
2. 每条 request、snoop、data 和 completion 消息何时出现；
3. operation 在各参与者处何时分配、等待、改变状态并最终释放。

本项目将这种协议无关的投影称为 **transaction time-space view**。它借鉴 CHI 的 Time-Space diagram，
同时允许 AXI、AHB、APB、TileLink 和 bridge trace 使用同一套视图 IR。图只读取已经形成的语义证据；
协议判定、operation correlation 和状态更新仍由 observer、monitor、VirtualDut backend 与 system runtime
负责。

## 1. CHI Time-Space diagram 表达什么

Arm 在《AMBA CHI Architecture Specification》Issue H 中为 Time-Space diagram 定义了专用约定：

- protocol node 沿水平方向排列，形成“空间”轴；
- 时间从上向下推进；
- 消息箭头连接发送和接收节点；
- 节点上的细长阴影区间表示事务从 allocation 到 deallocation 的生命周期；
- 请求到达、等待其他事件、解除等待等状态使用时间轴上的标记表示；
- 初始 cache state 放在节点上方，`I->UC` 一类标记表示事件发生时的 cache state transition。

CHI 规范随后还定义了 transaction flow diagram 的补充画法：颜色区分 REQ、RSP、SNP、DAT channel，
粗箭头表示可能需要多个 packet 的消息，`alt` 和 `opt` 分组表示替代或可选 flow。实际 CHI 协议流程图
通常同时使用这两组约定。

```text
                     space ─────────────────────────►
                 RN-F              HN-F              SN-F
time │             │                 │                 │
     │             ├── ReadShared ──►│                 │
     │             │                 ├── ReadNoSnp ───►│
     │             │◀──────────── CompData ────────────┤
     │             ├── CompAck ─────►│                 │
     ▼             │ I -> UC         │                 │
```

图中的竖线可按序列图术语理解为 lifeline，但 CHI Time-Space diagram 的信息量更大：它同时承载
message flow、transaction lifetime、forward-progress blocking 和 coherence state。只有消息箭头的图用于
说明 flow；allocation、blocking 和 cache state 各自由对应的 lifecycle、resource 与 coherence evidence 补充。

官方约定见 [AMBA CHI Architecture Specification Issue H，Figure 2 和 Figure 3](https://documentation-service.arm.com/static/68d13eb5bd7cab51328bee7a)。

## 2. Sequence diagram 与 MSC

通用 **sequence diagram** 使用竖直 lifeline 表示参与者，使用横向或斜向箭头表示交互，阅读方向通常从上
到下。它可以描述同步调用、异步消息、返回以及 `alt`、`opt`、`loop` 等组合片段。工程资料中的“两条竖线
加若干横向箭头”通常属于这一图类；参与者数量并不限定为两个。

**Message Sequence Chart（MSC）** 是 ITU-T Z.120 定义的通信 trace 语言，拥有图形和文本语法以及明确的
trace 解释。它可用于接口说明、需求、仿真、测试和文档。本项目当前输出自有的
`transaction time-space view` 或 `sequence view` IR。覆盖 Z.120 的实例、消息、条件、timer 和组合规则后，
可以增加符合该标准的 MSC exporter。

CHI Time-Space diagram 可以视为面向 CHI protocol flow 的扩展序列视图。其 allocation、blocked interval
和 cache state transition 均来自 CHI 事务语义，普通 sequence diagram 的几何位置只承担布局作用。

MSC 的正式定义见 [ITU-T Z.120](https://www.itu.int/ITU-T/recommendations/rec.aspx?rec=z.120)。Arm 的
[AMBA Viz 介绍](https://developer.arm.com/community/arm-community-blogs/b/soc-design-and-simulation-blog/posts/introduction-to-amba-viz)
也把从 CHI 波形提取的交互视图称为 interactive sequence diagram。

## 3. 五种视图的证据边界

这些视图可以由同一次运行生成，但它们投影的事实不同。

| 视图 | 主要对象 | 时间表达 | 适合回答 | 还需配合的证据 |
|---|---|---|---|---|
| topology | VirtualDut、port、link、boundary | 无 | 谁与谁相连，端口承担什么 role | 运行 trace 提供实际路径、消息顺序和等待原因 |
| waveform | clock、reset、pin、lane、field | 精确到采样 tick/cycle | VALID/READY、电平和 payload 在每个采样点的值 | operation correlation 连接多 channel 与跨 connection completion |
| transaction time-space | participant、message、operation span、state change | timestamp、tick 或明确标注的逻辑顺序 | 一次 operation 怎样穿过节点，在哪里等待和完成 | waveform 提供 pin 细节；causal edge 解释上下排列的依赖含义 |
| causal graph | event 与 typed causal edge | 偏序；可用拓扑序排版 | 哪个事件依赖哪个事件，哪些事件可并发 | frame/timestamp 提供物理间隔，topology 提供完整结构 |
| coherence/state view | line、owner、sharer、permission、state transition | 事件前后或状态 epoch | 一条 cache line 的权限和所有权怎样变化 | time-space 与 waveform 提供消息路径和 pin 握手 |

一个 AXI write 可以在 waveform 中分散为 AW、若干 W 和 B transfer；time-space view 将它们归入同一
operation；causal graph 再说明 B completion 依赖哪些 accepted transfer。三张图共享 event reference，
各自保留原本的观察粒度。

### 3.1 时间轴基础

每张事务时空图声明 `time_basis`。当前 `TransactionTimeSpaceView` v1 接受：

| `time_basis` | 含义 | 使用条件 |
|---|---|---|
| `event_index` | `SystemTrace` 接受事件的记录顺序 | 当前构造系统路径的可靠回退方式 |
| `model_step` | 调用方声明的一次语义执行步骤 | 同一步可包含多个 message/state event；显式 causal edge 可位于同一步 |

共享 `TimeBasis` 词表还预留 `clock_tick`、`timestamp` 和 `causal_rank`。它们分别以 `AtomicFrame` anchor、
跨 domain 统一时间和 causal DAG 分层为进入条件，待 time-space view 接入对应 typed projection 后启用。

`event_index` 与 `model_step` 都是逻辑顺序，图例直接标明所选基础。跨时钟对齐由 trace source 提供。

## 4. 本项目视图的数据输入

事务时空投影从稳定语义对象和显式 projection 读取数据：

| 输入 | 提供的事实 |
|---|---|
| elaborated system/topology record | VirtualDut、port、link、role、boundary，以及 lifeline 的可选分组 |
| `AtomicFrame` 与 observer evidence | clock、tick、同一采样边界、offer/stall/accepted transfer |
| `CanonicalEvent` | event kind、key、payload、source、clock、timestamp、sequence、trace index |
| `SystemEvent` | 全局 event index、完整 `InterfaceConnection` 名称、event kind、source port、destination port 与 `CanonicalEvent` |
| `SystemTrace.causal_edges` | 已由 monitor/backend 声明的 event 依赖 |
| operation lifecycle projection | operation identity、parent/child lineage、phase、allocation、completion 和 result folding |
| resource/progress projection | resource lease、blocked reason、unblock event、deallocation |
| coherence projection | line identity、participant、previous state、next state、owner/sharer delta |
| run manifest/artifact records | case、源图、SVG、waveform 与 causal graph 的相对路径和 provenance |

elaborated system、`AtomicFrame`、`CanonicalEvent`、`SystemEvent` 和 `SystemTrace.causal_edges` 已经存在于
当前 runtime。`SystemEvent.connection` 标识完整接口连接；协议 channel 来自 event kind/payload 或具名
projection。offer/stall 的独立 evidence 仍需补充。operation lifecycle、progress 与 coherence 需要由
translation executor、协议 monitor、VirtualDut backend 或后续 system monitor 公开 typed projection。
可视化层只读取这些显式 projection 与稳定 record。

### 4.1 当前 v1 与扩展字段

```text
TransactionTimeSpaceView
  name
  time_basis
  scope / evidence_basis
  lifelines[]
  messages[]
  state_changes[]
  causal_edges[]

TimeSpaceMessage
  event_ref
  operation_ref
  source / destination
  time
  label / lane / channel
  display_fields
  observation_point
```

`to_dict()` 增加 schema 与 `ViewDescriptor`，形成可保存的 JSON source。下一版 typed extension 再加入
`operation_spans`、`blocked_intervals`、waveform/causal anchors 与更细 provenance；进入条件是对应
lifecycle/resource projection 已有稳定来源。

IR 保存语义引用和布局所需的最小字段。颜色、字体、换行和泳道宽度属于 renderer policy，runtime
对象保持上游权威。JSON 源文件与 SVG 一起保存，便于复查消息为何出现在图中。

## 5. Lifeline 怎样选择

同一份 trace 可以按不同观察目的投影 lifeline：

- **VirtualDut lifeline**：适合 bridge、memory、crossbar 等 module 级说明；
- **port lifeline**：适合检查同一 module 上多个端口之间的 route 和 transform；
- **protocol participant lifeline**：适合 CHI RN/HN/SN、TileLink progress domain 等协议角色；
- **boundary lifeline**：适合把系统外部 traffic 与内部运行放在同一视图；
- **collapsed subsystem lifeline**：适合隐藏已经封装的内部网络。

默认的系统视图先按 VirtualDut 分组，再在需要时展开 port。未来的 `ProgressDomain` 可以成为独立
lifeline，但它与 VirtualDut 的映射必须显式提供：一个 module 可能含多个 progress domains，一个 domain
也可能概括多个内部 modules。

一张图可以使用层级标签，例如 `bridge0 / axi_in`；同一层的 lifeline 必须共享清楚的抽象尺度。把 module、
port 和 coherence shadow ledger 并排时，需要用分组框或不同 header 类型说明各自身份。

## 6. Operation correlation

消息到 operation 的关联是 time-space view 的核心输入。关联由协议 monitor 或 translation lifecycle 产生，
renderer 只消费结果。

### 6.1 稳定身份

建议为每个运行中的 operation 分配 `operation_ref`，并保存：

- 创建 operation 的 event；
- 当前 phase；
- request、data、snoop、response 和 final acknowledgment 的 event refs；
- parent operation 与 child operations；
- fanout child index；
- completion/result fold event；
- allocation 和 deallocation 所在 participant。

协议字段作为局部 correlation evidence 保存，lifecycle 再分配跨协议、跨复用周期稳定的
`operation_ref`：

- AXI ID 会重复使用，read 与 write 拥有不同上下文，AW/W/B 还需要 attachment 的 join state；
- AHB 和 APB 依赖当前 transfer/phase context；
- TileLink `source`、`sink` 的有效范围与 message phase 有关；
- CHI 的 `SrcID`、`TgtID`、`TxnID`、`DBID` 和 `HomeNID` 共同决定局部关联关系；
- bridge 两侧的协议 ID 可以完全不同。

bridge 将一个 burst 展开为多个 access 时，视图保存一条 parent-child lineage：AXI parent operation 可以折叠
显示，也可以展开为多个 AHB/APB child operations。跨协议数值 ID 恰好相等时，图仍使用 lifecycle 中声明的
lineage。

### 6.2 关联置信度

每条 correlation 可以标明来源：

- `declared`：executor/backend 创建的 token 或 owner record；
- `monitored`：协议 monitor 根据完整协议上下文判定；
- `observed`：外部 transaction adapter 已经提供 operation identity；
- `heuristic`：仅供探索的推测关联。

宣传和正式验证视图默认只展示前三类。若允许 heuristic，图例和源 IR 都应明确标记，且它不进入 verdict
证据。

## 7. 生命周期、阻塞和状态变化

CHI 风格的 transaction lifetime 需要三个事件：allocation、可选的中间状态、deallocation。项目中的
operation span 应包含 participant、operation ref、开始和结束依据。trace 在结束时仍有 pending resource 时，
span 保持 open，并标为 pending；渲染器不补造一个结束点。

blocked interval 还需要 typed reason，例如：

```text
waiting_for_child_completion(child-3)
waiting_for_capacity(apb_slots)
waiting_for_owner(axi_write_id=2)
waiting_for_higher_priority(channel=D)
```

一段空白、`READY=0` 或 FIFO 非空只能说明观察到的 transport 状态。具体等待原因由持有资源和等待条件的
owner 声明。unblock marker 引用解除等待的 event，从而也能跳转到 causal graph。

cache state transition 使用 `line_ref + participant + previous + next + event_ref` 表示。协议消息的 opcode
可以触发 monitor 检查，但 renderer 不根据 `ReadShared`、`Probe` 等名字自行推导 `I->SC`。存在 system
coherence ledger 时，图还可以选择显示 owner/sharer delta；该 ledger 的 reference/shadow 身份应在图例中
说明。

## 8. 与 waveform、causal graph 和 topology 互链

所有视图共享稳定引用：

```text
frame_ref      = <clock-domain, tick>
event_ref      = <run, case, global-event-index>
operation_ref  = <run, case, operation-sequence>
lifeline_ref   = <system-object, optional-port-or-domain>
```

这些标识在 view source 内保持稳定；当前 manifest 记录 artifact 的相对路径和 case。后续 report/navigation
层再保存 ref→artifact/anchor 的解析关系。

### 8.1 跳转关系

下表定义跨视图导航的目标合同。v1 source 已保留 event/operation/lifeline refs；实际双向链接随
report/HTML navigation 接入。

| 起点 | 目标 | 行为 |
|---|---|---|
| time-space message | waveform | 定位到对应 clock/tick，并展开该协议 channel 的 lane/field |
| time-space message | causal graph | 高亮同一 event node、直接 predecessors 和 dependents |
| operation span | causal graph | 高亮该 operation 全部 events 及 parent/child lineage |
| waveform accepted transfer | time-space | 定位到 lowering 后的 `CanonicalEvent` 和所属 operation |
| causal event | time-space | 定位到消息箭头或本地 state marker |
| topology link/port | time-space | 按 link、VirtualDut 或 port 过滤 lifelines 与消息 |
| time-space state change | coherence view | 定位到相同 line、epoch 和 transition evidence |

静态 SVG 可以通过元素 `id` 和 `<a href>` 提供页内或文件间链接；HTML 报告可以在统一 data model 上完成
双向筛选。源 JSON 始终保存引用，为当前静态 renderer 和后续交互 renderer 提供共同输入。

### 8.2 Artifact 布局

沿用当前 run artifact 生命周期时，一次 case 可以生成：

```text
<run-root>/
├── manifest.json
├── cases/<case>/
│   ├── transaction-time-space.svg
│   ├── waveform.svg
│   └── causal.svg
└── sources/cases/<case>/
    ├── transaction-time-space.json
    ├── waveform.json
    └── causal.dot
```

`transaction-time-space.json` 保存 schema、`ViewDescriptor`、name、lifelines、messages、state changes 和
causal edges。场景特有的 projection 参数、lifeline policy 与 provenance 由组合入口另存为 run
metadata/provenance artifact；统一 schema 属于后续扩展。具名 publisher 注册 source 与 rendered artifact；
普通协议运行的输出目录由调用方选择。

## 9. 表现层约定

- 时间从上向下，空间从左向右；改变方向时在坐标轴和图例中明确说明。
- message 颜色表示 channel 或 message class，并始终附图例；monitor verdict 与 evidence 表达 legality。
- accepted transfer 使用实线箭头；offer、stall 或 retry 使用本地 marker 或明确的虚线类型。
- 同一个 operation 使用稳定的描边或标签；协议 channel 颜色与 operation 颜色分开编码。
- burst 默认允许折叠，标签显示 beat 数量；展开模式保留每个 accepted beat 的 event ref。
- reset 以 epoch 分隔带表示，并链接到 reset observation；reset 期间隐藏 lane 只属于显示 policy。
- 长 trace 按 operation、时间窗口或 subsystem 分页，分页边界保留 continuation marker。
- 缺少 allocation、blocked reason 或 state transition evidence 时省略对应符号，并在图例列出当前证据覆盖。

这些约定让版式保持在现有 evidence coverage 内，并为缺失证据提供明确标记。

## 10. 当前实现与实施顺序

当前通用可视化已经具备：

- `TransactionTimeSpaceView` v1，以及 typed lifeline、message、state change 和 caller-supplied causal edge；
- `event_index` 与 `model_step` 两种时间基础、稳定 event/operation refs 和可序列化 JSON source IR；
- `transaction_time_space_dot()`、`transaction_causal_dot()` 与
  `transaction_semantic_wavejson()` 三种只读 source serializer；
- `project_chi_transaction_flow()`：从一次 live CHI Issue H runtime 投影 operation correlation、endpoint
  acceptance、状态提交和显式因果关系；
- CHI flow gallery 的逐案例 topology、time-space、causal 与 semantic timeline 发布；
- `system_topology_dot()`、`system_trace_dot()`、`RunArtifactStore`、manifest 和 source/rendered artifact
  注册。

下一阶段按证据来源推进：

1. 从通用 `SystemTrace` 生成 message-only view，并明确 VirtualDut/port lifeline policy；
2. 接入 observer 的 frame/tick anchor，实现 waveform 双向定位；
3. 接入 translation lifecycle 的 bridge parent-child correlation；
4. 为 allocation/deallocation、pending 和 blocked interval 增加 typed IR，并接入 resource/progress
   projection；
5. 接入通用 coherence projection，显示 line state 与 owner/sharer delta；
6. 在 HTML 报告中增加 topology、time-space、waveform、causal 四视图联动。

现有 v1 覆盖显式 message、state change 和 causal evidence。operation span、blocked interval 与跨视图
交互以上述 typed projection 为进入条件。
