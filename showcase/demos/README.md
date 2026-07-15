# 可执行示例目录约定

本目录保存宣传材料使用的可执行场景源码。AXI4 当前只有一套公开介绍例：

- [`axi4/`](axi4/README.md) 含 24 个具名场景，按事务生命周期、burst 与字节几何、
  ordering/interleave、观察与复位、独占访问与 profile 五个主题组织；
- 每个场景都由同一个 runner 实际生成 `result.json`、`waveform.svg` 和
  `causality.svg`；
- `write-narrow-unaligned-incr` 与 `write-early-wlast` 是同一套 24 案中的两项精讲，
  不是另一套 quick start，也不重复计数。

当前组织与近期扩展点：

```text
showcase/demos/
├── axi4/
│   ├── cases/          # 按语义主题拆分的输入目录
│   ├── common.py       # 小型输入构造词汇
│   ├── execution.py    # 调用当前协议模型并收集结果
│   ├── hero_cases.py   # 两个精讲 case 的丰富 AtomicFrame 输入
│   ├── presentation.py # 波形、因果图和导航投影
│   └── run.py          # 唯一具名发布入口
└── axi4-apb-bridge/
    └── （拟议的微网络演示）
```

公开阅读入口是 [AXI4 可执行示例导航](../generated/axi4/README.zh-CN.md)，英文版见
[AXI4 executable example guide](../generated/axi4/README.en.md)。普通 case 在导航中用折叠块串起
短说明、波形和因果图；两个精讲 case 直接展开并解释新的观察边界或资源关系。

目录只拥有场景编排和教程投影：

- 协议规则继续由 `protocol_model/link/` 拥有；
- DUT attachment 与 bridge recipe 继续由 `protocol_model/integrations/` 拥有；
- 通用运行产物继续由 `protocol_model/artifacts/` 和 `protocol_model/visualization/` 管理；
- 具名脚本原子替换自己拥有的 `showcase/generated/axi4/`，并保留 WaveJSON、DOT、参数与 provenance；
- 测试验证 engine，示例讲述用户故事；两者可以复用输入，但示例不实现第二套 checker。

场景数表示当前发布的可执行样本，不等价于 AXI4 规范覆盖率或 RTL compliance。
