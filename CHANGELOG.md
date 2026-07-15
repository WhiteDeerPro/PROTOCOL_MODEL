# Changelog

## 0.3.0 — bottom-up protocol architecture and public showcase (2026-07-16)

首个公开 technical preview。公共入口和建模边界仍可能根据实际使用反馈调整。

- 公共术语确定为 `LinkProtocol`、具体 `VirtualDut` 和全局 `SystemProtocol`；不暴露
  `Agent` 抽象。
- 增加 scope-aware constraint、resource、obligation 与可组合 `SemanticFragment`。
- 增加 typed VirtualDut port、ProtocolLink、link ownership/boundary elaboration 和全局语义
  namespace。
- 支持把 SystemProtocol 封装为复合 VirtualDut，统一 SoC、chiplet、封装和板级递归组合。
- 增加 executable event domain、LinkSession、CardinalityMonitor 和 SystemSession；单链路与
  `A → bridge → B` 均通过统一的自动投递路径执行。
- AMBA LinkProtocol 按 AXI/AHB/APB/ACE/CHI 家族组织；APB3/APB4/APB5 提供独立 API，
  APB5 当前覆盖 user/wakeup/RME 并关闭 parity profile。
- 增加 ACE-Lite ordinary-data profile，复用 AXI4 五通道语义并检查 domain/snoop/bar；
  CHI Issue H 当前保留实施边界。
- 增加 APB、AHB、AXI4-Lite 与 AXI4 的功能性 VirtualDut integration；AXI4 normal burst endpoint
  可展开逐 beat AddressAccess，AXI4-Stream 使用独立 StreamTransfer contract。
- 增加同宽 AXI→APB bridge VirtualDut：Lite profile 为单活动事务；full AXI4 profile 提供有界 parent
  FIFO、burst 逐 beat APB 调度、地址重映射和 completion 聚合。
- integration 源码按单端口 attachment 与 endpoint/fabric/bridge recipe 分层；AMBA 表示端口绑定范围，
  不建立 AMBA 设备继承树。
- 增加统一的 24 场景 AXI4 展示；每个场景均保留波形、因果图和机器可读结果，两项代表场景提供展开讲解。
- 增加中英文架构总览、one-pager、演示稿与发布文案。
- 运行目录由调用方按用途选择；`out/` 仅为未指定时的 scratch 默认，受版本控制的展示资产只能由
  具名生成脚本显式更新。
- 增加 Python packaging 元数据，版本由 `protocol_model.__version__` 单点提供。
