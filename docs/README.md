# 文档

当前面向使用者的文档包括：

- [用户手册](manual.md)：项目目标、核心概念、运行方法与实现边界；
- [AXI4 读交织约束报告](axi4_read_interleaving_report.md)：当前约束、quiet profile、ID 规则与缺口。
- [ProtocolInstance 管理](architecture/protocol-instance-management.md)：Project 如何引用协议并管理私域实例；
- [运行证据管理](architecture/evidence-management.md)：源码、手写文档与可再生报告的边界。
- [可执行实验图册](experiments.md)：各 Project 的稳定图像快照、运行命令与结果解读，包括 37-case AXI4 source/responder 场景集。

完整运行图片、报告和中间文件写入仓库根目录的 `out/<project>/<run-id>/`，由
`manifest.json` 管理且不进入 Git。`docs/images/experiments/` 仅保存图册引用的稳定 SVG
快照；它们不是另一套运行输出，变更 Project 行为后应重新生成 `out/`，确认结果后再更新快照。
