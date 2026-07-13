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
元素最终 elaboration 为不可变 `ProtocolSpec`，供 Project 派生 profile、实例化并生成证据。

```text
domain/schema → observation automaton → transaction relation → ProtocolSpec
      → Project profile/instance → legal & negative trace → evidence
```

因此 AXI4、APB 等只是这条通用建模流程在具体协议上的末端演示，而不是框架的起点。

## 统一的 Project 组网方式

所有验证例子遵循同一条路径：Project 从 `protocols/` 引用基础协议，通过
`ProtocolInstance` 给每条网络 link 命名；需要收窄能力时，先用 `ProtocolDerivation` 和
`ConstraintRecord` 生成带 provenance 的派生 spec。随后才连接 VirtualDut、运行 trace 并
发布可视化证据。

```text
protocols/<name>/ base ProtocolSpec
              │ instantiate / optionally constrain
              ▼
      named ProtocolInstance(s) ◄──► VirtualDut(s)
              │ run observations/events
              ▼
       trace + waveform + network + causality + report
```

当前四个 Project 都保留并迁移到该流程：

- `prj_ready_valid_sink`：一个 ready-valid 协议实例连接 Source/Sink；
- `prj_apb_compare`：APB3/APB4 两个基础协议实例及版本对比；
- `prj_axi4_read_bridge`：AXI-A/AXI-B 两个 AXI4 实例连接 bridge/responder；
- `prj_axi4_read_interleave`：一个施加具体 ID/quiet 约束的派生 AXI4 实例。

四个 Project 的网络图、波形图、因果图以及一条 34-event 长 trace 见
[可执行实验图册](docs/experiments.md)。图册说明每张图对应的运行命令、验证结论和协议含义。

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
waveform.svg + network.svg + causality.svg + HTML report
```

运行后可查看 `out/prj_axi4_read_interleave/01/` 下的 `waveform.svg`、`network.svg`、
`causality.svg`、`constraints.md` 和 `report.html`。该目录是可再生运行证据，不进入源码树。

## 快速开始

Python 模型本身只使用标准库；WaveDrom 用于生成 SVG 波形，Graphviz 用于生成关系图。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
npm ci

# ready-valid Project
.venv/bin/python -m protocol_model ready-valid-sink

# APB3/APB4 ProtocolInstance Project
.venv/bin/python -m protocol_model apb

# 双链路 AXI4 bridge Project
.venv/bin/python -m protocol_model axi-read-network

# 带具体约束的 AXI4 乱序读取 Project
.venv/bin/python -m protocol_model axi-read-interleave
```

报告统一写入 `out/<project>/01/report.html`，可在浏览器中打开。完整命令说明见
[用户手册：运行实验](docs/manual.md#运行实验)。

## 当前边界与下一步

这个版本是 `v0.1.1` 实验版本，接口和文件组织尚未承诺稳定兼容性。

- AXI4 尚未覆盖 exclusive、全部 USER/capability 语义和完整的跨 ID ordering；
- Project 还没有通用拓扑路由、仲裁、公平性、死锁搜索或可配置 latency/backpressure policy；
- VirtualDut responder 目前可产生确定性 payload，但还不是具有读写历史的 memory model；
- 尚未提供 VCD/FSDB/UVM adapter；因此不能直接检查真实 DUT 的波形文件；
- 下一阶段会先补强事件 JSON、外部 trace adapter、VirtualDut 的 memory/register state，
  再评估可复用的网络 elaboration 抽象。

## 文档与贡献

- [用户手册](docs/manual.md)：术语、架构、运行、读图方式、扩展方法和当前边界；
- [AXI4 读交织约束报告](docs/axi4_read_interleaving_report.md)：ID、quiet 与约束缺口；
- [ProtocolInstance 管理](docs/architecture/protocol-instance-management.md)：基础协议引用、私域 profile 与实例所有权；
- [运行证据管理](docs/architecture/evidence-management.md)：输出目录、manifest、约束和文档纪律；
- [文档入口](docs/README.md)：当前有效文档的索引；
- [CHANGELOG](CHANGELOG.md)：版本变更；
- [MIT License](LICENSE)：使用许可。

开发新规则时，建议提供一条明确的规则说明、一条合法 witness、一条只破坏该规则的
negative witness，以及能解释结论的波形或因果图。这样验证结果不会只停留在“测试通过”。
