# 事务转译 V1 实施计划

[返回架构索引](README.md) · [Canonical bridge 架构](typed-transaction-translation.md) ·
[构造方法的跨领域启示](bridge-construction-insights.md) ·
[当前实现状态](implementation-status.md) · [实施路线](technical-route/08-roadmap.md)

本文记录 [Bridge 与类型化事务转译](typed-transaction-translation.md) 的当前落地范围。它是实施状态和接入
计划，不承担通用概念的首次解释。

## 1. 起点：已有行为与抽取压力

工程已经能够执行 0..N emission，也已有可工作的 AXI4→APB 转译。缺口不是“能否产生多个事件”，而是
split、route、attribute projection、schedule、owner 和 result aggregation 仍集中在协议对 backend 中。

| 当前机制 | 已提供的能力 | V1 抽取目标 |
|---|---|---|
| `SemanticStep` / `DutTransition.emissions` | 一次 transition 产生 0..N outputs | 保留为底层执行能力 |
| `Axi4AddressSpaceAttachment` | AW/W join、burst geometry、`AddressAccess[]`、response encode | 分离 AXI codec 与通用 burst stage |
| `AddressRoute.translate()` | `AddressAccess` 的 1→1 地址 remap | 纳入 typed leaf stage |
| AXI4→APB backend | parent FIFO、逐 beat APB、owner、result aggregation | 迁入通用 serial executor |
| AXI4-Lite→APB recipe + generic single-ingress fabric backend | single-access route 与 completion return | 复用相同 executor/leaf stages |
| `ResourceDecl` / `CardinalityToken` | 声明容量、检查 link completion 数量 | 增加 Vdut fanout ledger 与 concrete lease |

## 2. V1 的结构限制

V1 只接受：

```text
zero or more 1→1 prefix stages
    + zero or one 1→N expansion
    + zero or more 0/1 or 1→1 suffix stages
    + one ingress / one egress
    + strict serial child issue
```

这里的“线性”只限制 runtime translation shape，不把 plan 简化为仅有 source/target type 的列表。V1 仍需在
构造期检查 request/completion 双向能力、stage 顺序、逐笔适用条件、语义效果和 reset/failure policy。

限制的理由是：

- 当前 AXI4→APB 只需要一个 fanout 和一个 active APB child；
- 线性 plan 已能验证 codec/stage/executor 的职责边界；
- 多 fanout、width merge、reorder 和多出口会同时引入新的 correlation 结构，不适合作为首个抽取变量；
- 第二个 egress 能证明复用价值，比先实现通用图搜索更有信息量。

## 3. 第一版对象契约

T1 已经冻结为一组不依赖具体协议的类型，而不是用无类型字典描述 stage：

| 对象 | 已冻结的边界 |
|---|---|
| `OperationSignature` | `domain/name/version` 加一组 request/completion runtime types；V1 使用精确兼容，结构转换必须显式成为 stage |
| `DecodedOperation` | attachment 已经解码出的 operation，加不透明的 wire reply context |
| `ParentEnvelope` | executor token、operation、reply context 和 ingress binding；token 不复用协议 ID |
| `CapabilityProjection` | `requires/remove/provide`；request 正向传播、completion 反向传播 |
| `StageContract` | 双向 capability relation、`SemanticEffect`、适用规则、completion rule、保持义务和 provenance |
| `BridgeProfile` | source/target capabilities、ordering、允许的语义弱化、等价层级、unsupported/reset policy 与 provenance |
| `TranslationPlan` | prefix、至多一个 fanout、suffix、双向 closure、effects 和 construction provenance |
| `SerialExecutorProfile` | 独立于 semantic plan 的 parent capacity、egress binding 与 pool 命名 |
| `FanoutLedger` | parent→child obligation 的 issued/completed/inflight；不保存执行容量 |
| `CapacityPool/Lease` | 运行时有限资源的 owner 与借还；同一容量声明投影为 `ResourceDecl` |

