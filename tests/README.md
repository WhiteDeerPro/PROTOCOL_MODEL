# Tests and reference fixtures

`tests/` 保存定向行为证据，不是第二份产品源码目录。可复用的 protocol ledger、VirtualDut backend、attachment、
bridge、crossbar、router 和 System session 必须位于 `protocol_model/`；测试只实例化它们并声明预期结果。

测试中可以保留三类私有 helper：

- 构造一个最小合法/非法 event、flit 或状态；
- 装配只服务该测试的具名 topology、端口 profile 和 participant binding；
- test double，例如故意阻塞的 monitor、投影 router 或只用于检查 generic stage 的 payload。

当一份 topology 对用户有讲解价值时，将参考装配放进 `showcase/demos/<topic>/model.py`，测试可以复用或独立构造，
但不要把固定 direct、ring 或 mesh 拓扑提升成协议核心 recipe。Topology 是调用方输入；协议组件负责在满足其
profile 的 topology 上运行。

删除测试前先检查两件事：生产状态迁移是否已经位于 `protocol_model/`，以及该测试是否仍是某项原子回滚、
资源守恒或负例诊断的唯一证据。普通测试使用临时/scratch 目录，不写回 `docs/` 或
`showcase/generated/`。
