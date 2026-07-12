# Component Architecture：为什么这样分层

## 从一张波形开始

设想验证工程师先拿到一段 AXI 波形。他最初可能写一个大 checker：看到
`AWVALID` 就记地址，看到 `WVALID` 就数数据，看到 `BVALID` 就检查响应。很快，这个
checker 同时知道时钟、握手、burst、ID、memory 内容、测试期望和报告格式。它能够检查
一个 DUT，却不能解释哪些规则属于 AXI、哪些只是当前 testbench 的假设，也不能复用于
APB 或 UART。

这个项目从拆开这些问题开始。

第一步，把引脚值变成语义事件。`VALID && READY` 不是一笔完整 AXI 事务，只是一个
channel transfer。这里需要状态机记住 stalled payload，因此状态机的抽象形式进入
`core/`；ready-valid 只是这个抽象的一种常见用法，所以进入 `patterns/`。

第二步，把 transfer 组合成事务。AR 创建若干 R beat 义务，AW 和 W burst 合流后创建
B 义务。这些规则不关心引脚怎样采样，而关心 token、数量、匹配和先后，因此进入
`semantics/`。

第三步，绑定规范名称。`AWLEN + 1`、`WLAST`、4KB boundary 和 APB 的
`PSEL/PENABLE/PREADY` 来自具体规范，只能放在 `protocols/axi4/` 或
`protocols/apb/`。

最后，随机产生多少事务、memory 返回什么数据、VirtualDut 延迟几周期以及图怎样画，分别
属于用户面对的 `projects/`、`virtual_dut/` 和 renderer。它们可以影响实验，却不能偷偷
改变协议接受哪些行为。

## 分层得到的责任边界

```text
core       定义 event、state、step、fault、verdict 是什么
semantics  定义 obligation、resource、ordering、correlation
patterns   定义 ready-valid、two-phase、reset、quiet 等常见机制
protocols  把机制绑定到 AXI/APB 字段和规范条款
engine     执行组合后的模型，生成或验证有限 trace
projects   拥有case、组件清单、生命周期、工程状态和artifacts
virtual_dut 提供功能状态、终端响应或协议间转换
project plan 在具体验证项目内部实例化link并组网
evidence   提供通用只读renderer；协议专用renderer归协议包
```

判断一个对象放在哪里，可以问：删除 AXI/APB 字段名后，它还剩下什么？如果剩下的是
状态迁移形式，它属于 core；如果剩下的是可复用的握手机制，它属于 patterns；如果是
token、义务或关系，它属于 semantics；如果无法删除字段名，它属于具体 protocol。

VirtualDut 再问一个问题：它是否描述“节点如何选择或转换行为”？通用 source、sink 和
function responder 位于 `virtual_dut/`；依赖具体计划的 AXI bridge 先留在对应 Project。

## 从单链路到Project组网

协议层仍只研究一条 link 接受哪些有限行为；VirtualDut 在合法集合中选择、终止或转换
行为。`prj_axi4_read_bridge` 已用两个 AXI ProtocolSession、一个 forwarding bridge 和一个
dumb responder 构成首个验证计划。该 responder 没有 memory 状态，因此数据仍只是确定性
payload，尚不能证明读值等于某个地址的真实内容。

因此下列能力暂时自然地用不上：

- Hoare-style pre/post contract：等待有 memory/register 状态的 VirtualDut；
- 通用网络路由和 open-system composition：等待多个 Project 证明抽象可复用；
- 范畴化组合：等待至少两个可组合网络案例；
- 仲裁、公平性和端到端 deadline：等待多个主动 endpoint 和调度器；
- FSDB 跨层 provenance：等待 adapter 与真实 DUT 观测。

这不是缺陷掩盖，而是明确的模型边界。有限状态 monitor、token obligation 和偏序 trace
可以独立成熟；Project 和 VirtualDut 消费这些语义，而不反过来污染协议定义。

## Quiet 为什么属于 pattern

未使用端口常有三种完全不同的验证含义：

```text
IGNORE  没有观察/不纳入本次验证；不能据此宣称端口合法
STABLE  第一次观察建立基线，之后任何变化都失败
TIED    每次观察都必须等于指定常量
```

它们不是 AXI 或 APB 独有规则，也不是“状态机是什么”的核心定义，而是由 core 自动机
构造出的通用观测模式，所以实现为 `patterns.QuietConstraint`。具体协议不应派生子类；
未来由 `InterfaceProfile`、adapter 或验证环境按端口实例化。若规范明确要求 reserved port
恒为零，protocol profile 可以实例化 `TIED(expected=0)`；若只是 probe 没接，则只能用
`IGNORE`，并在覆盖报告中保留这个事实。

## 当前统一接口

早期 `MonitorAutomaton` 与事件生成式 `ProtocolComponent` 已被单一
`SemanticComponent` 取代。验证把外部 action 送入 `step`；生成器可以提出候选，但候选
仍必须经过同一个 `step`。状态变化、emission、fault 和 causal predecessors 位于同一个
`SemanticStep`。下一步是让已经声明的 `PortSpec` 真正参与 action routing、ownership 与
coverage，而不是重新建立第二套生成接口。
