# Protocol Model

Protocol Model 使用可组合的可执行语义描述总线、协议接口、虚拟 module 和通信网络。工程中的
“自底向上”表示代码可以从较小的语义构件组合出较大的模型；它不表示所有协议都共享一条从
Link 到 System 的协议栈。

```text
构造依赖                 判定作用域                  表示与运输

semantics / patterns     event                       operation
          │                 ↓                            ↑ realized by
          ├────────────  interface-local             transaction lifecycle
          │                 ↓                            │ correlates
          ├────────────  VirtualDut/module               ▼
          │                 ↓                         message → packet → flit
          └────────────  SystemProtocol                           → pin/frame
```

三列描述不同问题：第一列是代码复用关系，第二列回答“一条规则至少需要观察多大范围”，第三列回答
“通信内容以什么形式被编码和运输”。AXI、TileLink、CHI 等具体标准是跨越这些坐标的协议族切片，
不整体归属于其中某一层。详细决定见[通信建模的作用域、表示与运输](docs/architecture/communication-scope-and-transport.md)。

## 公共术语

| 名称 | 含义 |
|---|---|
| `InterfaceProtocol` | 一个逻辑接口连接内可判定的通信合同，例如 AXI4 channel bundle 或 TileLink interface |
| `VirtualDut` | 一个具体、具名、但由软件模型或代理实现的虚拟 DUT/module |
| `InterfaceConnection` | 将一个完整接口合同的 roles 绑定到具体 module ports 的连接实例 |
| `SystemProtocol` | 多个 `VirtualDut`、接口连接和系统级约束共同定义的全局通信合同 |
| `TransportLink` | 单向 transmitter→receiver hop；只在需要显式描述 flit flow control 时出现 |

公共 API 不使用 `Agent`。规范中的 agent 概念在需要解释 TileLink 等标准时，可以映射到一个
`VirtualDut` 内部拥有协议状态的参与者，但工程对象首先表达 DUT/module。

`SystemProtocol` 不是 `InterfaceProtocol` 的 Python 子类，也不只是同一 alphabet 上“约束更多”的
profile。每条接口投影需要满足对应的 `InterfaceProtocol`；系统整体另外满足路由、身份、资源、
ordering、coherence 和 progress 约束。CHI 的 message、packet、flit 与 Link Credit 则沿表示/运输轴
展开，不能被一个巨型 `InterfaceProtocol` 对象代替。

详细设计见 [SystemProtocol 架构](docs/architecture/system-protocol.md) 和
[VirtualDut 方法论](docs/architecture/virtual-dut.md)。bridge、decoder-mux 与 crossbar 的当前统一
边界见 [AddressFabric VirtualDut](docs/architecture/address-fabric.md)，已实现范围见
[当前实现状态](docs/architecture/implementation-status.md)。有限 FIFO 的接纳、错误完成、丢弃和后续
deadlock 分析边界见[容量、接纳与背压](docs/architecture/capacity-admission-and-backpressure.md)。

面向初次阅读者的入口见 [交互式架构地图](docs/architecture/technical-route/README.md)；其中的总览图可以继续
进入各个建模问题的设计说明，而不把阅读顺序误作协议栈层级。

面向系统学习的工程讲义见 [《从链路到互连：可组合通信协议建模》](book/README.md)。讲义按认知顺序
重述稳定概念，并将架构合同继续留在 `docs/architecture/` 中。

面向分享与演示的入口见 [Showcase 工作区](showcase/README.md)：其中包含
[中文版方法总览](showcase/materials/assets/overview/protocol-model-overview.zh.svg)、
[English overview](showcase/materials/assets/overview/protocol-model-overview.en.svg)、双语 one-pager、演示稿，以及已经生成的
[统一 24 场景 AXI4 示例](showcase/generated/axi4/README.zh-CN.md)，其中每案都提供波形与因果图，两案增加精讲。
系统级入口另有 [AXI4-Lite 单管理端、多从设备地址总线](showcase/generated/system/axi4-lite-single-manager-fabric/README.md)
和 [CHI 两级 XP 路由读取](showcase/generated/system/chi-issue-h-routed-read/README.md)，分别展示传统总线与
显式 transport NoC 两种组网方式。

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

## 快速体验组网示例

下面两条具名命令分别构造并执行一个 AXI4-Lite 地址 fabric 和一个受限 CHI Issue H NoC。前者把同一份
显式星形 topology 同时投影为传统 bus strip；后者使用调用方声明的两个 XP、三跳 REQ 与反向三跳 DAT，
拓扑不固化在协议包中。

```bash
python showcase/demos/system/axi4_lite_single_manager_fabric/run.py
python showcase/demos/system/chi_issue_h_routed_read/run.py
```

发布结果位于 [`showcase/generated/system`](showcase/generated/system/)。这些示例提供可执行的模型级
证据，但不把事件步进图冒充 RTL/VCD 波形，也不据此宣称完整 AXI4 fabric 或完整 CHI/coherence 覆盖。

## 当前已打通的端到端实现

当前代码已经形成六组可组合能力：

- **语义与观察**：typed event/schema、constraint/resource/obligation、可组合 fragment、`AtomicFrame`、
  ready-valid/reset/quiet 与异步四相握手 observation；
- **接口协议**：AXI4、AXI4-Lite、AXI4-Stream、AHB-Lite/AHB5、APB3/4/5 和受限 ACE-Lite
  interface profile，包括相应 transaction lifecycle 与定向生成/观察能力；
- **VirtualDut**：typed port、attachment/binding、AddressSpace、有限 queued responder、Sensor FIFO、
  memory-copy engine、interrupt controller、bridge 和 scheduled address crossbar；
- **事务转译**：typed stage/plan、fan-out/completion ledger、capacity lease，以及覆盖 AXI4、AXI4-Lite、
  AHB 和 APB address family 的统一 serial bridge composition root；
- **系统与 CHI transport**：统一 interface/transport topology、address contract/resolution、原子 BLOCK 回滚，
  以及 CHI Issue H 的 REQ/RSP/DAT hop、有限 router、direct read 和 Retry/P-Credit 最小闭环；
- **证据与展示**：因果偏序、系统 trace、manifest v4、拓扑/波形/因果图投影和显式发布脚本。

这段只给出导航级摘要。准确 profile、尚未实现项和下一落点集中记录在
[实现状态](docs/architecture/implementation-status.md)；产物边界见
[运行产物、可视化与文档发布](docs/architecture/run-output-management.md)。

编辑循环先运行小型代表集和受影响职责的 target：

```bash
make smoke
make test-target TARGET=chi
```

完成代码变更前运行全量维护基线：

```bash
make test
```

可用 target、integration、迁移哨兵与 release 测试入口见
[测试说明](tests/README.md)。测试用于检查所修改的语义路径，不以 case 数量替代协议覆盖或架构进度。