当前 V1 compiler 真正执行的检查包括：精确 request/completion signature、双向 capability、stage 顺序、
fanout 的 split/aggregate 声明，以及 `weaken/drop` 的显式授权。它只接受 operation-effect equivalence、空的
ordering claim、reject unsupported policy、report-fault reset policy 和 sequential access mode；pin/cycle、
reset drain、隐式 default/drop 等尚无执行证据的承诺会在构造期被拒绝。`applicability_rule`、
`completion_rule` 和 completion evidence 的进一步闭合留到具体 address stage 与 codec 接入时完成。

Unary lowering 包含 `LoweredOne`、`LocalCompletion` 和 `Rejected`；fanout begin 对应
`Expanded(count, context, fold_state)`、`LocalCompletion` 或 `Rejected`。容量不足不由 stage 报告普通转换
失败。operation-level executor 沿用同步运行边界；pool 内部返回 typed `CapacityFailure`，executor fault
保留这份 detail，同时提供可读的 pool/usage/owner reason。typed
`ResourceDemand`/blocked state 留给非立即 emission 阶段。

Stage 不持有跨事务可变状态。ID map、owner、queue、cursor 和 result storage 由 executor state 持有，并有
明确的 owner、key、lifetime 与释放条件。`TranslationPlan` 带 compiler witness，不能绕过
`compile_translation_plan()` 直接制造；executor 在使用前重新核对 stage 的 name/signature/contract/
cardinality metadata。Python stage 内部行为是否无副作用仍由 stage 合同约束，因此定向测试也不把运行探针
存进 stage 自身。

### 3.1 尚待 attachment 外壳冻结的合同

公共 executor 故意不接收 `CanonicalEvent`。下一段 attachment-aware backend 需要把三份候选状态作为一次
事务提交：

```text
ingress decode candidate
    → executor candidate + operation emissions
    → egress/ingress encode candidates
    → 全部成功后一起 commit
```

任一 decode、stage 或 encode 失败时，attachment 与 executor 都保留调用前状态，且不发布部分 emission。
executor 会在同步调用内推进到“一个 child 已发行并等待 completion”或“所有工作完成且静止”；外层
`is_quiescent` 还必须同时检查两侧 attachment 的 partial transport state。这个外壳是 T4，不应通过给
`ProtocolAttachment` 增加一个覆盖 address、stream 和 coherent message 的万能 payload SPI 来实现。

## 4. 建议源码职责

```text
protocol_model/virtual_dut/
├── address/
│   └── burst.py                 # AddressBurst / AddressBurstResult
└── translation/
    ├── signature.py             # OperationSignature
    ├── envelope.py              # DecodedOperation、ParentEnvelope、reply context ownership
    ├── stage.py                 # unary/fanout stage、cardinality、lowering result
    ├── contract.py              # capability relation、SemanticEffect、applicability
    ├── lifecycle.py             # TokenRef、FanoutLedger、lineage
    ├── resources.py             # pool、lease、usage projection；demand 后续扩展
    ├── plan.py                  # 双向能力、stage 顺序和线性 plan 闭合检查
    └── engine.py                # operation-level 单 ingress/egress serial executor

protocol_model/integrations/
├── attachments/amba/...         # protocol event ↔ operation codec
└── recipes/amba/bridges/...     # audited presets / composition roots
```

`translation` 是 VirtualDut 的 constructed-backend 子包，不成为新的顶层架构层。Recipe 可以依赖两侧协议
attachment 和通用 executor；executor 不反向依赖 AMBA recipe。

## 5. 实施阶段

