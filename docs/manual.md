# Protocol Model 用户手册

## 1. 本项目解决什么问题

验证一个互连、桥接器、外设接口或带总线端口的 RTL 时，工程师通常会同时面对三类问题：

1. 这段波形在协议层面是否合法？
2. 如果不合法，究竟违反的是握手、事务匹配、burst、顺序还是容量规则？
3. 除了检查现有波形，能否基于同一套规则构造合法激励，并用一个简单的功能节点完成端到端实验？

Protocol Model 为这些问题提供一个形式化验证相关的可执行模型。它用状态迁移系统、值域、
义务和因果偏序表达协议语义。它不是 RTL 仿真器、综合工具、完整 model checker 或 UVM
替代品；它把时钟边沿的引脚观测降低为规范事件，再检查事件之间的状态、数据、数量和
因果关系。

当前版本处理的是**有限 trace**：一段已经结束或被截断的观察记录。它可以立即确认安全
违规；如果一个响应尚未到来且没有超时或结束标志，则应报告“证据不足”，而不是武断地判错。

## 2. 心智模型

```text
raw pin samples
    │  VALID / READY / address / data / reset ...
    ▼
protocol monitor
    │  successful handshakes and phase transitions
    ▼
canonical events ──► obligations and causal edges ──► verdict + evidence
    ▲                                                    │
    │                                                    ▼
VirtualDut ◄──────────── verification Project ─── waveform / graph / HTML
```

### 2.1 采样与事件

**采样**是一个周期的可见信号值。以 ready-valid 为例，一条采样包含周期号、`VALID`、
`READY` 和 payload。采样本身不等于一次传输。

**规范事件**是模型确认发生的协议动作。例如仅当 `VALID && READY` 时，ready-valid monitor
才发出一条 transfer event。这个区分很重要：握手稳定性、reset 和 APB phase 属于采样层；
请求与响应的匹配、burst beat 数和顺序属于事件层。

### 2.2 Trace、因果与并发

trace 是有限事件集合及其关系。终端输出可能是按发生顺序排列的一条日志，但模型还保存
“必须先于”的因果边。例如：

```text
AR accepted → creates four R-beat obligations
R beat 0    → must precede R beat 1 of the same burst
final R     → discharges the request's final obligation
```

两件事没有因果边，只表示当前模型没有要求先后顺序；这不自动等于它们在所有条件下独立。
“未建模”“无必要顺序”和“允许同周期发生”是不同的结论。

### 2.3 义务与三值结论

**义务**是由某个事件创建、由后续事件履行的责任。AXI4 read request 创建 `ARLEN + 1`
个 read-data beat 的义务；`RLAST` 只能出现在最后一个 beat。

验证结果有三种：

| 结论 | 含义 |
|---|---|
| `PASS` | 当前有限 trace 满足已经实现的规则；不表示未来任意延伸都合法。 |
| `FAIL` | 已观察到无法被未来事件修复的违规，例如 stall 期间 payload 改变。 |
| `INCONCLUSIVE` | 仍有未完成义务，且 trace 没有提供结束、超时或不可能完成的证据。 |

### 2.4 Protocol、VirtualDut 与 Project

| 对象 | 责任 | 不负责什么 |
|---|---|---|
| Protocol | 定义一条链路允许哪些采样和事件关系 | 设备为何发起操作、RAM 应返回哪个数据 |
| ProtocolInstance | 在 Project 网络中命名并绑定一个基础或派生协议 | 重新实现协议规则 |
| VirtualDut | 在合法协议行为中接收、响应或转换功能动作 | 重新定义总线规范 |
| Project | 实例化链路、VirtualDut、case 和报告 | 变成新的协议实现层 |

例如，AXI4 本身不规定 RAM 对某地址必须返回什么数值；这是 memory VirtualDut 或被测 DUT
的功能合同。反过来，memory 选择延迟多少周期回复，也不能违反 AXI 的 handshake 和响应
义务。

## 3. 目录与扩展边界

```text
protocol_model/
├── core/          事件、状态迁移、fault 和 verdict 的公共接口
├── domains/       payload 值域与 event schema
├── patterns/      ready-valid、reset、two-phase、quiet 等通用机制
├── semantics/     cardinality、obligation、correlation 等事务关系
├── protocols/     AXI4、APB3/APB4、ready-valid 的具体规则
├── virtual_dut/   可复用 source、sink、function responder 原语
├── projects/      可以直接运行的验证实验
└── evidence/      WaveDrom、Graphviz、文本和 HTML 报告
```

