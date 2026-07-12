# Development Workflow

## 派生协议

```text
S0 研究规范与版本
 → S1 列出 requirement、来源和非目标
 → S2 识别可复用 foundation
 → S3 elaboration 为 ProtocolSpec
 → S4 lowering 为 per-link ProtocolSession
 → S5 同一 SemanticComponent.step 支持构造与验证
 → S6 在 Project 中接入 VirtualDut 和验证计划
```

目录责任：

```text
domains/       字段值域和EventSpace
core/          SemanticComponent、step、fault、verdict
semantics/     token、cardinality、correlation
patterns/      ready-valid、two-phase、reset、quiet
protocols/     规范字段、规则和ProtocolSpec
virtual_dut/   功能节点、bridge、endpoint策略
projects/      case、验证计划、生命周期和专用证据
evidence/      真正跨项目复用的renderer
```

协议包不得包含 VirtualDut 功能、测试 case、HTML 或项目 topology。Project 可以实例化
任意协议和 VirtualDut，但不能改变协议接受语言。

## Requirement contract

每条协议规则至少记录：

```text
name
rule
foundation
implementation status
source/provenance
```

规则的可执行 witness 应包含一个正例和一个单点 mutation，并报告具体 rule id。随机测试
数量不是语义证据。

## 生成与验证

构造器可以提出候选 action，但候选必须经过与外部 trace 相同的
`SemanticComponent.step(state, action)`。禁止维护 `generate_legal_axi()` 与
`check_axi()` 两套协议规则。

## 新 Project

一个用户验证项目建立独立包：

```text
projects/prj_<protocol-or-purpose>_<dut-or-goal>/
├── __init__.py
├── project.py      case、inventory、lifecycle
├── network.py      该计划的link/topology/runtime（需要时）
└── evidence.py     该项目专用图和HTML（需要时）
```

只有至少两个 Project 证明某段机制完全相同，才把它提升到通用层。

## 最小验证原则

每次执行前明确要求：

- 哪个合法行为必须出现；
- 哪个 mutation 必须触发哪个 rule；
- 哪些状态应创建、消耗或恢复；
- 哪张波形/因果图是最终证据。

默认不运行大规模回归；发布里程碑再进行完整测试。

Project simulation 默认写入各 Project 包根目录的 `sims/<run-id>/`，并允许调用者指定目录；`sims/` 已加入
`.gitignore`。删除 simulation 目录不影响任何协议、VirtualDut 或 Project 定义。直接调用
`Project.run_case()` 默认不写文件，调用 Project 自己的 `build_simulation()` 才发布结果。
