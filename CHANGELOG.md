# Changelog

## Unreleased — repository hygiene

- 删除旧的 `docs/images/` 手工 SVG 快照、早期设计草稿和 Project 内遗留运行目录。
- 删除绕过 `ArtifactBundle` 的 CLI 文件输出；运行证据只允许进入带 manifest 的 `out/` bundle。

## 0.1.1 — project workflow and evidence management (2026-07-13)

本版本把协议定义、Project 私域约束、网络实例和运行证据整理为一条可审计流程。

### Added

- 新增 AXI4 跨 ID 读交织 Project，以 `AR1、AR2、R2、R1、R2-last、R1-last` 提供乱序完成 witness。
- 新增 APB3/APB4 对比 Project；APB 和 AXI bridge 不再由 CLI 临时重写协议流程。
- 新增 `ProtocolDerivation`、`ConstraintRecord` 和显式 Project owner 的 `ProtocolInstance`。
- 新增统一 `ArtifactBundle`，输出 manifest、约束表、trace、SVG 和 HTML 报告。
- 新增 Project 私域 instance 与运行证据管理文档。

### Changed

- Project 默认运行目录由源码树内的 `sims/` 迁移到仓库根目录 `out/<project>/<run-id>/`。
- `ProtocolInstance.bind()` 现在必须通过 `owner=` 声明 Project 所有者；持久身份采用 `owner/link`。
- Project 生命周期公共类型由 `projects.base` 移至 `projects.lifecycle`。
- 因果关系实现由顶层 `protocol_model.relations` 移至 `protocol_model.engine.relations`。
- APB CLI 统一使用 `--sim-dir`；旧 `--artifacts-dir` 暂时保留为兼容别名。

### Verification

- ready-valid、APB3/APB4、双链路 AXI4 bridge 和 AXI4 读交织四个 Project 均通过可执行 smoke run。
- 每个 run bundle 的产物哈希、HTML 本地引用和 SVG 文档格式均经过一致性检查。
- AXI4 的 `structural_no_comb_path` 继续明确报告为缺失结构证据，未由有限 trace 冒充证明。

### Compatibility

这是一个 pre-1.0 实验版本，模型语义内核仍属于 0.1 系列。直接导入旧 `projects.base`、
`protocol_model.relations`，或不传 `owner` 调用 `ProtocolInstance.bind()` 的代码需要迁移。

## 0.1.0 — experimental foundation

首个实验性里程碑，建立协议语义、trace 和验证 Project 的共同骨架。

- 统一 `SemanticComponent.step(state, action)` 语义接口。
- 提供 AXI4 与 APB3/APB4 的可执行约束、合法 trace 生成和违规 trace 检查。
- 提供 ready-valid 与 AXI4 VirtualDut 验证 Project。
- 输出 WaveDrom 波形、Graphviz 因果图和验证报告。
- 将仿真结果默认放在各 Project 的 `sims/` 目录，并排除生成物与本地环境文件。

本版本 API 和协议覆盖范围仍处于实验阶段，尚未承诺稳定兼容性。
