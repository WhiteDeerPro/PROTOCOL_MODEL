# 文档

当前面向使用者的文档包括：

- [用户手册](manual.md)：项目目标、核心概念、运行方法与实现边界；
- [AXI4 读交织约束报告](axi4_read_interleaving_report.md)：当前约束、quiet profile、ID 规则与缺口。
- [ProtocolInstance 管理](architecture/protocol-instance-management.md)：Project 如何引用协议并管理私域实例；
- [运行证据管理](architecture/evidence-management.md)：源码、手写文档与可再生报告的边界。

运行图片、报告和中间文件只允许出现在仓库根目录的 `out/<project>/<run-id>/`，由
`manifest.json` 管理且不进入 Git。`docs/` 只保留当前有效的手写规范，不保存运行快照或
历史草稿。
