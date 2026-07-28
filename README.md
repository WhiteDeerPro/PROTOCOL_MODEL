# Protocol Model

Protocol Model 是一个面向通信协议与片上网络的可执行建模研究原型。它用可组合语义描述
`InterfaceProtocol`、具体 `VirtualDut`、事务表示与 `SystemProtocol`，并从同一次执行生成可复查的
trace、拓扑和诊断证据。

当前项目处于 pre-1.0 technical preview。仓库中的场景证明相应输入和建模边界可执行；它们不等同于完整
规范覆盖、RTL 仿真结果或芯片实现。

[![Protocol Model 三视图架构地图](docs/architecture/technical-route/overview.svg)](docs/architecture/technical-route/overview.svg)

这张图分别展示代码构造依赖、规则判定作用域和通信表示/运输。完整说明见
[通信建模的三张视图](docs/architecture/communication-scope-and-transport.md)。

## 从这里开始

| 想了解什么 | 入口 |
|---|---|
| 先浏览可执行结果 | [Showcase gallery](showcase/README.md) |
| 理解核心对象与职责边界 | [架构文档](docs/architecture/README.md) |
| 核对当前到底实现了什么 | [实现状态](docs/architecture/implementation-status.md) |
| 查看近期施工顺序 | [技术路线](docs/architecture/technical-route/08-roadmap.md) |
| 查看长期研究方向 | [项目 Roadmap](ROADMAP.md) |

## 精选可执行展示

| 展示 | 主要内容 |
|---|---|
| [AXI4 场景集](showcase/generated/axi4/README.zh-CN.md) | 24 个确定性合法/违规场景；每案连接输入、verdict、波形、因果图和机器结果 |
| [CHI Issue H flow gallery](showcase/generated/chi/issue-h-flow-gallery/README.md) | 5 个实际执行流程；每案连接 resolved XP topology、transaction 时空图、显式因果图与语义事件时间线 |
| [CHI 异构 ring + star](showcase/generated/system/chi-issue-h-heterogeneous-ring-star/README.md) | 非均匀环形骨干、星形叶节点与方向化 exact-route witness |
| [CHI 4×4 mesh](showcase/generated/system/chi-issue-h-four-by-four-mesh/README.md) | 16-router mesh、角到角长路径与 route-table closure witness |

flow gallery 观察 `ReadUnique`、`CleanUnique`、`MakeUnique`、`Evict` Retry 和
`WriteBackFull` 同址 Snoop 组合；两个 topology 示例分别关注异构结构和 mesh 长路径/规模。它们回答的问题不同，
不能用场景数量或节点数量替代协议功能覆盖。

## 快速开始

基础包要求 Python 3.10 或更高版本：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python -c "import protocol_model as p; print(p.__version__)"
```

重建 AXI4 Showcase 还需要 Node.js/npm 和 Graphviz：

```bash
npm ci
dot -V
python showcase/demos/axi4/run.py
```

生成结果写入 [`showcase/generated/axi4`](showcase/generated/axi4/README.zh-CN.md)。普通运行和临时输出
不会改写受版本控制的发布树；具名 Showcase 脚本会在显式调用时替换自己拥有的生成子树。

## 建模边界

- `InterfaceProtocol` 判断一个完整逻辑接口内的合同；
- `VirtualDut` 表示一个具体 module，其 backend 可以是本地模型、外部 RTL/RPC 代理或更大的封装系统；
- `SystemProtocol` 组合多个 module、接口、transport hop 与系统合同；
- transaction 负责 operation 生命周期与 correlation；message、packet、flit 和 pin/frame 按协议与观察目标
  选择性展开。

准确 profile、明确缺口和阶段边界集中记录在
[实现状态](docs/architecture/implementation-status.md)，不从示例数量推断规范覆盖率。
