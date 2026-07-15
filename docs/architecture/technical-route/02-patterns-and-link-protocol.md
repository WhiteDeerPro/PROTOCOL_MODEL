# 通用模式与 LinkProtocol：从积木构造单链路协议

[返回架构地图](README.md) · [基础语义](01-semantic-foundation.md) · [术语表](glossary.md)

APB、AHB 和 AXI 名字不同，却反复出现相似事务形状：请求后必须回复、一个 burst 有固定数量的 beat、
描述符和数据需要汇合、同一 ID 内不能越序。Pattern 抽取这些形状，LinkProtocol 再选择并组合它们。

<a id="patterns"></a>
## 1. Pattern 不是协议名称，而是可复用关系

| Pattern | 保存的最小历史 | 它回答的问题 | 使用场景 |
|---|---|---|---|
| in-order completion | FIFO pending token | 下一个 completion 是否对应最早请求？ | APB、AHB-Lite |
| cardinality | key 与剩余 beat 数 | 一个 opener 是否收到恰好 N 个 beat？ | AXI read、AXI4-Lite single beat |
| burst assembler | 当前数据 burst | beat 数和 LAST 是否一致？ | AXI W channel |
| FIFO join | descriptor/data 两个队列 | 分离到达的 AW 和 W 应怎样配对？ | AXI write |
| completion ledger | 已 join 的 transaction | B 是否消费正确的 pending write？ | AXI write response |
| quiet | 模式与观察状态 | 禁止事件、信号稳定、忽略观察各是什么意思？ | read-only profile、pin policy |

以 AW/W 为例：AXI 允许写数据先于地址出现。模型不能只写“先 AW 后 W”的状态机，而是分别保存完整 W
burst 与 AW descriptor，再按 FIFO 规则 join；join 后才打开等待 B 的 completion resource。

实现集中在 [`protocol_model/patterns/`](../../../protocol_model/patterns/)。

### Quiet 的三个不同作用域

“quiet”至少有三层不同含义：

1. LinkProtocol 禁止某类 canonical event；
2. pin observation 要求信号 tied/stable，或选择不检查；
3. 可视化隐藏某些 lane。

`IGNORE` 只表示观察覆盖不检查，不能证明接口没有活动；显示隐藏也不是协议证据。三层使用相似词汇，
但不能由一个布尔开关代替。

<a id="link-protocol"></a>
## 2. LinkProtocol：一条逻辑连接的静态合同

LinkProtocol 描述：

```text
roles
  requester / completer

channels
  READ           requester → completer  + EventSchema
  READ_RESPONSE  completer → requester  + EventSchema

semantics
  constraints / resources / obligations

monitors
  executable transaction state
```

它是不可变定义，不保存某次运行的 pending request。每条具体 ProtocolLink 都需要自己的 LinkSession，
这样两个 AXI link 不会意外共享 outstanding 状态。

核心实现见 [`link/protocol.py`](../../../protocol_model/link/protocol.py)。

<a id="define-refine"></a>
## 3. define、refine、forbid 与 capacity

这些操作都针对“合法行为集合”，不是设备继承：

- `define()`：建立基础链路合同；
- `refine()`：增加规则或 monitor，单调收窄行为；
- `forbid_events()`：明确禁止某类 canonical event；
- `with_resource_capacities()`：给已有生命周期的资源增加或收紧上限。

例如 AXI4 read-only profile 禁止 AW/W/B，不等于创建一个新设备类型；同一个 VirtualDut 端口可以选择
基础 AXI4 或更严格 profile。

`family` 表示稳定协议族身份，transport shape 表示事件、字段和方向的外形。两个独立构造但配置相同的
AXI LinkProtocol 可以共享 attachment；语义 monitor 的函数对象身份不参与 transport shape 比较。

<a id="link-session"></a>
## 4. LinkSession：某一条具体 link 的运行账本

收到事件后，LinkSession 依次完成：

1. 找到承载该 event kind 的 channel；
2. 用 EventSchema 检查字段；
3. 给事件分配该 link 内的 trace index；
4. 同步推进所有相关 monitor；
5. 收集 causal predecessor；
6. 检查声明了容量的资源是否超限；
7. 所有步骤接受后提交新状态。

它也把各 monitor 的 `EventOffer` 取交集，用同一套状态语义约束生成。当前这是状态感知采样，不是对完整
状态空间的穷举证明。

同一 AtomicFrame 的多个事件可以由 `step_batch()` 按协议指定顺序全批提交或回滚。这里的“batch”不表示
事件天然可交换；例如 AXI observer 使用固定 lowering order 处理同帧 channel。

实现见 [`link/session.py`](../../../protocol_model/link/session.py)。

## 5. LinkProtocol 的作用域边界

LinkProtocol 可以判断：

- 字段宽度、枚举和事件局部几何；
- channel direction；
- request/response 数量与关联；
- burst、同 ID ordering、单 link outstanding resource。

它不判断：

- pin/cycle 怎样形成事件——Observation；
- endpoint 读地址后返回什么——VirtualDut；
- bridge 选哪个下游端口——多端口 backend；
- 多条 link 的 route、owner、deadlock——SystemProtocol。

## 6. 当前协议实现范围

- AXI4：五通道、burst、narrow/unaligned、read interleave、AW/W/B、exclusive；
- AXI4-Lite：原生单 beat schema 与 AXI4 embedding；
- AXI4-Stream：T channel、byte qualifier、packet/interleave；
- AHB-Lite：address/write-data/response pipeline 和 burst；
- APB3/APB4/APB5：single outstanding request/completion，版本化 pin schema 由各自子包公开。
- ACE-Lite data：在 AXI4 五通道上加 domain/snoop/bar 组合约束，当前不含 barrier/CMO。

详细协议说明仍在 [AXI4](../axi4-link.md)、[AMBA variants](../amba-link-variants.md) 和
[AHB/APB phased links](../amba-phased-links.md)。AMBA link 家族的源码分组见
[AMBA LinkProtocol 家族](../amba-link-families.md)。
ACE-Lite 当前 profile 与 CHI 前置条件见 [ACE/CHI Link 边界](../ace-chi-links.md)。

下一步阅读：[VirtualDut](03-virtual-dut.md) 或 [端到端 APB 示例](07-apb-read-walkthrough.md)。
