# 基础语义：建立所有协议共享的词汇

[返回架构地图](README.md) · [查看总览图](overview.svg) · [术语表](glossary.md)

这一层解决的不是“AXI 有哪些信号”，而是更基础的问题：不同协议的通信事实怎样用同一种结构表达，
规则怎样说明适用范围，有限 trace 怎样区分“已经违规”和“还没完成”。

<a id="canonical-event"></a>
## 1. CanonicalEvent：已经发生的一件通信事实

原始波形会说 `PSEL=1`、`PENABLE=1`、`PREADY=1`；UVM monitor 可能给出一个 APB transaction。基础语义
不直接依赖这些来源，而把它们归一化为：

```python
CanonicalEvent(
    kind="READ",
    key=None,
    payload={"addr": 0x1000, "prot": 0},
)
```

- `kind` 表示发生了哪类协议动作；
- `key` 用于 ID、flow 等关联；
- `payload` 保存这类动作的字段；
- source、clock、timestamp、trace index 等元数据用于追踪来源和执行位置。

CanonicalEvent 不是 pin，也不是完整设备行为。它只是后续各层都能共同理解的“通信事实”。实现见
[`semantics/event.py`](../../../protocol_model/semantics/event.py)。

<a id="schema"></a>
## 2. ValueDomain 与 EventSchema：消息格式的合法性

可以把 ValueDomain 理解为表单字段的取值范围，把 EventSchema 理解为整张表单：

```text
READ
├── key: 必须为 None
├── addr: 32-bit bit vector
└── prot: 3-bit bit vector
```

Schema 有两个方向的用途：

- 验证：解释缺字段、额外字段或非法值；
- 生成：把 EventOffer 给出的部分条件补成一个具体合法事件。

`EventOffer` 只是“当前允许生成哪类事件、哪些字段已经固定”的部分赋值，不是已经发生的事件，也不是
完整状态空间探索。当前生成属于 state-aware sampling。实现见
[`link/protocol.py`](../../../protocol_model/link/protocol.py) 和
[`semantics/generation.py`](../../../protocol_model/semantics/generation.py)。

<a id="declarations"></a>
## 3. Constraint、Resource、Obligation：规则、占用和待办

三者分别回答不同问题：

| 对象 | 白话解释 | 例子 |
|---|---|---|
| `SemanticConstraint` | 哪些行为不允许 | AXI burst 不跨越 4KB；response ID 必须有效 |
| `ResourceDecl` | 什么东西会被占用并释放 | 一个未完成 APB transfer；AXI pending read slot |
| `ObligationDecl` | 发生 A 后仍欠着什么 B | READ 已接受，因此之后需要 READ_RESPONSE |

它们都带 scope：event、link、virtual_dut 或 system。Scope 表示“至少要看到多大范围才能判断”，用于避免
把设备功能、单 link 规则和全局网络约束混在一起。

有限 trace 中：

- 观察到直接违规，可以判为 `FAIL`；
- 没有违规且所有状态都已静止，可以判为 `PASS`；
- 没有违规，但仍有 pending 或 obligation，结果是 `INCONCLUSIVE`。

因此“没有报错”不总等于“已经完成”。实现见
[`semantics/model.py`](../../../protocol_model/semantics/model.py)。

<a id="fragment"></a>
## 4. SemanticFragment：可以组合和追踪的规则包

SemanticFragment 把 constraints、resources、obligations、dependencies 和来源组织成具名片段。协议定义
可以组合多个 fragment，并在实例化时加 namespace，避免不同 link 的规则和资源混名。

需要注意：声明进入 fragment，不代表当前有一个通用求解器自动执行了所有文字规则。当前真正的执行
来源主要是：

- EventSchema 的字段与事件局部约束；
- monitor 的状态迁移；
- LinkSession 对有界资源的用量检查。

Fragment 同时承担 requirement catalog、诊断来源和未来分析 IR 的作用。实现见
[`semantics/fragment.py`](../../../protocol_model/semantics/fragment.py)。

<a id="component"></a>
## 5. SemanticComponent：会记住历史的审核员

只检查一个事件的字段不够。例如收到 READ_RESPONSE 时，必须知道之前是否真的有 READ。可执行组件使用
统一转移形式：

```text
(old state, action)
    → (new state, emissions, causal predecessors)
    或 SemanticFault
```

Monitor 是最常见的 SemanticComponent：它保存 pending token、beat count、FIFO descriptor 等最小历史。
LinkSession 将多个 monitor 同步运行，只有所有检查都接受时才提交状态。

实现见 [`semantics/component.py`](../../../protocol_model/semantics/component.py)。

## 6. CausalGraph：记录语义依赖，不只是文件顺序

trace 保存事件的线性记录位置，但 causality 只在“后一个事件在语义上依赖前一个事件”时增加边。例如
response 依赖 request；两个不同 AXI ID 的 response 可能没有相互因果边。

因此“没有边”表示未建立 happens-before，可能是并发或不可比较，不应擅自解释为记录顺序。实现见
[`semantics/causal.py`](../../../protocol_model/semantics/causal.py)。

## 这一层不负责什么

- 不识别具体 APB/AXI pin；那属于 Observation；
- 不决定地址读取返回什么；那属于 VirtualDut backend；
- 不连接多个模块；那属于 SystemProtocol；
- 不自动证明无限时间上的 progress；当前主要处理有限行为与显式状态。

下一步阅读：[通用模式与 LinkProtocol](02-patterns-and-link-protocol.md)。