| 阶段 | 状态 | 实现内容 | 完成判据 |
|---|---|---|---|
| T1 | 已完成 | signature、envelope、profile/contract、unary/fanout stage、ledger、pool/lease、linear plan DTO | 合成 `Batch(3)→Item` 显示 1 parent、3 obligations、child peak=1；plan 定位 request/completion、capability 顺序和未授权 loss |
| T2 | 已完成 | operation-level `SerialTranslationExecutor` | parent FIFO、一个 child owner、lazy fanout、local completion、reverse lift/fold、lease usage 和错误原子回退均进入显式状态 |
| T3 | 待实施 | `AddressBurst` 与 `BurstToAccessStage` | AXI attachment 负责 AW/W join 并产出 reply context；通用 stage 负责 child geometry/fold |
| T4 | 待实施 | executable binding + attachment-aware backend/codec transaction | plan、executor profile、codec/ports 形成完整 provenance；event decode/encode 与 executor 候选状态共同提交，完整 quiescence 覆盖两侧 attachment |
| T5 | 待实施 | 重构 AXI4→APB | 外部 profile 保持；删除 pair backend 中重复的 split/schedule/correlate 核心 |
| T6 | 待实施 | 重构 AXI4-Lite→APB | 1→1 plan 与 AXI4 bridge 共用 executor 和 address leaf stages |
| T7 | 待实施 | 增加 AHB→APB 或 AXI4→AHB-SINGLE witness | 只替换 codec/preset，不增加新的协议对 backend |
| T8 | 待实施 | 接入 SystemProtocol construction | 报告 intent→codec→stage→policy→VirtualDut provenance 和 mismatch 原因 |

T1/T2 只使用新的合成定向测试。T5 选择当前新架构 bridge 的合法、route miss、capacity 与错误聚合
witness，不调用历史回归入口。

## 6. V1 验收条件

本节是完整 V1（直至至少第二种 egress/preset）的验收条件，不等同于 T1/T2 已经全部满足。

- 至少三种 bridge preset 共用一个 executor；
- `BurstToAccessStage` 可替换 APB egress 为 AHB SINGLE egress；
- AXI reply context 与 `AddressBurst` 分离；多个 parent 的 R/B 编码仍能回到各自 descriptor/ID；
- executor token 不复用 AXI ID；同 ID parent 按完整 operation 形成顺序 FIFO 完成；
- child descriptor lazy、write-result fold O(1)，同时明确 V1 read-result storage 为 O(N)；
- plan 构造能拒绝 signature 不闭合、第二个 fanout 和未声明的属性损失；
- plan report 能列出双向 capability closure、stage ordering、SemanticEffect 和所选 equivalence level；
- route miss 形成 local completion，不占用 egress lease；
- 容量 fault 能指出 pool、当前 usage、limit 和被拒绝的 owner；
- trace/projection 能区分 parent token、child obligation、lease peak 和累计发行数；
- AXI4→APB 当前公开 profile 的 completion 和容量边界保持可解释；
- recipe 不重新实现 stage/executor 已拥有的状态机；
- concrete executor state 能说明 owner、lifetime、release 和 reset/cancel 行为；wire completion 不抹掉内部
  completion origin。

## 7. V1 暂缓项

- 任意 stage DAG 和自动多跳搜索；
- nexus 图上的通用 fixed-point 协商与自动 stage pipeline synthesis；
- 多入口 arbitration、crossbar 和多 egress route；
- 多 child 并发、reorder 与 full AXI ID remap；
- AXI R 的逐 child 流式返回；
- 精确的每个 child result→对应 R event 因果边；V1 只要求 parent/child ownership 正确；
- width split/merge；
- exclusive、atomic、coherence 和 stream-to-memory；
- AHB native burst 重组；
- READY/backpressure 的 pin-level 投影；
- typed `ResourceDemand`、blocked/deferred transition 与自动恢复；
- CHI 等协议线上真实 Link Credit；
- 运行期 topology reconfiguration。

这些是当前实施范围，不是对协议能力的长期判断。V1 在第二个 egress 上证明接口稳定后，再依据真实
bridge/crossbar pressure 扩展。
