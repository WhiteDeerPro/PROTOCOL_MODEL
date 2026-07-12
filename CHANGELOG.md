# Changelog

## 0.1.0 — experimental foundation

首个实验性里程碑，建立协议语义、trace 和验证 Project 的共同骨架。

- 统一 `SemanticComponent.step(state, action)` 语义接口。
- 提供 AXI4 与 APB3/APB4 的可执行约束、合法 trace 生成和违规 trace 检查。
- 提供 ready-valid 与 AXI4 VirtualDut 验证 Project。
- 输出 WaveDrom 波形、Graphviz 因果图和验证报告。
- 将仿真结果默认放在各 Project 的 `sims/` 目录，并排除生成物与本地环境文件。

本版本 API 和协议覆盖范围仍处于实验阶段，尚未承诺稳定兼容性。
