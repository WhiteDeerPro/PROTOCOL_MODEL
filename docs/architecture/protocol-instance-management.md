# Project 私域 ProtocolInstance 管理

## 结论

`protocols/` 提供不可变、可复用的基础 `ProtocolSpec`；Project 不复制 AXI4 的实现，也不
修改基础对象。Project 在 elaboration 阶段按需生成自己的 profile，再把基础 spec 或私域
profile 绑定为具名 `ProtocolInstance`。实例、运行 session 和证据都归该 Project 所有。

```text
protocols/axi4: build_axi4_spec(config)
                 │ immutable base ProtocolSpec
                 ▼
Project constraints.py ── ProtocolDerivation ── private profile ProtocolSpec
                                                   │
Project.elaborate() ── ProtocolInstance(owner, link)┘
                              │ open_session per run/case
                              ▼
                     trace + constraint evidence
```

## 四层对象及生命周期

| 层 | 例子 | 所有者 | 生命周期 | 是否可共享 |
|---|---|---|---|---|
| 基础协议定义 | `axi4` `ProtocolSpec` | `protocols/axi4` | 构建后不可变 | 可以 |
| Project profile | `axi4_read_interleave` | `prj_axi4_read_interleave` | elaboration 期间构造，之后不可变 | 默认不跨 Project |
| 网络实例 | `prj_axi4_read_interleave/AXI-RI` | Project | 一次 Project 对象 | 不共享可变状态 |
| 运行 session | pending AR/R obligations | case/run | 一次运行 | 绝不共享 |

基础 spec 是规则模板，不是带 pending transaction 的活对象。`ProtocolInstance` 也只保存
绑定关系；每个 case 必须用 `open_session()` 创建新的运行状态，禁止让两个 link 或两个 case
共用 session state。

## 私域 profile 放在哪里

需要收窄 AXI4 能力时，在对应 Project 的 `constraints.py` 定义：

- 一个不可变配置 dataclass，例如 active IDs、quiet channels、outstanding 上限；
- 一个纯构造函数：输入基础 `ProtocolSpec` 和配置，返回派生 `ProtocolSpec`；
- 每项收窄都生成 `ConstraintRecord`，记录 rule、target、foundation 和 scope。

Project 的 `project.py` 只负责调用这个构造函数并绑定实例，不应再次手写 AXI channel schema、
握手或事务义务。若一套 profile 被两个以上 Project 采用，再考虑提升到独立的公共 profile
模块；提升前它仍是 Project 私域实现。

## 身份与命名

短名表达网络 link，例如 `AXI-A`、`AXI-B`、`AXI-RI`；它只需在一个 Project 内唯一。
持久证据使用 `owner/link` 形式的限定名，例如：

```text
prj_axi4_read_bridge/AXI-A
prj_axi4_read_bridge/AXI-B
prj_axi4_read_interleave/AXI-RI
```

`manifest.json` 同时记录 owner、link、base spec、effective spec、是否使用私域 profile 以及
profile constraint ID。这样图中仍可只显示简洁 link 名，审计时却能回答“该实例来自哪个
Project、引用哪个基础协议、具体施加了哪些约束”。

## 约束归属判断

| 问题 | 应放位置 |
|---|---|
| AXI4 对所有合法接口都成立吗？ | 基础 `protocols/axi4` requirement |
| 只是这个 endpoint/实验不支持吗？ | Project profile `ConstraintRecord` |
| 是本次故意破坏规则的输入吗？ | simulation case，报告为 `TEST` witness |
| 是 DUT 的功能映射或数据计算吗？ | Project VirtualDut / reference model |
| 需要 RTL/netlist 才能判断吗？ | 标为缺失 structural evidence，不伪装成 trace 约束 |

例如 `RID` 必须匹配 pending `ARID`、同 ID 消费最老 token 是 AXI4 规则；只允许 ID 1/2、
`ARCACHE=0`、AW/W/B quiet 是本实验 profile；“把 ARCACHE 改成 1”则是验证 profile 生效的
negative test。

## 禁止事项

- 不在 CLI 或 Project 中复制一份 AXI4/APB 协议实现；
- 不原地修改基础 `ProtocolSpec`；
- 不把 `ProtocolInstance` 做成跨 Project 全局 singleton；
- 不让两个网络 link 共享一个有状态 session；
- 不把 quiet 写成“忽略”，却在结论中声称信号满足约束；
- 不把 Project profile 的限制回写成所有 AXI4 都必须满足的基础规则。
