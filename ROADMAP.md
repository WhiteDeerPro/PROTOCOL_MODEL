# Protocol Model Roadmap

## 1. 项目定位

Protocol Model 的目标是：用可执行语义和受约束的状态空间探索，生成、验证并诊断通信协议
及协议网络的有限行为。

它可以采用形式语言、自动机、偏序、Petri 网、时序逻辑和 assume/guarantee 等方法，但
边界应始终围绕**协议可观察行为**。它不是通用 RTL model checker、定理证明器、RTL 生成器，
也不负责建立每一种 DUT 的完整功能模型。

```text
协议要求
  → SemanticFragment
  → LinkProtocol + 具体 VirtualDut
  → SystemProtocol + topology elaboration
  → 有限 trace / 系统状态
  → verdict + 最小诊断证据
```

`network` 是 `SystemProtocol` 内部的 topology 概念；全局可观察通信合同本身称为
`SystemProtocol`。当前设计分别使用 `LinkProtocol`、`ProtocolLink/SystemProtocol` 和
topology/runtime 表达协议定义、绑定与执行。

后续工作遵守三个原则：

1. 同一套 step 语义同时服务合法行为构造和外部 trace 验证；
2. 协议规范、endpoint 能力、实现策略和测试假设必须分别记录；
3. 每项能力用合法 witness、单点负例和可解释图表闭环，不以测试数量代替语义覆盖。

本文维护长期能力方向和依赖关系，不承担当前实现清单。近期工作的实际顺序见
[技术路线实施阶段](docs/architecture/technical-route/08-roadmap.md)，已实现与尚未实现的边界见
[实现状态](docs/architecture/implementation-status.md)。Bridge 的概念和首版施工边界分别由
[Bridge 与类型化事务转译](docs/architecture/typed-transaction-translation.md)和
[类型化事务转译实施案](docs/architecture/translation-implementation.md)维护。

## 2. 当前基础

以下方法已经进入新架构或完成取舍，不再作为未来计划重复列出：

- `SemanticComponent` 统一 state/action/step/emission/fault，支持三值 verdict；
- 类型化 payload domain、reset/ready-valid/quiet observation pattern；
- cardinality、correlation、AW/W join、read/write obligation 和 per-ID token；
- 有限因果偏序、拓扑序、并发查询和因果图；
- AXI4 五通道、burst、4KB、WSTRB、narrow、读写事务及 link-local ordering；
- 不可变 `LinkProtocol`、profile、`ProtocolLink` 和 `SystemProtocol`；
- VirtualDut 的 source、sink、responder、bridge 原型及声明式 contract 元数据；
- manifest、显式 `out/` 运行结果、系统拓扑/因果图和文档发布边界。

当前主要缺口不是“再增加几个 case”，而是通用组合语义、resource-aware blocked/deferred 网络运行扩展、
可达性分析、时钟模型和外部观测接入。现有同步 `SystemSession` fixed-point runtime 继续作为点到点与微型
bridge 的执行基础。

## 3. 工作主线

### R1：提升语义引擎与协议派生能力

目标是让新协议主要通过复用元组件和组合器得到，而不是为每个协议重新编写一个大型状态机。

优先建设：

- **I/O LTS 组合**：同步积、异步并行、端口 rename/hide、输入输出 ownership；
- **规则组合器**：guard、invariant、choice/conflict、join/fork、sequence、retry、timeout；
- **资源语义**：credit、capacity、FIFO、token color、reservation 和 release；
- **关系语义**：显式 precedence、independence、conflict 与 ordering domain；
- **时间语义**：逻辑时钟、区间 deadline、跨域不可比时间，而不是默认使用单一 cycle；
- **派生器**：对 channel、event domain、transaction model、capability 和 requirement 进行
  可追溯替换或收窄；
- **类型化事务转译**：用 operation form、translation stage/plan、fan-out ledger、completion fold
  和资源租约描述 bridge，不让成对协议 backend 随协议数量按平方扩张；
- **统一 provenance**：每个 fault、emission、因果边和派生约束能够回指规则、实例和原始采样；
- **有界探索**：状态 canonicalization、visited-state、反例 trace、partial-order reduction；
- **最小诊断相关集**：从失败状态反向提取最小相关事件、资源和规则集合。

