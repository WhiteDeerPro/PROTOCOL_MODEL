# 通用模式与 InterfaceProtocol：从积木构造接口局部合同

[返回架构地图](README.md) · [基础语义](01-semantic-foundation.md) · [术语表](../terminology.md)

APB、AHB 和 AXI 名字不同，却反复出现相似事务形状：请求后必须回复、一个 burst 有固定数量的 beat、
描述符和数据需要汇合、同一 ID 内保持次序。Pattern 抽取这些关系，InterfaceProtocol 选择并组合它们，
InterfaceSession 保存每条具体连接的运行状态。

<a id="patterns"></a>
## 1. Pattern：可复用的协议关系

| Pattern | 保存的最小历史 | 它回答的问题 | 使用场景 |
|---|---|---|---|
| in-order completion | FIFO pending token | 下一个 completion 是否对应最早请求？ | APB、AHB-Lite |
| cardinality | key 与剩余 beat 数 | 一个 opener 是否收到恰好 N 个 beat？ | AXI read、AXI4-Lite single beat |
| burst assembler | 当前数据 burst | beat 数和 LAST 是否一致？ | AXI W channel |
| FIFO join | descriptor/data 两个队列 | 分离到达的 AW 和 W 应怎样配对？ | AXI write |
| completion ledger | 已 join 的 transaction | B 是否消费正确的 pending write？ | AXI write response |
| quiet | 模式与观察状态 | 禁止事件、信号稳定、忽略观察各是什么意思？ | read-only profile、pin policy |

以 AW/W 为例：AXI 允许写数据先于地址出现。模型分别保存完整 W burst 与 AW descriptor，再按 FIFO 规则
join；join 完成后打开等待 B 的 completion resource。这个状态形状可以继续复用于其他“描述符与数据
独立到达”的协议。

实现集中在 [`protocol_model/patterns/`](../../../protocol_model/patterns/)。

### Quiet 的三个作用域

“quiet”至少有三层不同含义：

1. InterfaceProtocol 禁止某类 canonical event；
2. pin observation 要求信号 tied/stable，或选择不检查；
3. 可视化隐藏某些 lane。

`IGNORE` 的证据强度止于“该项 observation 未检查”，接口活动状态保持未知。可视化隐藏只改变展示结果。
三层各自保存配置和证据，InterfaceProtocol 的事件禁令才参与协议合法性判定。

<a id="interface-protocol"></a>
## 2. InterfaceProtocol：一条逻辑接口连接的静态合同

InterfaceProtocol 描述：

```text
roles
  requester / completer

event kinds
  READ           requester → completer  + EventSchema
  READ_RESPONSE  completer → requester  + EventSchema

semantics
  constraints / resources / obligations

monitors
  executable transaction state
```

InterfaceProtocol 是不可变定义。运行中的 pending request 和 outstanding 资源归 InterfaceSession 所有。
每条具体 InterfaceConnection 建立独立 session，使各连接拥有各自的运行账本。

核心实现见 [`interface/protocol.py`](../../../protocol_model/interface/protocol.py)。

<a id="define-refine"></a>
## 3. define、refine、forbid 与 capacity

这些操作共同构造接口的合法行为集合：

- `define()`：建立基础接口合同；
- `refine()`：增加规则或 monitor，单调收窄行为；
- `forbid_events()`：明确禁止某类 canonical event；
- `with_resource_capacities()`：给已有生命周期的资源增加或收紧上限。

例如 AXI4 read-only profile 通过禁止 AW/W/B 得到更严格的接口合同。同一个 VirtualDut 端口可以选择
基础 AXI4 合同或 read-only profile，设备类型保持由 VirtualDut 的 module 边界和 backend 决定。

`interface_family` 当前表示 attachment 分派和 shape 比较使用的稳定接口族身份，interface shape 再比较事件、
字段、方向和关键参数。标准族谱需要独立演化时，可增加 `standard_family`、`revision` 和 compatibility
key。两个独立构造但配置相同的 AXI InterfaceProtocol 可以共享 attachment；interface shape 比较采用
合同配置，语义 monitor 的函数对象身份保留为运行构造细节。

<a id="interface-session"></a>
## 4. InterfaceSession：某一条具体连接的运行账本

收到事件后，InterfaceSession 依次完成：

1. 找到该 event kind 的有向声明；
2. 用 EventSchema 检查字段；
3. 给事件分配该 interface session 内的 trace index；
4. 同步推进所有相关 monitor；
5. 收集 causal predecessor；
6. 检查声明了容量的资源是否超限；
7. 所有步骤接受后提交新状态。

session 还会把各 monitor 的 `EventOffer` 取交集，用同一套状态语义约束生成。当前证据级别是状态感知
采样；完整状态空间证明需要独立的穷举或形式化过程。

同一 AtomicFrame 的多个事件可以由 `step_batch()` 按协议指定顺序执行，并按整批接受或整批回滚提交。
事件交换性由具体协议声明；例如 AXI observer 使用固定 lowering order 处理同帧 channel。

实现见 [`interface/session.py`](../../../protocol_model/interface/session.py)。

## 5. InterfaceProtocol 的判定范围与责任交接

| 事实 | Owner |
|---|---|
| 字段宽度、枚举、事件局部几何和 event direction | InterfaceProtocol |
| request/response 数量与关联，burst、同 ID ordering、单接口 outstanding resource | InterfaceProtocol |
| pin/cycle 到 canonical event 的解释 | Observation |
| endpoint 读取地址后的执行结果 | VirtualDut backend |
| bridge 的下游端口选择 | 多端口 backend |
| 多条连接的 route、owner 和 deadlock | SystemProtocol |

这里的 interface-local 描述判定范围。CHI Link layer 则属于标准定义的 transport 切面：flit、L-Credit 和
link activation 可以复用 EventSchema、monitor、resource 与 session product，并由 transport contract
组织。CHI transaction、packet、flit 的边界见
[通信建模的三张视图](../communication-scope-and-transport.md)。

## 6. 当前协议实现范围

- AXI4：五通道、burst、narrow/unaligned、read interleave、AW/W/B、exclusive；
- AXI4-Lite：原生单 beat schema 与 AXI4 embedding；
- AXI4-Stream：T channel、byte qualifier、packet/interleave；
- AHB-Lite：address/write-data/response pipeline 和 burst；
- APB3/APB4/APB5：single outstanding request/completion，版本化 pin schema 由各自子包公开。
- ACE-Lite data：在 AXI4 五通道上加 domain/snoop/bar 组合约束；barrier/CMO 需要专用 monitor 后再扩展
  profile。

详细协议说明见 [AXI4](../axi4-interface.md)、[AMBA variants](../amba-interface-variants.md) 和
[AHB/APB phased interfaces](../amba-phased-interfaces.md)。AMBA interface 家族的源码分组见
[AMBA interface 家族](../amba-interface-families.md)。
ACE-Lite 当前 profile 与 CHI 前置条件见 [ACE/CHI 接口与系统边界](../ace-chi-communication-scopes.md)。

下一步阅读：[VirtualDut](03-virtual-dut.md) 或 [端到端 APB 示例](07-apb-read-walkthrough.md)。
