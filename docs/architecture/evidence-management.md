# 运行证据与文档管理

## 三类文件

仓库文件按责任分为三类，不能互相混放：

| 类型 | 位置 | Git | 内容 |
|---|---|---|---|
| 可维护源码 | `protocol_model/projects/prj_*/` | 跟踪 | project、constraints、VirtualDut、evidence view、simulation plan |
| 手写规范文档 | `README.md`、`docs/` | 跟踪 | 稳定概念、架构决策、约束边界、使用方法 |
| 可再生运行证据 | `out/<project>/<run-id>/` | 忽略 | trace、约束快照、SVG、HTML、manifest |

Project 源码目录不再保存 `sims/`、一次性报告或图形中间文件。`docs/images/` 只接收确实要
长期版本化引用的人工挑选快照，不能当日常输出目录。

## Run bundle 契约

每个 Project 通过统一 `ArtifactBundle` 发布一次运行：

```text
out/<project>/<run-id>/
├── manifest.json       运行身份、verdict、case、实例、state、产物哈希
├── constraints.json    机器可读的 SPEC / PROFILE / TEST 约束表
├── constraints.md      同一约束表的人工审阅视图
├── trace.json          规范事件、采样或 milestone 与因果边
├── report.html         人工入口
├── network.svg         Project 实际组网
├── waveform*.svg       采样层证据
├── causality*.svg      事件依赖证据（若适用）
└── sources/            WaveJSON 和 Graphviz DOT 源文件
```

`report.html` 是浏览入口，`manifest.json` 是机器入口。manifest 中每个已登记产物都有相对路径、
media type 和 SHA-256；复制一个 run 目录时，证据闭包不会依赖 Project 源码目录里的临时文件。

## 约束报告纪律

每条约束证据必须带以下字段：

- `id`：稳定规则标识；
- `source`：`SPEC`、`PROFILE` 或 `TEST`；
- `target`：受约束的 link、channel、field 或 mutation；
- `rule` 与 `foundation`：自然语言规则和对应模型元素；
- `status`：implemented、missing、verified 或 mismatch；
- `instances`：Project 限定的实例身份；
- `witness`：若为 test，给出实际触发规则或观察结果。

基础协议 requirement 和 Project profile 从 `ProtocolInstance` 自动提取；simulation 只补充
legal/negative witness，不手工重抄基础约束表。这样协议模型改动后，下一次运行会自然产生
新的约束快照。

## Project 源文件约定

一个 Project 可按需要使用以下文件，未使用的文件不必为了形式创建：

| 文件 | 责任 |
|---|---|
| `project.py` | 生命周期、实例化、case 执行、verdict |
| `constraints.py` | Project 私域 profile 配置和派生函数 |
| `virtual_dut*.py` | 本实验功能节点，不重复协议规则 |
| `evidence.py` | 报告视图、网络图与因果图的纯格式化函数 |
| `simulation.py` | 运行计划并通过 `ArtifactBundle` 发布完整证据 |
| `__init__.py` | 仅导出稳定运行入口和必要类型 |

仓库根 `projects/` 下只保留生命周期公共设施和 `prj_*` 包；协议派生类型属于
`protocols/spec.py`，通用证据发布属于 `evidence/`，CLI 只解析参数并调用 Project。

## 更新流程

修改协议或 Project 后按以下顺序收尾：

1. 更新稳定的手写规则说明；
2. 运行受影响 Project；
3. 检查 command exit code 和 manifest verdict；
4. 审阅 constraints 中是否出现意外 `missing`/`mismatch`；
5. 打开或检查 SVG/HTML 引用是否都存在；
6. 只有需要长期引用时，才把某个 SVG 复制为 `docs/images/` 快照。
