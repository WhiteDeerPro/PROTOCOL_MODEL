# 事务转译 V1 实施状态与后续

[返回架构索引](README.md) · [Canonical bridge 架构](typed-transaction-translation.md) ·
[构造方法的跨领域启示](bridge-construction-insights.md) ·
[当前实现状态](implementation-status.md) · [实施路线](technical-route/08-roadmap.md)

本文记录 [Bridge 与类型化事务转译](typed-transaction-translation.md) 的当前落地范围和接入计划。通用概念
由 canonical bridge 文档定义。

## 1. 当前抽取结果

V1 已把早期协议对实现中的 split、route、attribute projection、schedule、owner 和 result aggregation
抽到 operation form、typed stage、serial executor 与 attachment-aware backend。协议相关代码负责端口
event 编解码和 profile 选择；各协议对复用同一调度核心。

| 当前机制 | 已落地的职责 | 复用边界 |
|---|---|---|
| `SemanticStep` / `DutTransition.emissions` | 一次 transition 产生 0..N outputs | 底层执行能力 |
| `Axi4BurstTranslationAttachment` | AW/W join、burst geometry、reply context、R/B encode | AXI4 ingress codec |
| address route/shape/protection stages | route/remap、目标访问形状和 AMBA protection 转换 | 与协议对无关或以 family 参数化的 plan stage |
| `SerialTranslationExecutor` | parent FIFO、逐 child 调度、owner、result fold、capacity lease | single-access 与 burst fanout 共用 |
| `AddressOperationTranslationBridgeBackend` | 两侧 attachment 状态与 executor 候选状态的原子提交 | 所有当前 AMBA serial address bridge 共用 |
| `build_amba_serial_bridge_vdut()` | 按 ingress form 选择 single-access 或 AXI4 burst composition root | AXI4、AXI4-Lite、AHB、APB 的 4×4 family 构造矩阵 |

4×4 描述四种 address family 的 operation-shape 组合。当前具体 builder 包含 AXI4、AXI4-Lite、AHB-Lite、
AHB5、APB3、APB4 和 APB5；默认 32-bit profile 的 7×7 构造见证说明这些 variant 可以进入同一
composition root。定向 execution witness 列出已经验证的 sideband、性能性质和规范范围。

当前执行见证选择了能够施加不同架构压力的路径：AXI4→AHB-Lite、AXI4→APB4、
AXI4-Lite→AHB-Lite/APB4/AXI4、AHB-Lite→APB4，以及 AXI4-Lite→AHB-Lite→APB4 链。其余格子
目前主要证明 attachment/requester 可替换和 plan 可装配；需要某个方向承担更强承诺时，再补该 profile 的
定向运行与规范目录。

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

- 当前 AXI4 burst→address egress 只需要一个 fanout 和一个 active child；
- 线性 plan 已能验证 codec/stage/executor 的职责边界；
- 多 fanout、width merge、reorder 和多出口会同时引入新的 correlation 结构，因此留到线性 plan 稳定后推进；
- AXI4、AXI4-Lite、AHB、APB egress 已证明 codec 可替换性；通用图搜索列入后续阶段。

## 3. 第一版对象契约

V1 已经冻结为一组协议中立的 typed contracts：

| 对象 | 已冻结的边界 |
|---|---|
| `OperationSignature` | `domain/name/version` 加一组 request/completion runtime types；V1 使用精确兼容，结构转换必须显式成为 stage |
| `DecodedOperation` | attachment 已经解码出的 operation，加不透明的 wire reply context |
| `ParentEnvelope` | executor token、operation、reply context 和 ingress binding；token 不复用协议 ID |
| `CapabilityProjection` | `requires/remove/provide`；request 正向传播、completion 反向传播 |
| `StageContract` | 双向 capability relation、`SemanticEffect`、适用规则、completion rule、保持义务和 provenance |
| `TranslationProfile` | source/target capabilities、ordering、允许的语义弱化、等价层级、unsupported/reset policy 与 provenance |
| `TranslationPlan` | prefix、至多一个 fanout、suffix、双向 closure、effects 和 construction provenance |
| `SerialExecutorProfile` | 独立于 semantic plan 的 parent capacity、egress binding 与 pool 命名 |
| `FanoutLedger` | parent→child obligation 的 issued/completed/inflight；不保存执行容量 |
| `CapacityPool/Lease` | 运行时有限资源的 owner 与借还；同一容量声明投影为 `ResourceDecl` |

当前 V1 compiler 真正执行的检查包括：精确 request/completion signature、双向 capability、stage 顺序、
fanout 的 split/aggregate 声明，以及 `weaken/drop` 的显式授权。它只接受 operation-effect equivalence、空的
ordering claim、reject unsupported policy、report-fault reset policy 和 sequential access mode；pin/cycle、
reset drain、隐式 default/drop 等尚无执行证据的承诺会在构造期被拒绝。`applicability_rule`、
`completion_rule` 已由具体 address stage 与 codec 使用；更完整的 ordering/admission/fold report 仍需继续补齐。
当前 deterministic output 的证据级别是 execution witness。外部 RTL 的逐周期等价需要 `PIN_CYCLE`
comparison profile；通用 stutter projection、partial-order conformance 和 latency window checker 属于后续
实现。

Unary lowering 包含 `LoweredOne`、`LocalCompletion` 和 `Rejected`；fanout begin 对应
`Expanded(count, context, fold_state)`、`LocalCompletion` 或 `Rejected`。Stage 报告转换语义，
capacity pool 与 executor 报告资源不足。operation-level executor 沿用同步运行边界；pool 内部返回 typed
`CapacityFailure`，executor fault 保留这份 detail，同时提供可读的 pool/usage/owner reason。typed
`ResourceDemand`/blocked state 留给非立即 emission 阶段。