设计上优先增加可组合的 `SemanticComponent` 构造器和稳定的语义 IR。只有出现新的、长期稳定的
状态迁移形状时才增加基类；避免形成大量彼此不兼容的协议专用子类。

完成标准：至少能用公共组件派生 UART frame、I²C transaction 和一个 credit/FIFO 网络，而
不修改 core 的 step 契约。

### R2：协议网络、环与 deadlock 诊断

网络分析不能只对现有因果 DAG 增加一次“找环”。需要明确区分三类图：

| 图 | 节点/边 | 环的含义 |
|---|---|---|
| Topology graph | endpoint、link、bridge 及物理/逻辑连接 | 环可以合法；ring、反馈控制和 token 环都可能正常工作 |
| Causal graph | 已发生事件之间的 happens-before | 必须是严格偏序；出现环说明语义自相矛盾 |
| Wait-for graph | 当前状态中组件、端口、资源之间的等待 | 环是 deadlock 候选，不单独构成充分证明 |

真正的协议 deadlock witness 至少应满足：

```text
reachable(state)
and non_quiescent(state)
and no_enabled_internal_transition(state)
and blocked_obligations(state) != empty
and environment_assumptions_hold(state)
```

wait-for 环不一定导致失效。例如下面的机制可能提供 escape：

- 环中预先存在 token 或 credit；
- 某个 buffer 仍有容量，可以先释放一个依赖；
- 协议允许 retry、drop、abort 或独立 response channel；
- routing/virtual-channel 规则保留了无环 escape class；
- 某个 transition 已经 enabled，只需要公平调度即可前进。

注意：fairness 可以防止 enabled transition 长期得不到执行，但不能挽救“没有任何 transition
enabled”的真实 deadlock。

网络主线分为：

1. typed port 与 role compatibility；
2. topology elaboration、link ownership 和 event routing；
3. 每条 link 独立 session state，禁止隐式共享；
4. buffer、credit、outstanding、route 和 obligation 的动态资源视图；
5. SCC 作为廉价候选检测，再用有界可达性确认或排除 deadlock；
6. 输出最小 wait cycle、被阻塞端口、持有资源、未完成义务和可能的 escape transition；
7. 支持协议/profile 声明“此环为何安全”的约束及可验证 invariant。

第一个端到端验证场景可使用 ready-valid ring：同一拓扑生成三组结果——零缓冲 lock、带一个
初始 token 的可前进环、带 escape FIFO 的安全环。这样可以证明“拓扑有环”和“系统死锁”不是
同一件事。

deadlock 之后仍需覆盖以下网络问题：

- livelock、starvation、unfair arbitration；
- head-of-line blocking、priority inversion 和拥塞传播；
- buffer overflow/underflow、credit leak 和资源泄漏；
- route loop、广播 join 永不满足、请求/响应归属错误；
- ID alias、重复、丢失、非法重排和 barrier 破坏；
- reset propagation、局部 reset 后的旧事务污染；
- open system 中环境不响应与网络自身 deadlock 的区分。

### R3：VirtualDut backend 与构造算子

VirtualDut 是外部 module 边界。复杂算法、FPU 计算或软件模型可以通过 RTL/Python/C/RPC/trace
backend 提供；内部状态可以不透明，引擎不需要证明或枚举 backend 内部实现。

需要在工程内部构造 traffic、reference endpoint、bridge 或 crossbar 时，按
[VirtualDut 方法论](docs/architecture/virtual-dut.md) 使用 bottom-up 算子，不按外设名称建立继承树：

- Source/Choice、Sink/Observe 和 Transform；
- FIFO/table/pool/counter/register 等 Store/Resource；
- Correlate/Join、Route/Fork 和 Select/Arbitrate；
- Compose/Hide、boundary contract 和 backend binding；
- 后续增加 blocked/deferred emission、latency 和 clock-domain 扩展。

其中 `Transform` 是行为构造词汇；跨协议 bridge 需要把它收窄为可执行的类型化转译合同。operation
form、stage、执行资源和 completion 回收的边界以
[Bridge 与类型化事务转译](docs/architecture/typed-transaction-translation.md)为准。

#### QoS 与仲裁的归属

QoS 和仲裁不是只能放在一个层次，正确划分如下：

