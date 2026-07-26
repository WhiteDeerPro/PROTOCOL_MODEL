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

## 生命周期状态与执行集合

生命周期状态和执行集合是两个不同维度：

- `active` 是当前维护的行为证据；
- `legacy-sentinel` 只保护具名迁移边界，必须同时记录 owner、原因和删除条件；
- `smoke`、`target`、`integration` 和 `release` 是可以重叠的执行集合，不复制测试实现。

当前唯一的 legacy sentinel 保护 `protocol_model.system.protocol` 中
`InterfaceConnection` 的公共 re-export。它随该 facade 的正式退役一起删除，不通过新增兼容层延长寿命。
精确 test ID 和删除条件保存在 `tests/suites/manifest.py`。

当前限制的负例仍属于 active。若测试断言的是“当前尚未实现”，manifest 必须记录它何时转为正例；对应能力
落地时用合法 lifecycle witness 替换负例。协议永久禁止、架构边界和阶段性缺口不得共用一个模糊的
“unsupported”理由。

## 运行入口

编辑循环运行小型代表集：

```bash
make smoke
```

完成代码修改前运行 active 全集；当前全量测试很快，不以分层为由省略最终回归：

```bash
make test-active
make test
```

入口默认使用简洁输出；复现失败时可传入 `UNITTEST_FLAGS=-v`。

按受影响职责运行 target：

```bash
make test-target TARGET=chi
make test-target TARGET=virtual-dut
make test-target TARGET=interfaces
make test-target TARGET=system
make test-target TARGET=architecture
make test-target TARGET=e2e
```

修改具体协议与 SystemProtocol、attachment、backend 或 recipe 的组合边界时，增加 integration：

```bash
make test-integration
```

兼容迁移和发布入口分别是：

```bash
make test-sentinels
make test-release
```

`test-release` 只运行仓库测试，包括不写发布树的 showcase model witness。具名 showcase 生成器仍需由发布流程
显式运行，并优先写入临时/scratch 输出；只有明确发布动作才替换 `showcase/generated/`。

## Manifest 约束

`tests/suites/manifest.py` 显式登记模块、target、smoke、integration、legacy sentinel 和待转正负例。
`tests/test_suite_manifest.py` 检查：

- discovery 得到的每项测试都由 active 或 legacy sentinel 覆盖；
- suite 中引用的 test ID 真实存在；
- smoke、target 和 integration 都是 active 的子集；
- 没有隐藏的 skip 或 expected failure；
- sentinel 和待转正负例包含退出条件。

新增测试模块时必须加入一个职责 target。不要依赖运行时 import 扫描自动决定回归范围。
