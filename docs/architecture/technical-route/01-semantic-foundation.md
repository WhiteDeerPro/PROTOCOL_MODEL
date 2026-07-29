# 基础语义：建立所有协议共享的词汇

[返回架构地图](README.md) · [查看总览图](overview.svg) · [术语表](../terminology.md)

基础语义层定义各协议共享的通信事实、规则作用域和有限 trace 证据。具体协议的 pin、message 和设备行为
通过相邻层映射到这些对象。

<a id="canonical-event"></a>
## 1. CanonicalEvent：统一的通信事件值

原始波形可以给出 `PSEL=1`、`PENABLE=1`、`PREADY=1`，UVM monitor 也可以给出一个 APB transaction。
observation adapter 或调用方把这些来源归一化为：

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

CanonicalEvent 是 pin-neutral 的通信事件值。observation、generator 或调用方先构造 event candidate；
session 接受候选值、同步提交 monitor 状态并赋予 trace index 后，得到该次运行中的 committed event。
设备执行结果继续由 VirtualDut backend 持有。实现见
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

Schema 支持两个方向：

- 验证：解释缺字段、额外字段或非法值；
- 生成：把 EventOffer 给出的部分条件补成一个具体合法事件。

`EventOffer` 表示“当前允许生成哪类事件、哪些字段已经固定”的部分赋值。它经过 schema 补全后形成
event candidate，再由 session 决定是否接受。当前证据级别是 state-aware sampling；完整状态空间覆盖需要
独立的穷举或形式化过程。实现见
[`interface/protocol.py`](../../../protocol_model/interface/protocol.py) 和
[`semantics/generation.py`](../../../protocol_model/semantics/generation.py)。

<a id="declarations"></a>
## 3. Constraint、Resource、Obligation：规则、占用和待办

三者分别回答不同问题：

| 对象 | 白话解释 | 例子 |
|---|---|---|
| `SemanticConstraint` | 合法行为集合受到什么限制 | AXI burst 禁止跨越 4KB；response ID 必须有效 |
| `ResourceDecl` | 什么东西会被占用并释放 | 一个未完成 APB transfer；AXI pending read slot |
| `ObligationDecl` | 发生 A 后仍欠着什么 B | READ 已接受，因此之后需要 READ_RESPONSE |

它们都带 scope：event、transport、interface、virtual_dut 或 system。Scope 表示一条规则的最小判定边界，
让设备功能、接口局部规则和全局网络约束各自回到对应 owner。Transport-hop 与 Interface 是两个并列
观察面：前者检查相邻 TX→RX 的 flow control，后者检查完整逻辑接口内的事件和事务关系。

有限 trace 的 verdict 条件为：

- `FAIL`：已观察到直接违规；
- `PASS`：全部检查接受，且相关状态已经 quiescent；
- `INCONCLUSIVE`：当前前缀保持合法，同时仍有 pending 或 obligation。

pending 状态因而把“当前未观察到违规”与“已经完成”区分开。实现见
[`semantics/model.py`](../../../protocol_model/semantics/model.py)。

<a id="fragment"></a>
## 4. SemanticFragment：可以组合和追踪的规则包

SemanticFragment 把 constraints、resources、obligations、dependencies 和来源组织成具名片段。协议定义
可以组合多个 fragment，并在实例化时加 namespace，为每个 interface instance 分配独立的规则与资源名称。

fragment 负责 requirement catalog、组合结构和诊断 provenance。当前执行判定由以下实现承担：

- EventSchema 的字段与事件局部约束；
- monitor 的状态迁移；
- InterfaceSession 对有界资源的用量检查。

声明进入 fragment 后即可供报告和未来分析 IR 使用；对应规则获得上述执行实现时，才产生可执行 verdict。
实现见 [`semantics/fragment.py`](../../../protocol_model/semantics/fragment.py)。

合同 refinement 保持单调收窄：增加 constraint、降低 capacity 或禁止 event 后，合法行为集合满足
`L(refined) ⊆ L(base)`。profile 可以给这个结果命名，也可以描述一组基础配置。实现见
[`interface/protocol.py`](../../../protocol_model/interface/protocol.py)。

<a id="component"></a>
## 5. SemanticComponent：会记住历史的审核员

事件局部字段检查由 EventSchema 完成；跨事件关系由 SemanticComponent 保存历史。例如，READ_RESPONSE
的判定需要查找此前已接受的 READ。可执行组件使用统一转移形式：

```text
(old state, action)
    → (new state, emissions, causal predecessors)
    或 SemanticFault
```

Monitor 是最常见的 SemanticComponent：它保存 pending token、beat count、FIFO descriptor 等最小历史。
InterfaceSession 将多个 monitor 同步运行，并在所有检查接受后一次提交状态。

实现见 [`semantics/component.py`](../../../protocol_model/semantics/component.py)。

## 6. CausalGraph：happens-before 与记录顺序

trace index 保存事件的线性记录位置。CausalGraph 在“后一个事件在语义上依赖前一个事件”时增加
happens-before 边。例如 response 依赖 request；两个不同 AXI ID 的 response 可以保持并发或不可比较。

缺少 causal edge 表示当前证据尚未建立 happens-before；trace index 继续独立记录文件或执行位置。实现见
[`semantics/causal.py`](../../../protocol_model/semantics/causal.py)。

## 7. 与相邻层的责任交接

| 事实 | Owner |
|---|---|
| APB/AXI pin 到 event candidate 的解释 | Observation |
| 地址读取的设备执行结果 | VirtualDut backend |
| 多个 module 与 connection 的系统关系 | SystemProtocol |
| 无限时间上的 progress 证明 | 显式 system/scenario property 与相应形式化过程 |

基础语义层为这些 owner 提供有限行为、显式状态和可追踪声明。

下一步阅读：[通用模式与 InterfaceProtocol](02-patterns-and-interface-protocol.md)。