| 内容 | 归属 |
|---|---|
| QoS/priority 字段的宽度、握手稳定性和协议规定的 ordering | 基础 LinkProtocol |
| endpoint 支持哪些 priority、outstanding 或 burst | Protocol profile / capability |
| round-robin、fixed-priority、age-based 等选择算法 | interconnect/arbiter VirtualDut |
| 最大等待、公平性、带宽配额、隔离目标 | scenario contract / verification property |
| 搜索 starvation、检查 invariant、生成反例 | engine/network analyzer |

也就是说，总线协议规定“如何表达并合法传输”，VirtualDut 决定“如何调度”，验证场景声明
“这次必须保证什么”，引擎负责验证。不要把某个 arbiter 的策略写成所有 AXI4 实例都必须满足
的规则。

### R4：派生新的实用协议

新增协议的意义不是扩大协议名单，而是用不同协议压力测试公共抽象。

#### UART：先做

UART 适合作为下一份协议，因为它迫使引擎处理串行化和时间容差，而不依赖复杂网络：

```text
line samples/edges
  → baud interval and sampling window
  → start bit + data bits + parity + stop bits
  → UART_FRAME event
```

第一阶段覆盖 idle/start/data/optional parity/stop、LSB-first、framing/parity error、相邻 frame 和
可配置 baud tolerance。模型不模拟模拟电气噪声；抖动和采样不确定性用时间区间或有限选择表达。

建议场景：一端 `UartTx VirtualDut` 产生 frame，另一端 `UartRx VirtualDut` 解码；分别构造
正常 frame、错误 stop bit、baud drift 边界和 back-to-back frame。

#### I²C：在 shared-wire 与 network ownership 之后

I²C 会同时压力测试：open-drain 多驱动解析、START/STOP/repeated START、address/ACK/NACK、
clock stretching、多 controller arbitration 和 bus recovery。因此它应建立在 R1 的时间语义和
R2 的多参与者网络运行时之上。

需要新增的公共基础包括：

- resolved wire：所有参与者只能拉低或释放，总线值为 wired-AND；
- edge/level phase monitor；
- multi-owner drive intent 与 arbitration-lost event；
- clock stretching 的等待关系及 bus-busy timeout；
- transaction 层的 address/data/ACK/repeated-start obligation。

I²C 网络中的物理连接天然类似“多端共享环/总线”，但诊断仍应基于 drive、ownership 和
wait-for 关系，而不是仅按拓扑判断。

后续可用 SPI 检验同步串行与 chip-select ownership，用 TileLink/AXI-stream 检验更丰富的
channel/credit 组合；在 UART/I²C 把公共缺口暴露清楚前，不追求协议数量。

每份新协议的完成标准相同：基础 spec、合法生成、外部 trace 验证、至少一个合法和一个单点
负例、一个 VirtualDut 组合场景、波形/因果图、明确的未覆盖条目。

### R5：多时钟域与 CDC

CDC 不能通过给所有事件增加一个全局 cycle 解决。不同 clock domain 的本地时间默认不可直接
比较，只有同步事件、已知 clock relation 或 bridge contract 才能建立跨域因果边。

计划分层：

1. `ClockDomain`、本地 tick、频率/相位关系和异步 domain；
2. 多源 observation 的稳定合并，不把采集顺序伪装成协议顺序；
3. two-flop synchronizer 的有限非确定延迟抽象；
4. toggle/pulse handshake、Gray counter 和 async FIFO pointer obligation；
5. reset-domain crossing 与 epoch 隔离；
6. 跨域 latency 区间、丢 pulse、重复消费和 reconvergence 诊断。

边界必须写清：本项目可验证协议级 CDC handshake 和抽象 synchronizer contract，不取代结构化
CDC lint，也不模拟模拟意义上的 metastability。metastability 只建模为有限不确定、延迟区间
或 unknown value，结构上是否使用正确 synchronizer 仍需要 RTL/netlist 证据。

第一个 CDC 场景建议为 async ready-valid bridge 或 async FIFO：正例跨两个独立逻辑时钟
传递 token，负例展示 pulse 丢失、reset epoch 污染或 pointer obligation 破坏。

### R6：外部观测、诊断与工程化

这是让模型进入真实 UVM/RTL 工作流的关键方向，应与 R1 同步设计 schema，而不是最后再做。

