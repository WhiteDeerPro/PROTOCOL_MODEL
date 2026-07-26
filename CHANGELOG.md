# Changelog

## Unreleased

- 将回归入口分为 smoke、职责 target、integration、迁移哨兵和 full baseline，增加 suite manifest 自检与
  Python 3.10/3.13 最小 CI；同时收敛仓库工作约定，并让根 Roadmap 只维护长期依赖和 canonical 施工入口。

## 0.4.0 — interface scopes, executable fabrics, and CHI network slices (2026-07-27)

- 建立当前版本的单一 canonical 术语注册表，并将公共词族收敛为 `InterfaceEventKind`、
  `InterfacePort`/`InterfaceAttachment`、`VirtualDutBackend`、`TranslationProfile` 和
  `ConstraintRecord`；注册表允许通过有记录的迁移继续演进。
- 公共接口作用域名称收敛为 `InterfaceProtocol`、`InterfaceSession` 和
  `InterfaceConnection`；退役旧 `protocol_model.link` 源码树，单向 flit hop 使用独立的
  transport 对象。
- observation 增加异步四相 REQ/ACK lowering；InterfaceProtocol 增加 schema、profile refinement、
  event prohibition 与 bounded resource offer。
- VirtualDut 增加协议无关 backend、typed transaction translation、统一 AMBA serial bridge、
  scheduled address crossbar、AXI4 read/write crossbar，以及 sensor、memory-copy、interrupt、
  queued responder 与 stepped emission 组网原件。
- SystemProtocol 增加有向 transport topology、resolved hop plan、显式 address contracts 和
  family-owned network runtime，并在 blocked step 上提供原子回滚。
- CHI Issue H 增加 REQ/RSP/DAT transport、有限 store-and-forward router、direct-Home
  `ReadNoSnp` 和 `RetryAck`/P-Credit 重发闭环，以及受限
  `ReadShared`/`ReadUnique`/dirty-unique/`ReadNotSharedDirty` coherence lifecycle；完整 CHI 与
  coherence 仍按状态页声明的边界推进。
- 增加 recipe catalog、source dependency guard 与 453 项默认回归测试；测试目录保存行为合同，
  不承担生产状态机实现。
- 文档按渐进导读、canonical 架构、当前状态、路线图和历史 release 分工，减少状态清单的重复维护。
- Showcase 增加异步握手、bridge chain、AXI fabric/crossbar、Sensor-DMA、interrupt、CHI routed
  read 与 2×2 clean-coherence mesh 的具名发布证据。

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
