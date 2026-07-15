# v0.1 方法迁移收口审计

v0.1 实现曾作为方法样本参与 v0.2 架构重建。完成本轮审计后，旧 Python 包已不再承担回归、兼容或
文档职责；需要考察历史实现时使用版本控制记录。本文件只记录语义取舍，避免旧目录继续成为隐含 API。

## 已吸收的方法

| 旧方法形状 | 当前落点 | 调整 |
|---|---|---|
| canonical event、value domain、event space | `semantics.event`、`link.EventSchema` | payload 不可变；schema 同时服务解释与构造 |
| state/action/step/emission/fault | `semantics.component` | fault 增加明确 scope 和 location |
| 每条 link 独立 session | `link.LinkSession` | schema、monitor、因果边和原子 batch 统一提交 |
| ready-valid stall 与 reset epoch | `observation` | 以 `AtomicFrame` 保留采样同时性，不建立独立“ready-valid 协议包” |
| quiet/stable/tied | `patterns.quiet` | canonical event 禁用、观察值约束和显示隐藏拆成三层 |
| keyed exact-count obligation | `patterns.CardinalityMonitor` | 支持同 ID FIFO、跨 ID 交织和 causal predecessor |
| descriptor/data correlation | `BurstAssembler`、`FifoJoin`、`CompletionLedger` | AW/W/B 不再依赖单体相关状态机 |
| 严格因果偏序 | `semantics.CausalGraph` | 保留 reachability、concurrency、ancestors 和拓扑序查询 |
| source/sink/function responder | 当前同步 `VirtualDutModel` | 输入和 emission 显式携带 port；后续重构为 opaque/constructed backend 与通用行为算子 |
| link runtime 与局部/全局索引 | `SystemSession` | 自动路由并保存逐跳 provenance |
| artifact、manifest、renderer、publisher | `artifacts`、`visualization` | 运行目录可配置；长期文档和 showcase 资源需要显式发布 |

## 不按旧实现迁移

| 旧内容 | 当前决定 |
|---|---|
| APB3/APB4 包与 `ClockedTwoPhaseTransfer` | 旧实现退休。当前 APB3/APB4/APB5 已从 `AtomicFrame + SemanticComponent + LinkProtocol` 重建两阶段观察，没有恢复旧 `ProtocolSpec` |
| 独立 ready-valid 协议与 Project | 握手观察方法已进入 `observation`；具体数据通道由使用它的 LinkProtocol 定义 |
| `ProtocolInstance`、`ProtocolDerivation` | 分别由不可变 LinkProtocol、profile、ProtocolLink 和 SystemProtocol 表达 |
| Project lifecycle、CLI、HTML gallery | 属于旧实验组织方式，不进入新语义 API |
| `can_cooccur()` 的排列检查 | 不再用交换性近似同时采样；`AtomicFrame` 和协议本地 lowering 明确原子边界 |
| 字符串 VirtualDut contract/capability | 描述文字不驱动执行；后续 contract 需要 executable property |
| 旧 AXI signal session | 新 `Axi4ObservationSession` 已覆盖 canonical ready-valid frame；raw RTL 字段 adapter 另行设计 |

## 提取后仍待实现的需求

以下内容有价值，但旧代码与当前对象模型耦合较深，因此只保留需求，不保留实现：

- **AXI 波形投影**：从新 `AtomicFrame` 或 canonical trace 生成 WaveJSON，展示 VALID/READY/FIRE、
  ID、payload 和 reset；`LaneDisplayPolicy` 只影响显示，不作为 quiet 证据。
- **AXI read bridge**：VirtualDut 维护有限 downstream ID 池、upstream/downstream ID 映射、剩余
  R beats 和 RLAST 一致性；容量耗尽应形成 blocked/resource 状态，而不是旧式 Project fault 流程。
- **scenario catalog**：保留同 ID ordering、跨 ID interleave、AW/W FIFO join、同帧可见性、stall、
  reset epoch、narrow/unaligned 和 exclusive 的语义类别；新测试围绕单项能力打通一条可以运行的小型完整路径，
  不复制旧 case gallery。

旧包删除后，迁移判断以本文件、当前代码和规范 requirement catalog 为准。历史代码只在确有审计需要时
从版本控制读取，不重新接入默认运行路径。