- canonical event/trace JSON schema 与版本迁移；
- VCD adapter 优先，FSDB 通过可选外部转换器或插件接入，UVM transaction adapter 后续加入；
- pin sample → canonical event → transaction → rule 的完整 provenance；
- partial probe、unknown/unobserved/quiet 的覆盖报告；
- waveform 上回链到 violation 和最小因果/等待依赖子图；
- 两次运行或 DUT/reference trace 的语义 diff；
- requirement coverage：implemented、profiled、unobserved、missing foundation；
- 稳定 Python API、场景扩展入口、版本化 manifest 和可重复运行配置。

另一个必要方向是**规约一致性与 refinement**：判断场景 profile 是否真的是基础协议的收窄，
bridge 输出是否 refinement-compatible，以及两端 assumption/guarantee 是否能够闭合。这仍然只
针对协议接口，不扩张到任意程序证明。

## 4. 长期能力的依赖顺序

以下顺序描述从当前桥原型走向协议网络分析时的主要依赖。它是长期阶段建议；某一阶段的局部工作可以
与相邻阶段并行，但不应绕过其输入合同。

| 阶段 | 主要交付 | 为什么先做 |
|---|---|---|
| P0 | typed operation form、TranslationPlan、fan-out/completion ledger、lease 与串行 executor | 先把已有 pair-specific bridge 提炼成可复用且可解释的转换过程 |
| P1 | capability/address 投影、construction lowering 与 provenance | 让连接意图可以安全地生成显式 bridge VirtualDut 和两侧 links |
| P2 | blocked reason、动态资源、resource-aware/deferred runtime extension、ready-valid ring 与死锁相关依赖子图 | 在局部容量生命周期稳定后，建立跨节点 wait-for 关系 |
| P3 | opaque backend binding、Store/Route/Arbitrate backend 与 crossbar owner table | 同时接入外部 Vdut，并扩展多入口互连的局部调度能力 |
| P4 | canonical JSON 与 VCD adapter | 把外部 DUT trace 接入同一语义入口 |
| P5 | time domain 与 UART | 用较小协议验证串行和时间抽象 |
| P6 | shared wire 与 I²C | 验证多驱动、仲裁、stretch 与共享总线 |
| P7 | async bridge/FIFO 与 CDC contract | 在多时钟基础成熟后处理跨域协议 |
| P8 | partial-order reduction、refinement、规模与插件化 | 在语义和资源边界稳定后解决状态爆炸和生态扩展 |

依赖关系可以概括为：

```text
semantic composition
       └──► typed transaction translation
                  └──► capability-backed construction
                              └──► resource-aware runtime extension ──► wait-for/deadlock ──► QoS/fairness

semantic provenance ──► trace schema ──► VCD/FSDB/UVM adapters

time domains ──► UART ──► CDC
           └──► resolved shared wire ──► I²C
```

## 5. 近期版本建议

下一里程碑不以“增加协议数量”为目标，建议定义为：

### 阶段 A：Typed Bridge and Composable Network

- `AddressBurst` 等 operation form、类型化 stage/plan、fan-out ledger、lease 与串行 executor；
- 用公共转译执行器重构 AXI4→APB，并增加第二种 egress 以检验复用边界；
- capability/address 投影和 construction lowering，生成显式 bridge VirtualDut 与两侧 links；
- 扩展现有 elaboration，闭合 capability、construction provenance 和生成后的 topology；
- resource/wait reason IR；
- topology、causal、wait-for 三图分离；
- ready-valid ring 的 lock/safe/escape 三个 case；
- 最小 deadlock witness 与诊断报告；
- 一个由 Store 算子构造的 stateful FIFO VirtualDut fixture。

### 阶段 B：Timed and External Traces

- canonical trace schema、VCD adapter；
- clock domain 与时间区间；
- UART 基础协议与 Tx/Rx 组合场景；
- 外部 waveform 到规则/事件的 provenance。

### 阶段 C：Shared Bus and CDC

- resolved open-drain wire 与 I²C 基础事务；
- 多 controller arbitration/stretches 诊断；
- async ready-valid/async FIFO CDC 场景；
- bounded exploration 与 partial-order reduction 的第一版。

阶段名称只表示能力依赖顺序，不表示理论已经完备。每个里程碑都必须保留未覆盖规则和环境假设，
避免把一次有限 witness 的 `PASS` 宣称为对完整协议或 RTL 的证明。