一个可复用的状态机或事件转换应放在 `core/` 或 `patterns/`；包含 AXI 字段名的规则应放在
`protocols/axi4/`；只有在至少两个 Project 中独立复用的功能节点才应从 Project 提升到
`virtual_dut/`。这样可以避免把某个 testbench 的临时策略误写成协议规则。

## 4. 安装与运行

### 4.1 依赖

Python 模型目前只依赖 Python 标准库。生成 SVG 波形需要 Node.js 和 `wavedrom`；生成
因果图和网络图需要系统安装 Graphviz 的 `dot`。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
npm ci

# Ubuntu/Debian 如未安装 Graphviz：
sudo apt-get install graphviz
```

### 4.2 运行 Project

```bash
.venv/bin/python -m protocol_model ready-valid-sink
.venv/bin/python -m protocol_model apb
.venv/bin/python -m protocol_model axi-read-network
.venv/bin/python -m protocol_model axi-read-interleave
```

默认输出位置：

```text
out/prj_ready_valid_sink/01/report.html
out/prj_apb_compare/01/report.html
out/prj_axi4_read_bridge/01/report.html
out/prj_axi4_read_interleave/01/report.html
```

`out/` 是运行产物，未被 Git 跟踪，可删除后重新生成。每次运行至少生成 `manifest.json`、
`constraints.json`、`constraints.md`、`trace.json` 和 `report.html`；可视化源文件放在
`sources/`，SVG 放在 run 根目录。需要保存到别处时：

```bash
.venv/bin/python -m protocol_model axi-read-interleave --sim-dir /tmp/axi-read-run
```

还可运行更小的协议 witness：

```bash
.venv/bin/python -m protocol_model waveform --channel AR
.venv/bin/python -m protocol_model read-transaction
.venv/bin/python -m protocol_model write-transaction
.venv/bin/python -m protocol_model constraint-witness
.venv/bin/python -m protocol_model axi-read-interleave
.venv/bin/python -m protocol_model apb --transactions 1
```

`axi-read-interleave` 的运行目录包含 HTML/Markdown 约束报告，以及 `waveform.svg`、
`network.svg` 和 `causality.svg` 三份可视化证据。

## 5. 如何读取证据

### 5.1 波形图

波形图展示的是采样层：每一列是一个周期，`VALID && READY` 表示该周期完成一次传输。未被
本 Project 使用且被设置为 quiet 的端口会隐藏，以免大量恒定信号遮挡有效信息。

波形适合回答“哪一周期发生了什么”。它不单独表达整个事务的匹配关系。

### 5.2 网络图

网络图展示 Project 的组件与连接，例如 source、protocol link、bridge、responder 和 sink。
它适合回答“这次验证中谁在驱动、谁在终止、谁在转换协议行为”。网络不是一个全局固定包：
它属于具体 Project，因为 case、节点和连接由验证计划决定。

### 5.3 因果图

因果图的节点是规范事件，边表示必须先发生的依赖，例如 request 创建 response obligation，
或上游事件导致 bridge 的下游事件。它适合回答“为什么这个响应合法”“哪条依赖被破坏”。

因果边不是单纯的屏幕先后顺序，也不是总线信号的物理布线。

### 5.4 违规证据

一个有效的负例只破坏一条目标规则。例如 ready-valid 负例保持 `VALID`，但在 `READY=0`
期间改变 payload；报告应能指向 payload-stability 规则，而不是产生模糊的总失败。

开发规则时应优先提供以下闭环：

```text
规范要求 → 模型元素 → 合法 witness → 单点 mutation → rule id + waveform/graph
```

## 6. 当前协议覆盖

### 6.1 ready-valid 与 APB

ready-valid 模式实现成功握手、stall 时 `VALID` 与 payload 稳定，以及 reset epoch。APB3/APB4
实现 SETUP/ACCESS 转换、`PREADY` wait、`PSLVERR`，并处理 APB4 的 `PSTRB` 和 `PPROT`。

`QuietConstraint` 提供三种观测策略：

| 模式 | 含义 |
|---|---|
| `IGNORE` | 本次不观察该端口；不能据此声称它合法。 |
| `STABLE` | 第一次采样建立基线，之后变化即失败。 |
| `TIED` | 每次采样都必须等于指定常量。 |

### 6.2 AXI4

当前 AXI4 模型涵盖：五通道 ready-valid、reset、AR/R beat cardinality、AW/W ordered join、
write response obligation、部分 per-ID ordering、`WLAST`/`RLAST`、burst 地址几何、WRAP
约束、4KB boundary 和 WSTRB byte lane。

读交织实验位于独立的 `prj_axi4_read_interleave` Project。它从基础 AXI4 `ProtocolSpec`
派生 read-only 约束，只开放 ID 1/2，将 `ARLOCK/ARCACHE/ARPROT/ARQOS/ARREGION` 绑零，
并要求 `AW/W/B` 保持 quiet。输入 VirtualDut 发出两个 AR，输出 VirtualDut 交织生成 R beat；
不同 ID 可以交织，相同 ID 必须完成最老的 pending burst。详细规则与缺口见
[AXI4 读交织约束报告](axi4_read_interleaving_report.md)。

它尚未涵盖 AXI exclusive、完整 USER/capability 语义、完整跨 ID ordering、真实 arbitration
和外部 trace 文件解析。模型验证通过只表示这段 trace 符合已实现的规则，不表示已覆盖整份
AXI 规范。

## 7. VirtualDut 方法

`virtual_dut/` 提供三种最小构造块：

| 构造块 | 行为 |
|---|---|
| `ScriptedSource` | 按设定顺序发射输入动作。 |
| `Sink` | 消费已被协议接受的动作，可保留记录用于诊断。 |
| `FunctionResponder` | 用 Python 函数将一个输入动作映射为零个或多个输出动作。 |

一个 VirtualDut 可以是简单终端，也可以是具有功能状态的 reference model。例如测试 FPU 时，
可将 SoftFloat、C/C++ 模型或 Python 位精确模型包装成 responder；Project 负责把协议事件
转换为 FPU 请求，并把 DUT 响应与参考结果按 tag 或因果关系对齐。

不要把 handshake、burst 或 port ownership 规则藏进 reference function；这些属于 Protocol。
也不要把具体 Project 的临时 bridge 立即放进公共库；只有确实复用后才提升。

## 8. 新增协议或 Project 的建议流程

1. 写下可观察的协议要求，并区分 shape、逐周期 safety、事务因果和功能行为。
2. 定义 payload 的值域与规范事件；不能表示的信号应明确标记为未覆盖，而不是默认允许。
3. 使用通用 pattern 或 `SemanticComponent.step(state, action)` 表达状态迁移。
4. 为 request/response、beat 数、资源上限或顺序关系添加语义组件。
5. 先构造一个合法 witness，再构造只破坏一项条件的 negative witness。
6. 若需要端点行为，先在 Project 内实现 VirtualDut；确认跨 Project 可复用后再抽象。
7. 输出波形、网络图或因果图，使每次结论都可复查。

Project 的规范组网顺序是：引用 `protocols/` 中的基础 `ProtocolSpec`；创建一个或多个具名
`ProtocolInstance`；可选地用 `ProtocolDerivation` 添加本例约束；连接 VirtualDut；最后运行
trace 并发布证据。Project 不应在自身或 CLI 中重新定义 AXI/APB/ready-valid 语义。

Project 私域 profile 和 `ProtocolInstance` 的所有权、命名与禁止共享规则见
[ProtocolInstance 管理](architecture/protocol-instance-management.md)；运行报告的目录契约见
[运行证据管理](architecture/evidence-management.md)。

## 9. 已知限制与路线

当前没有 VCD/FSDB/UVM adapter，因此还不能直接读取真实 DUT 仿真数据库。也没有通用网络
elaboration、动态仲裁、公平性/死锁分析、可配置延迟/backpressure 以及具有读写历史的
memory VirtualDut。

下一步优先级是：定义 canonical event JSON 与外部 trace adapter；为 VirtualDut 增加
memory/register state 与明确合同；在多个 Project 出现相同需要后，再提炼通用 topology、
arbitration 和资源分析机制。
