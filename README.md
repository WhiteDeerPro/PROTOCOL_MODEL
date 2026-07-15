# Protocol Model

Protocol Model 采用不保留 v0.1 API 的语义架构。当前版本把用户通信协议分成两个明确
作用域，并以具体的虚拟 DUT 连接它们：

```text
基础约束 → SemanticFragment → LinkProtocol
                                  │
                    concrete VirtualDut modules
                                  │
                                  ▼
                            SystemProtocol
                                  │
                              elaborate
                                  ▼
                       ElaboratedSystemProtocol
```

## 公共术语

| 名称 | 含义 |
|---|---|
| `LinkProtocol` | 单条逻辑接口或链路上的局部协议，例如 ready-valid、AXI4、TileLink link |
| `VirtualDut` | 一个具体、具名、但由软件模型或代理实现的虚拟 DUT/module |
| `SystemProtocol` | 多个 `VirtualDut`、多条 `LinkProtocol` 和系统级约束共同定义的全局通信协议 |

公共 API 不使用 `Agent`。规范中的 agent 概念在需要解释 TileLink 等标准时，可以映射到一个
`VirtualDut` 内部拥有协议状态的参与者，但工程对象首先表达 DUT/module。

`SystemProtocol` 不是 `LinkProtocol` 的 Python 子类，也不只是同一 alphabet 上“约束更多”的
profile。它的 alphabet 包含多个 link 和 DUT 状态；正确关系是每条链路投影满足对应的
`LinkProtocol`，同时整体满足额外的路由、资源、ordering、coherence 和 progress 约束。

详细设计见 [SystemProtocol 架构](docs/architecture/system-protocol.md) 和
[VirtualDut 方法论](docs/architecture/virtual-dut.md)。bridge、decoder-mux 与 crossbar 的当前统一
边界见 [AddressFabric VirtualDut](docs/architecture/address-fabric.md)。历史方法的吸收与退休记录见
[v0.1 方法迁移审计](docs/architecture/migration-audit.md)。

面向初次阅读者的入口见 [交互式架构地图](docs/architecture/technical-route/README.md)；其中的总览图可以继续
进入每一层的设计说明，而不把所有解释压缩在一张图里。

面向分享与演示的入口见 [Showcase 工作区](showcase/README.md)：其中包含
[中文版方法总览](showcase/materials/assets/overview/protocol-model-overview.zh.svg)、
[English overview](showcase/materials/assets/overview/protocol-model-overview.en.svg)、双语 one-pager、演示稿，以及已经生成的
[统一 24 场景 AXI4 示例](showcase/generated/axi4/README.zh-CN.md)，其中每案都提供波形与因果图，两案增加精讲。

## 快速体验 AXI4 示例

需要 Python 3.10 或更高版本、Node.js/npm，以及能够提供 `dot` 命令的 Graphviz。下面的命令安装当前
Python package 和锁定的 WaveDrom 依赖，然后显式重建统一示例；不会写入普通运行目录 `out/`。

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
npm ci
dot -V
python showcase/demos/axi4/run.py
```

结果写入 [`showcase/generated/axi4`](showcase/generated/axi4/README.zh-CN.md)。一个导航页串起全部 24 个
场景；每案都有波形、因果图和机器结果，全套场景共享一张点到点结构图。6 个 frame 输入场景使用
`AtomicFrame` 展开 AXI ready/valid 与 `ARESETn`，18 个 event 输入场景使用明确标注的
`CanonicalEvent` 顺序视图；两个重点场景从前一类中增加详细讲解。这些都是模型生成的证据，不是
RTL/VCD 采样。

## 当前已打通的端到端实现

新包已经提供：

- scope-aware `SemanticConstraint`、resource 和 obligation 声明；
- `SemanticFragment` 的组合及实例 namespace；
- `AtomicFrame` observation 边界、ready-valid lowering 和 link-local reset epoch；
- `protocol_model.link.amba` 下按 AXI/AHB/APB/ACE/CHI 分组的 LinkProtocol 家族；AXI4 五通道当前实现范围包含 read interleave、AW/W FIFO join、
  B completion、link-local exclusive、narrow/unaligned、状态驱动生成及 `AtomicFrame` observation；
- 原生 AXI4-Lite `LinkProtocol`、固定语义到 AXI4 的显式 embedding，以及 AXI4-Stream 的 byte qualifier、
  packet/interleave、Continuous_Packets profile、生成和 observation；
- AHB-Lite address/data pipeline、burst 与两拍 ERROR observation，以及独立 APB3/APB4/APB5
  package；APB5 包含可配置 user/wakeup/RME 语义，parity 在当前 profile 中关闭；
- ACE-Lite ordinary-data LinkProtocol：AXI4 五通道事务核加 domain/snoop/bar 约束，builder
  名称保留当前 barrier/CMO 边界；
- `LinkProtocol` 定义、单调 `refine()`、event prohibition 和 bounded resource profile；
- executable event domain、`LinkSession` 和 keyed `CardinalityMonitor`；
- 具名 `VirtualDut`、typed `ProtocolPort`、`PortAttachmentBinding`/`VirtualDutBuilder`、同步
  port-facing model 和 AddressSpace reference region；
- integration 层中的 APB-family address completer/requester attachment、passive AddressSpace endpoint，以及单入口
  decoder/response-mux AddressFabric VirtualDut；
- APB/AHB/AXI 的 idle source 与显式 blackhole sink 空端点；
- `SystemProtocol` topology、link ownership 与 boundary elaboration；
- 单 link point-to-point 提升，以及自动执行 `A → bridge → B` 的 `SystemSession`；
- 将一个 `SystemProtocol` 封装成 `VirtualDut`，用于 chiplet、封装、板级和更大系统的递归组合；
- 严格因果偏序的 reachability、concurrency、ancestor 和拓扑序查询；
- 与协议无关的运行产物存储、manifest v3、系统拓扑/trace 可视化及显式文档发布。

产物和可视化分层设计见
[运行产物、可视化与文档发布](docs/architecture/run-output-management.md)。

开发时如需检查当前架构，可按修改风险选择定向测试，或显式运行当前测试集：

```bash
make smoke
```

## 历史实现

v0.1 实现已在方法审计后退出当前源码树，不再作为兼容包或回归入口。需要追溯旧行为时使用版本控制；
当前迁移边界见 [新架构状态](docs/architecture/migration-status.md)。
