# Protocol Model

Protocol Model 是一个**形式化验证相关**的实验项目：它用可执行状态机、带类型事件空间、
事务义务和因果偏序来形式化描述通信协议。模型把引脚或总线采样转换为协议事件，再检查
一段有限 trace 是否违反协议规则。

当前工程属于形式化建模与运行时验证基础设施，还不是完整的定理证明器或 RTL model
checker；没有结构证据时，它不会声称已经证明真实 RTL 的所有执行都满足协议。

它面向的不是 RTL 生成，也不是替代 UVM。它解决的是协议验证中经常反复出现的问题：
同一条规则既需要生成合法激励，也需要检查 DUT 观测；违规时还应指出哪条规则、哪几个
事件以及它们的依赖关系导致了失败。

当前提供 AXI4、APB3/APB4 和 ready-valid 的形式化验证演示工程及可执行 VirtualDut。
这些协议用于验证建模方法；项目主体是从协议要求构造可执行语义模型，再将模型实例化为
验证网络的一般流程。

## 它能做什么

- 从已建模的规则构造有限、合法的协议 trace；
- 验证已有 trace，给出规则标识、违规位置和三值结论（通过、失败、证据不足）；
- 记录请求、响应、burst、join 等行为之间的因果边，而不只保留线性日志；
- 将 Protocol 与 VirtualDut 组合成小型验证 Project，输出波形、网络图、因果图和 HTML 报告；
- 对 AXI4 检查五通道握手、stall 稳定性、reset、burst、4KB、WSTRB、读写义务及部分 ID ordering；
- 提供 AXI4 跨 ID 读交织约束场景，区分协议规则、endpoint profile 与 quiet 测试配置；
- 对 APB3/APB4 检查 SETUP/ACCESS 两阶段、PREADY wait、PSLVERR 和 APB4 扩展字段。

## 核心思路

```text
pin sample / external trace
            │
            ▼
protocol monitor ──► canonical event ──► obligation + causal relation ──► verdict
            ▲                                                        │
            │                                                        ▼
       VirtualDut ◄──────── Project plan ◄──────── waveform / graph / report
```

- **采样（sample）**是某个周期观察到的引脚值，例如 `VALID`、`READY` 与 payload。
- **规范事件（canonical event）**是协议确认发生的一次传输，例如一次 `AR` 握手；它不是原始信号的逐位拷贝。
- **有限 trace**是一组已观察事件及其因果关系。它可被线性记录，但模型不会把日志顺序误当成唯一的协议顺序。
- **义务（obligation）**是事件创建的后续责任。例如 AXI `AR` 创建若干 `R` beat 的义务，最后一拍必须带 `RLAST`。
- **VirtualDut** 是功能性验证节点；它可以接收、响应或转换合法协议行为，但不是 RTL 生成器。
- **Project** 把协议链路、VirtualDut、激励和预期结果组织成一个可运行的验证实验。

详细定义、运行方法和边界见 [用户手册](docs/manual.md)。

## Protocol Model 建模流程

建模从协议要求出发：先用类型化值域和 `EventSpace` 定义可观察事件，再将逐周期行为写成
状态迁移系统，并用 cardinality、correlation、obligation 与因果偏序表达跨事务约束；这些
元素最终 elaboration 为不可变 `ProtocolSpec`，供 Project 派生 profile、实例化并生成运行结果。

```text
domain/schema → observation automaton → transaction relation → ProtocolSpec
      → Project profile/instance → legal & negative trace → report
```

因此 AXI4、APB 等只是这条通用建模流程在具体协议上的末端演示，而不是框架的起点。

## 统一的 Project 组网方式

所有验证例子遵循同一条路径：Project 从 `protocols/` 引用基础协议，通过
`ProtocolInstance` 给每条网络 link 命名；需要收窄能力时，先用 `ProtocolDerivation` 和
`ConstraintRecord` 生成带 provenance 的派生 spec。随后才连接 VirtualDut、运行 trace 并
生成可视化结果。

```text
protocols/<name>/ base ProtocolSpec
              │ instantiate / optionally constrain
              ▼
      named ProtocolInstance(s) ◄──► VirtualDut(s)
              │ run observations/events
              ▼
       trace + waveform + network + causality + report
```

当前维护中的 Project 都使用该流程：

