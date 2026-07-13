# 文档

当前面向使用者的文档包括：

- [用户手册](manual.md)：项目目标、核心概念、运行方法与实现边界；
- [AXI4 读交织约束报告](axi4_read_interleaving_report.md)：当前约束、quiet profile、ID 规则与缺口。
- [ProtocolInstance 管理](architecture/protocol-instance-management.md)：Project 如何引用协议并管理私域实例；
- [运行证据管理](architecture/evidence-management.md)：源码、手写文档与可再生报告的边界。

`images/` 只存放需要版本化引用的稳定 SVG 快照。日常运行证据统一写入仓库根目录的
`out/<project>/<run-id>/`，不放入 Project 源码目录，也不由 Git 跟踪。

## 历史设计记录

[`archive/2026-07-design-notes/`](archive/2026-07-design-notes/) 保存项目早期的架构推导、
AXI4/APB 派生、理论审计和开发工作流。这些材料解释了设计过程，但不是当前 API 或行为的
规范；其中的计划性描述可能已经过时。需要了解当前能力时，以 README、用户手册和实际
代码为准。
