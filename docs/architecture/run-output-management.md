# Project 与运行结果管理

这套约定只解决两个实际问题：生成文件不要散落在源码各处，读者能够从固定入口找到结果。
它不是提交前检查制度，也不要求每次修改都重新运行全部实验。

## 目录角色

| 内容 | 位置 | Git | 说明 |
|---|---|---|---|
| 模型实现 | `protocol_model/` | 跟踪 | 协议模型、公共运行设施和 CLI |
| 随软件维护的 Project | `protocol_model/projects/prj_*/` | 跟踪 | 一个可独立运行的实验或场景集 |
| 单 Project 运行结果 | `protocol_model/projects/prj_*/out/<run-id>/` | 忽略 | 从该 Project 的 `run.sh` 产生 |
| 全部 Project 汇总结果 | `out/<project>/<run-id>/` | 忽略 | 由 `run-all` 产生 |
| 说明文档 | `README.md`、`docs/` | 跟踪 | 稳定概念和使用方式 |

这里统一使用“运行结果”或“生成产物”，不把仿真结果泛称为 evidence。`out/` 只是可删除、可重新
生成的工作目录；manifest 是报告导航和程序读取入口，不承担代码合规审计的含义。

## 为什么 Project 目前位于 `protocol_model` 中

`protocol_model` 是本仓库的软件实现包，角色接近一个 Python library 加命令行程序。当前 Project
直接调用这个包的协议类型、运行设施和渲染代码，并由同一个 CLI 发现和批量运行。把这些随软件
共同维护的小型 Project 放在包内，有三个现实好处：

- import 路径和单元边界明确；
- 不需要另一套插件发现或环境配置；
- `python -m protocol_model run-all` 能直接运行维护中的完整集合。

代价是 library 与具体实验在目录视觉上靠得较近。因此这里把 `protocol_model/projects/` 定义为
“随软件发布的内建 Project”，而不是所有未来工程的永久容器。若某个 Project 有独立依赖、独立
版本或大量自有文件，更自然的位置是仓库根 `projects/<name>/`，通过公开 API 使用
`protocol_model`。当前规模下不为目录纯度做一次大搬迁。

## 单 Project 的工作入口

每个 `prj_*` 目录可以放一个很薄的 `run.sh`。它只选择对应 CLI 命令，并把默认结果写到本目录的
`out/01/`；协议行为仍由 Python Project 定义，shell 脚本不复制实验逻辑。

```text
protocol_model/projects/prj_axi4_scenarios/
├── project.py
├── simulation.py
├── virtual_dut.py
├── run.sh
└── out/
    └── 01/
        ├── report.html
        ├── manifest.json
        └── cases/...
```

这种入口适合只处理一个 Project。`run-all` 面向全量运行，将所有 Project 汇总到根 `out/`，并生成
`out/index.html`。两种目录不是两份必须同时保存的结果，
而是单项目工作与全仓汇总两个使用场景。

## 一次运行包含什么

一次运行通常生成：

```text
out/<run-id>/
├── report.html         人工浏览入口
├── manifest.json       文件索引和运行摘要
├── constraints.json    本次采用的约束数据
├── constraints.md      便于阅读的约束表
├── network.svg         Project 组网
├── cases/<case>/       trace、波形和因果图
└── sources/            WaveJSON 和 Graphviz DOT 等可视化源文件
```

合法判例与负例可以是同一次实验中的多个 case，共享拓扑和约束。也可以在研究目的确实不同的时候
拆成两次运行；目录管理不替实验设计作这个决定。

约束表中的 `SPEC`、`PROFILE` 和 `TEST` 用来说明规则来源。`status`、`instances` 和 `witness`
等字段是报告数据，不是一张要求开发者逐项签字的检查表。

## 日常使用

只改某个 Project 时，可直接运行其入口，例如：

```bash
./protocol_model/projects/prj_axi4_scenarios/run.sh
```

需要观察结果时打开同目录 `out/01/report.html`。只有当改动会影响运行行为、正在调查问题，或准备
更新文档示例时，才需要重新生成相应结果。全量回归使用：

```bash
.venv/bin/python -m protocol_model run-all
```

`out/` 中的内容可以随时删除，不提交完整运行目录。