- `prj_ready_valid_sink`：一个 ready-valid 协议实例连接 Source/Sink；
- `prj_apb_compare`：APB3/APB4 两个基础协议实例及版本对比；
- `prj_axi4_read_bridge`：AXI-A/AXI-B 两个 AXI4 实例连接 bridge/responder；
- `prj_axi4_read_interleave`：一个施加具体 ID/quiet 约束的派生 AXI4 实例。
- `prj_axi4_scenarios`：manager source 与 subordinate responder 直接连接的 37-case AXI4 批量实验。

运行全部 Project 后，`out/index.html` 会生成按复杂度排列的本地功能导览；仓库同时跟踪一份
[Project 功能导览](docs/project-guide.md)，并保存该导览引用的 SVG 图表。

## AXI4 跨 ID 乱序读取

当前主线 Project 从通用 AXI4 `ProtocolSpec` 派生 read-only profile。输入 VirtualDut 依次
发出 `AR1、AR2`，输出 VirtualDut 按 `R2、R1、R2-last、R1-last` 回复，使后发 ID2 先
响应且先完成。Project 同时验证同 ID 不得越序、RID active set、sideband quiet 和写通道
quiet。

这个需要具体约束的 Project 使用：

```text
base ProtocolSpec
      + Project ConstraintRecord[]
      ↓ ProtocolDerivation
immutable derived ProtocolSpec
      + two VirtualDuts
      ↓
cases/<case>/{waveform,causality,trace} + network.svg + HTML report
```

从单 Project 入口运行后，可查看
`protocol_model/projects/prj_axi4_read_interleave/out/01/` 下的 `cases/`、`network.svg`、
`constraints.md` 和 `report.html`。这些是可重新生成的运行结果，不进入 Git。

## 快速开始

Python 模型本身只使用标准库；WaveDrom 用于生成 SVG 波形，Graphviz 用于生成关系图。

```bash
python3 -m venv .venv
npm ci
.venv/bin/python -m protocol_model run-all
```

WaveDrom 由 `npm ci` 安装；关系图还需要系统中存在 Graphviz `dot`。运行完成后打开统一入口
`out/index.html`。单个 Project 也可以通过自身目录内的 `run.sh` 启动：

```bash
.venv/bin/python -m protocol_model run-all

# ready-valid Project
.venv/bin/python -m protocol_model ready-valid-sink

# APB3/APB4 ProtocolInstance Project
.venv/bin/python -m protocol_model apb

# 双链路 AXI4 bridge Project
.venv/bin/python -m protocol_model axi-read-network

# 带具体约束的 AXI4 乱序读取 Project
.venv/bin/python -m protocol_model axi-read-interleave

# 无 bridge 的 AXI4 source/responder 批量场景
.venv/bin/python -m protocol_model axi-scenarios
```

每个 Project 是一个 run bundle，legal 与 negative 是 bundle 内的独立 case；各自的 trace、
波形和因果图写入 `cases/<case>/`，共享的拓扑、约束、manifest 和总报告保留在 run 根目录。
单独运行时，报告默认写入对应 Project 的 `out/01/report.html`；`run-all` 则汇总到
仓库根 `out/<project>/01/report.html`。完整命令说明见
[用户手册：运行实验](docs/manual.md#运行实验)。

## 后续工作

下一阶段优先建设可组合语义组件、typed protocol network、wait-for/deadlock 诊断和 stateful
VirtualDut；随后接入外部 trace，并用 UART、I²C 与 CDC 场景检验时间、多驱动和跨时钟抽象。
完整的边界判断、依赖关系和版本规划见 [Roadmap](ROADMAP.md)。

## 文档与贡献

- [用户手册](docs/manual.md)：术语、架构、运行、读图方式、扩展方法和当前边界；
- [ProtocolInstance 管理](docs/architecture/protocol-instance-management.md)：基础协议引用、私域 profile 与实例所有权；
- [Project 与运行结果管理](docs/architecture/run-output-management.md)：Project、输出目录与文档素材的边界；
- [Roadmap](ROADMAP.md)：引擎、网络、VirtualDut、新协议、CDC 与外部接入的工作路径；
- [文档入口](docs/README.md)：当前有效文档的索引；
- [CHANGELOG](CHANGELOG.md)：版本变更；
- [MIT License](LICENSE)：使用许可。

开发新规则时，建议提供一条明确的规则说明、一条合法 witness、一条只破坏该规则的
negative witness，以及能解释结论的波形或因果图。这样验证结果不会只停留在“测试通过”。