Stage 的作用域是一笔 operation；executor state 持有跨事务的 ID map、owner、queue、cursor 和 result
storage，并为其声明 key、lifetime 与释放条件。`TranslationPlan` 必须由 `compile_translation_plan()` 产生并携带
compiler witness；executor 在使用前重新核对 stage 的 name/signature/contract/cardinality metadata。
stage 合同约束 Python stage 的副作用，定向测试通过外部 probe 观察运行行为。

这些运行对象已经能在 bridge 内说明 parent pool、egress lease、reply context、child owner、fold 和
completion origin。下一步由统一 VirtualDut boundary projection 向 SystemProtocol 暴露资源、owner 和
error-origin 事实，并接入 wait-for 或端到端 return monitor。当前“资源已声明”的证据范围是 bridge runtime
已经拥有唯一、可投影的事实来源。

### 3.1 Attachment-aware 外壳

公共 executor 接收已经 decode 的 operation。attachment-aware backend 在 event 边界汇合以下三份候选状态，
并作为一次事务提交：

```text
ingress decode candidate
    → executor candidate + operation emissions
    → egress/ingress encode candidates
    → 全部成功后一起 commit
```

decode、stage 或 encode 失败时，attachment 与 executor 保留调用前状态，emission 集合保持为空。
executor 会在同步调用内推进到“一个 child 已发行并等待 completion”或“所有工作完成且静止”；外层
`is_quiescent` 同时检查两侧 attachment 的 partial transaction state。这个外壳使用 address-operation attachment
契约；`InterfaceAttachment` 保持最小 operation SPI，stream 和 coherent message 采用各自的 typed operation。

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

`translation` 是 VirtualDut 的 constructed-backend 子包。Recipe 依赖两侧协议 attachment 和通用 executor；
executor 的依赖止于协议中立合同。

## 5. 实施阶段

| 阶段 | 状态 | 实现内容 | 完成判据 |
|---|---|---|---|
| T1 | 已完成 | signature、envelope、profile/contract、unary/fanout stage、ledger、pool/lease、linear plan DTO | 合成 `Batch(3)→Item` 显示 1 parent、3 obligations、child peak=1；plan 定位 request/completion、capability 顺序和未授权 loss |
| T2 | 已完成 | operation-level `SerialTranslationExecutor` | parent FIFO、一个 child owner、lazy fanout、local completion、reverse lift/fold、lease usage 和错误原子回退均进入显式状态 |
| T3 | 已完成 | `AddressBurst` 与 `BurstToAccessStage` | AXI attachment 负责 AW/W join 并产出 reply context；通用 stage 负责 child geometry/fold |
| T4 | 已完成 | attachment-aware operation backend/codec transaction | event decode/encode 与 executor 候选状态共同提交，完整 quiescence 覆盖两侧 attachment |
| T5 | 已完成 | AXI4→APB 迁入公共 runtime | preset 只选择 profile；split/schedule/correlate 由公共 stage、executor 和 backend 承担 |
| T6 | 已完成 | AXI4-Lite→APB 迁入公共 runtime | 1→1 plan 与 AXI4 burst bridge 共用 executor 和 address leaf stages |
| T7 | 已完成 | AHB/APB/AXI egress 与统一 composition root | `build_amba_serial_bridge_vdut()` 复用公共 backend，闭合 4×4 family 矩阵，并以当前 7 个 variant 的 7×7 默认-profile 装配见证验证入口复用 |
| T8 | 部分完成 | 接入普通 `SystemProtocol` topology | bridge 已作为普通多端口 VirtualDut 接入；完整 intent→codec→stage→policy→module construction report 仍待补齐 |

这些阶段使用新架构定向 witness 检查 route miss、capacity、错误聚合、burst split 和跨 family 返回。
4×4 表示 family-level 构造闭合；具体 revision、可选字段和运行语义仍受下述 profile 边界约束。

## 6. V1 验收条件

本节记录当前已经满足的 V1 验收条件：

- 至少三种 bridge preset 共用一个 executor；
- `BurstToAccessStage` 可替换 APB egress 为 AHB SINGLE egress；
- AXI reply context 与 `AddressBurst` 分离；多个 parent 的 R/B 编码仍能回到各自 descriptor/ID；
- executor token 独立于 AXI ID；同 ID parent 按完整 operation 形成顺序 FIFO 完成；
- child descriptor lazy、write-result fold O(1)，同时明确 V1 read-result storage 为 O(N)；
- plan 构造能拒绝 signature 不闭合、第二个 fanout 和未声明的属性损失；
- plan/compiler witness 保存双向 capability closure、stage ordering、SemanticEffect 和所选 equivalence level；
- route miss 形成 local completion，egress lease 保持可用；
- 容量 fault 能指出 pool、当前 usage、limit 和被拒绝的 owner；
- AXI4→APB 当前公开 profile 的 completion 和容量边界保持可解释；
- recipe 选择并组合 stage/executor 已拥有的状态机；
- concrete executor state 能说明 owner、lifetime 和正常 completion release；wire completion 与内部 token
  使用独立身份。

尚未达到 V1 完整报告目标的部分是统一 construction report、逐 child 因果投影，以及 reset/cancel origin 的
完整运行路径。当前 serial bridge 已覆盖构造和同步执行；更强诊断承诺以上述报告与投影为进入条件。

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

本表记录当前实施范围。多个 AMBA egress 已证明当前接口可以复用；后续依据 width、并行 outstanding、
原生 burst 保持和诊断需求选择下一项扩展。
