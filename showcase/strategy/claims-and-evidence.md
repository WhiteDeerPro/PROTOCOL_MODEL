# 对外宣称与证据 / Public Claims and Evidence

**审计快照 / Review snapshot:** 2026-07-16
**适用范围 / Scope:** 当前 `protocol_model/` 主源码树，不含已经退出的 v0.1 实现。

本表是宣传文案的事实底稿。代码存在不自动等于方法有效；“当前实现”只说明对象和定向 witness 已经进入主线，
“拟议”说明目标与升级门槛已定义，“研究问题”说明结论仍需要外部案例或比较实验。

This table is the factual basis for public copy. Code presence does not by itself validate the method. **Current** means
that an object and focused witness exist on the main line; **proposed** means that a target and promotion gate are
defined; **research question** means that external cases or comparative experiments are still required.

## 1. 当前可以使用的宣称 / Claims supported today

| ID | 中文公开表述 | English public wording | 代码或执行证据 | 必须保留的限定 |
|---|---|---|---|---|
| C-01 | Protocol Model 可以从 typed event、constraint、resource、obligation 和可组合 fragment 构造协议语义。 | Protocol Model composes protocol semantics from typed events, constraints, resources, obligations, and fragments. | [`semantics`](../../protocol_model/semantics/)；[`patterns`](../../protocol_model/patterns/)；[当前状态](../../docs/architecture/migration-status.md) | “组合”指当前 Python 模型的构造与执行，不是数学完备性证明。 |
| C-02 | 当前 AXI4 LinkProtocol 覆盖 burst、narrow/unaligned、read interleave、AW/W/B correlation、link-local exclusive eligibility 和 observation。 | The current AXI4 LinkProtocol covers bursts, narrow/unaligned transfers, read interleaving, AW/W/B correlation, link-local exclusive eligibility, and observation. | [`link/amba/axi/axi4`](../../protocol_model/link/amba/axi/axi4/)；[`test_axi4_link.py`](../../tests/test_axi4_link.py)；[`test_axi4_narrow.py`](../../tests/test_axi4_narrow.py)；[`test_axi4_exclusive.py`](../../tests/test_axi4_exclusive.py)；[`test_axi4_observation.py`](../../tests/test_axi4_observation.py) | 不写“完整 AXI4 compliance”；跨 link exclusive conflict、memory visibility 和逐条 requirement catalog 尚未闭合。 |
| C-03 | 当前主线包含 AXI4、AXI4-Lite、AXI4-Stream、AHB-Lite/AHB5 profile、APB3/4/5 和 ACE-Lite ordinary-data subset 的 LinkProtocol 实现。 | The main line includes LinkProtocol implementations for AXI4, AXI4-Lite, AXI4-Stream, AHB-Lite/AHB5 profiles, APB3/4/5, and an ACE-Lite ordinary-data subset. | [`link/amba`](../../protocol_model/link/amba/)；[`test_ahb_link.py`](../../tests/test_ahb_link.py)；[`test_apb_link.py`](../../tests/test_apb_link.py)；[`test_ace_lite_link.py`](../../tests/test_ace_lite_link.py) | 不写“全部 AMBA”。Arm 的[规范列表](https://www.arm.com/architecture/system-architectures/amba/amba-specifications)还包括 CHI/CHI C2C、full ACE、ATB、CXS 等；本项目的 CHI 当前只有 namespace/audit，TileLink 只有 namespace。 |
| C-04 | VirtualDut 表示具名虚拟 module，并通过 typed port、binding 与 attachment 装配协议边界。 | A VirtualDut represents a named virtual module whose protocol boundaries are assembled through typed ports, bindings, and attachments. | [`virtual_dut/boundary`](../../protocol_model/virtual_dut/boundary/)；[`virtual_dut/binding`](../../protocol_model/virtual_dut/binding/)；[`integrations/attachments`](../../protocol_model/integrations/attachments/)；[`test_virtual_dut_binding.py`](../../tests/test_virtual_dut_binding.py) | 当前 backend 主要是构造式同步模型；不能据此声称已连接任意外部 RTL/RPC DUT。 |
| C-05 | SystemProtocol 可以连接多个 VirtualDut 与 link，检查 ownership/elaboration，并在当前同步边界内运行微小网络。 | SystemProtocol can connect VirtualDuts and links, check ownership and elaboration, and execute small networks within the current synchronous boundary. | [`system`](../../protocol_model/system/)；[`test_system_protocol.py`](../../tests/test_system_protocol.py)；[SystemProtocol 架构](../../docs/architecture/system-protocol.md) | 当前使用同步 fixed-point session；异步 emission、复杂 progress 和 deadlock 尚未闭合。 |
| C-06 | 当前已有 AXI4→APB 与 AXI4-Lite→APB bridge witness，可展示拆分、串行调度、地址映射和 completion return 的一部分。 | AXI4-to-APB and AXI4-Lite-to-APB bridge witnesses currently demonstrate parts of splitting, serial scheduling, address mapping, and completion return. | [`integrations/recipes/amba/bridges`](../../protocol_model/integrations/recipes/amba/bridges/)；[`test_virtual_dut_axi4_apb_bridge.py`](../../tests/test_virtual_dut_axi4_apb_bridge.py)；[`test_virtual_dut_axi4_lite_apb_bridge.py`](../../tests/test_virtual_dut_axi4_lite_apb_bridge.py) | Full AXI bridge 仍是协议对专属 backend；width conversion、并发 APB child 和 attachment-aware 公共 executor 尚未完成。 |
| C-07 | 类型化事务转译内核已经实现 operation signature、stage contract、plan closure、fan-out lifecycle、capacity lease 和 serial executor。 | The typed transaction translation kernel implements operation signatures, stage contracts, plan closure, fan-out lifecycle, capacity leases, and a serial executor. | [`virtual_dut/translation`](../../protocol_model/virtual_dut/translation/)；[`test_virtual_dut_translation.py`](../../tests/test_virtual_dut_translation.py)；[转译架构](../../docs/architecture/typed-transaction-translation.md) | 这里的“typed”是 Python 类型对象与构造期/运行期合同检查，不是静态类型定理或自动 bridge 合成证明。 |
| C-08 | 项目具有 managed run store、manifest、Graphviz topology/trace 和 WaveDrom renderer 的产物基础。 | The project has an artifact foundation comprising a managed run store, manifests, Graphviz topology/trace output, and a WaveDrom renderer. | [`artifacts`](../../protocol_model/artifacts/)；[`visualization`](../../protocol_model/visualization/)；[`test_artifacts.py`](../../tests/test_artifacts.py)；[`test_system_protocol.py`](../../tests/test_system_protocol.py) | 当前 AXI 投影先放在 Demo presentation adapter；现阶段不能宣传成 RTL/VCD 波形工具。 |
| C-09 | 当前统一 AXI4 介绍集实际执行 24 个具名场景；每案生成模型波形、因果图和机器结果，其中两个场景在同一导航内增加逐步精讲。 | The unified AXI4 introduction set executes 24 named scenarios; every case produces a model waveform, causal graph, and machine-readable result, while two cases add focused walkthroughs within the same navigation. | [`source and runner`](../demos/axi4/README.md)；[`中文发布结果`](../generated/axi4/README.zh-CN.md)；[`English artifacts`](../generated/axi4/README.en.md)；[`coverage graphic`](../generated/axi4/coverage.svg) | 10 个合法场景与 14 个预期违规满足声明期望；这是代表性场景证据，不是 AXI4 规范条款覆盖率或 RTL compliance。18 个 event 输入场景生成 CanonicalEvent 顺序视图，6 个 frame 输入场景生成 `AtomicFrame` ready/valid 视图；其中两案增加精讲。两种视图都不是 RTL/VCD。 |

## 2. 可以描述为目标，但不能改成现在时 / Proposed capabilities

| ID | 拟议表述 / Proposed wording | 当前缺口 / Missing evidence | 升级为 CURRENT 的门槛 / Promotion gate |
|---|---|---|---|
| P-01 | “完整首轮技术预览将提供一个干净安装入口和统一的示例运行命令。” / “The complete first technical preview will provide a clean installation path and one example command.” | `pyproject.toml`、统一具名 runner 和本地隔离构建/安装记录已经存在；尚无非维护者干净复现记录，也没有通用 list/replay CLI。 | 三位外部用户从干净 checkout 在约 10 分钟内生成统一结果，并能解释 expected violation。 |
| P-02 | “公开场景将继续按知识目标校正，并与 requirement metadata 相连。” / “The public scenarios will continue to be refined by learning objective and connected to requirement metadata.” | 当前 24 个场景已有主题、目标和执行规则，但尚未逐项连接官方文档 revision/section/profile/status。 | 每案有 requirement/profile/status，去除叙事重复，并由至少三位外部用户独立读懂。 |
| P-03 | “公共 translation kernel 旨在让 bridge 复用 codec 与 semantic stage。” / “The shared translation kernel is intended to let bridges reuse codecs and semantic stages.” | Full AXI4→APB 尚未迁移到 attachment-aware executor；尚无第二个协议对复用同一完整路径。 | 至少两个语义不同的 bridge preset 复用 executor/stage，并保持各自 protocol-specific codec 与 error mapping。 |
| P-04 | “未来可以把 RTL observation 降低为同一 AtomicFrame，再复用检查与展示路径。” / “A future RTL path can lower observations into the same AtomicFrame boundary and reuse checking and presentation.” | 尚无 VCD/FST/cocotb/UVM adapter，也未闭合四态值、采样区间与 backpressure。 | 一个公开小 DUT 的真实 trace 可重放；报告明确 simulator、时钟/reset、采样政策和原始波形来源。 |
| P-05 | “后续小型 interconnect 示例将研究 arbitration、return ownership 与 wait-for。” / “A later interconnect example will study arbitration, return ownership, and wait-for relationships.” | 通用 Arbitrate/Compose、blocked reason 和异步 emission 尚未实现。 | 先建立可执行 multi-ingress owner/return table，再定义 system progress property；不能用若干独立 bridge 冒充 crossbar。 |

## 3. 应当作为研究问题 / Research questions

| ID | 中文问题 | English question | 需要怎样的证据？ |
|---|---|---|---|
| RQ-01 | 同一份构造语义能否减少 generator、monitor 和 report 之间的重复与分叉？ | Can one constructed semantics reduce duplication and drift across generators, monitors, and reports? | 选择同一组 AXI requirements，对比传统实现与共享构造路径的修改点、缺陷与维护成本；避免只比较代码行数。 |
| RQ-02 | typed operation + stage 是否能降低多协议 bridge 的组合增长？ | Can typed operations and stages reduce combinatorial growth in multi-protocol bridge implementations? | 至少实现两个以上协议族的多个 bridge preset，记录真正复用与仍需协议专属处理的部分。 |
| RQ-03 | LinkProtocol / VirtualDut / SystemProtocol 的作用域是否改善故障归属？ | Does the LinkProtocol / VirtualDut / SystemProtocol scope split improve fault ownership? | 用 link-local、bridge-local 和 system-level 三类真实缺陷做盲审，看诊断是否落到正确 owner 与证据窗口。 |
| RQ-04 | 资源生命周期能否自然导出 wait-for/deadlock 分析？ | Can explicit resource lifecycles support useful wait-for and deadlock analysis? | 先实现非立即 emission、blocked demand 和动态 owner，再在有界微网络中验证 soundness 与误报边界。 |

## 4. 不应发布的强宣称 / Claims to reject

| 不使用的说法 | 为什么证据不足 | 可替换的说法 |
|---|---|---|
| “达到国际领先/学术前沿水平” | 没有系统文献综述、同行评审或可复现实验比较。 | “提出一条可执行的组合式协议语义路线，正在通过 AXI 与 bridge 案例检验。” |
| “在工业界首次实现……” | 无法从当前仓库证明 first-to-market 或穷尽专有工具能力。 | “把 LinkProtocol、VirtualDut、SystemProtocol 与 typed translation 放在一个参考实现中联合探索。” |
| “超越商业 VIP、formal 或互连工具” | 没有等价任务、benchmark、覆盖率、性能或误报对比；商业能力也通常不可完全检查。 | “与仿真、VIP、formal 和硬件生成生态互补，重点探索语义构造与解释证据。” |
| “支持几乎所有主流 AMBA 协议” | Full ACE、CHI 尚未成为可执行完整 profile；协议版本和 feature 范围不同。 | 使用 C-03 的精确列表，并明确 ACE-Lite subset、CHI/TileLink 状态。 |
| “协议无关透明桥接，无需协议对适配器” | 当前 full AXI4→APB 是 pair-specific backend；codec、属性和 error mapping 本来也需要协议知识。 | “正在把协议专属 codec 与可复用 operation/stage/executor 分离。” |
| “完整形式化验证” | 当前有 executable constraints、monitor 和 causal evidence，但无 model checker、SMT proof 或 theorem prover。 | “组合式可执行语义检查”；若生成违规样例，称 “diagnostic replay trace”，不称 formal counterexample。 |
| “类型安全保证协议转换正确” | 当前 typed DTO 与 plan closure 能提前发现一部分 mismatch，但不构成端到端正确性证明。 | “typed contracts 与 plan closure 在构造期暴露一部分 signature、capability 和 semantic-loss 问题。” |
| “从 module 到跨片系统的统一模型已经完成” | 子系统封装能力已存在，但 chiplet/board/inter-chip timing、transport 和 consistency 尚无完整实现。 | “架构允许递归封装；当前可执行证据集中在单 link 与同步微网络。” |

## 5. 与相邻工作的克制对照 / Bounded comparison with adjacent work

这些参照说明本项目所面对的问题并非空白领域，也帮助限定自己的切入点；它们不构成优劣评分。

| 相邻工作 | 官方公开目标或机制 | 对 Protocol Model 的启示与边界 |
|---|---|---|
| [Accellera UVM](https://www.accellera.org/activities/working-groups/uvm) | 模块化、可扩展、可复用的验证环境与标准方法。 | Protocol Model 不替代 UVM 的 simulator/VIP 生态；可研究是否为 sequence、monitor 和 report 提供共享语义来源。 |
| [CIRCT ESI](https://circt.llvm.org/docs/Dialects/ESI/) 与 [rationale](https://circt.llvm.org/docs/Dialects/ESI/RationaleESI/) | typed point-to-point channels、services 与硬件 IR/lowering；官方文档也标注仍处于早期。 | typed communication 不是本项目独有。Protocol Model 的待证差异是协议约束、生命周期和诊断证据如何从构造结果派生。 |
| [Chipyard Diplomacy](https://chipyard.readthedocs.io/en/1.12.2/TileLink-Diplomacy-Reference/) | 节点通过两阶段参数交换协商互连配置。 | capability negotiation 和互连构造已有成熟思想；本项目当前更关注验证侧的 link/system contract，而非硬件生成。 |
| [OpenTitan testplanner](https://opentitan.org/earlgrey_1.0.0/book/util/dvsim/doc/testplanner.html) | 将 testpoint、执行测试和结果状态关联起来。 | requirement catalog 应把条款、profile、monitor 和 scenario 连起来；不能用“测试很多”代替可审计覆盖。 |
| [Arm AMBA specifications](https://www.arm.com/architecture/system-architectures/amba/amba-specifications) | 官方 AMBA 家族包含 CHI/CHI C2C、AXI、ACE、AHB、AXI-Stream、APB、ATB、CXS 等多个协议系列。 | 对外协议清单必须写 feature/profile 边界；当前 executable scope 不能概括成“几乎所有 AMBA”。 |

公开比较时只说明作用域和可连接点，不使用星级表、笼统领先性或无法复现的开发效率数字。

## 6. 对外部评价稿的取用方式 / How the supplied assessment is used

外部评价提出的“统一语义来源、分层责任、typed translation、可复用验证资产”适合作为项目价值假设，已经在
one-pager 和 deck 中改写成可以由 demo、外部案例和比较实验回答的问题。以下内容不进入公开事实陈述：

- “国际领先”“工业界首次”“超过商业工具”等缺少对等 benchmark 的结论；
- 把 executable constraint 直接等同于 formal proof 的表述；
- 把尚未接入公共 executor 的 bridge witness 写成任意协议自动转换；
- 星级评分和无法说明测量方法的开发效率比较；
- 量子协议验证、聚合物网络等与片上互连问题没有直接证据关系的参考资料。

NoC/formal survey 可以用于说明领域问题的重要性，但不能单独证明本项目的水平。公开材料优先链接相邻项目的
官方文档、当前代码 witness 和可复现 artifact；研究影响力留给后续同行评审和真实采用来判断。
