# 文档

当前面向使用者的文档包括：

- [用户手册](manual.md)：项目目标、核心概念、运行方法与实现边界；
- [ProtocolInstance 管理](architecture/protocol-instance-management.md)：Project 如何引用协议并管理私域实例；
- [Project 与运行结果管理](architecture/run-output-management.md)：Project、运行目录与文档素材的边界。
- [Project 功能导览](project-guide.md)：五个 Project 的全部 case、波形图和因果事件图。

单独运行时，图片、报告和中间文件写入对应 Project 的 `out/<run-id>/`；全量运行时汇总到仓库
根目录的 `out/<project>/<run-id>/`。两者都不进入 Git；全量运行生成的 `out/index.html` 是五个
Project 的统一功能导览。
