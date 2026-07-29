# SystemProtocol 源码导航

## 定位

`protocol_model.system` 描述一个选定验证作用域内的通信系统。`SystemProtocol` 聚合具名
`VirtualDut`、接口连接、transport hop、系统边界和跨连接合同；`ElaboratedSystemProtocol` 保存结构闭合
与 resolution 的结果。

三个核心对象按事实范围协作：

- `InterfaceProtocol` 判定一次完整逻辑接口上的局部通信；
- `VirtualDut` 保存 module 局部执行状态，并通过端口接收和发出事件；
- `SystemProtocol` 保存跨 module 的连接、authority 和判定范围。

它们通过组合建立系统模型，各自保持独立的公共 API。

```text
InterfaceProtocol / transport profile + VirtualDut boundary
                            │
                            ▼
                 canonical weak topology
                            │ + system contracts
                            ▼
                    SystemProtocol
                            │ elaborate / resolve
                            ▼
               ElaboratedSystemProtocol
                 ├─ owner_by_port
                 ├─ address_plan
                 └─ transport_plan
                            │ execute / monitor / analyze
                            ▼
                  trace + verdict + evidence
```

## 输入

`SystemProtocol` 接收以下声明：

- `virtual_duts`：参与系统的具名 module；
- `connections`：完整逻辑接口的 `InterfaceConnection`，以及单向 hop 的
  `DirectedTransportConnection`；
- `boundary`：暴露给外层组合的端口引用；
- `semantics`：系统作用域的补充语义；
- `address_map`：接收窗口与显式 router route 的系统合同。

`SystemProtocol.from_interface()` 提供单接口系统的便捷构造；`SystemProtocolBuilder` 用于逐项装配较大的
topology 和 address contract。

## 输出与状态归属

elaboration 组合语义 namespace，校验端口引用、角色、方向、协议族和唯一 ownership，并产生只读结果：

| 结果 | 事实范围 | 当前对象 |
|---|---|---|
| 端口 ownership | 每个 VirtualDut port 的 connection 或 boundary owner | `owner_by_port` |
| 地址闭合 | ingress、route、egress connection 与 direct receiver claim | `ResolvedAddressPlan` |
| transport 投影 | 具名有向 hop 及 incoming/outgoing 查询 | `ResolvedTransportPlan` |
| 接口执行记录 | connection state、DUT state snapshot、事件和因果边 | `SystemSessionState`、`SystemTrace` |

module 内的 FIFO、仲裁器、owner table、directory 和其他可变行为状态由对应 `VirtualDut` backend 定义。
系统层保存跨连接 authority、已解析计划、执行轨迹以及由 monitor/analysis 派生的判定结果。

各职责包的输入与产物如下：

| 包 | 输入 | 产物或持有的事实 |
|---|---|---|
| [`topology/`](topology/README.md) | VirtualDut、端口和连接声明 | canonical 弱结构图与 typed ownership |
| [`contracts/`](contracts/README.md) | 系统意图和边界声明 | address、capability、identity、domain、property 等合同 |
| [`construction/`](construction/README.md) | module、connection、contract、factory | 显式 `SystemProtocol` 声明及构造核对 |
| [`resolution/`](resolution/README.md) | frozen system 声明 | 带来源信息的不可变 resolved plan |
| [`runtime/`](runtime/README.md) | elaborated system、外部 action | session state、事件、trace 与调度状态 |
| [`monitors/`](monitors/README.md) | 多 connection 事件与系统 authority | reference ledger 与 system verdict |
| [`analysis/`](analysis/README.md) | topology、plan、trace、资源快照 | reachability、wait-for、witness 与 refinement 证据 |

## 公共入口

应用代码从 `protocol_model.system` facade 导入稳定名称：

```python
from protocol_model.system import (
    SystemProtocol,
    SystemProtocolBuilder,
    VirtualDutPortRef,
    elaborate_system_protocol,
)
```

当前实现落点：

- [`protocol.py`](protocol.py) 定义 `SystemProtocol`、单接口提升和递归 `as_virtual_dut()`；
- [`elaboration.py`](elaboration.py) 编排结构闭合、语义组合、address resolution 和 transport resolution；
- [`session.py`](session.py) 实现 `InterfaceConnection` 的同步执行入口；
- transport family 从 `ElaboratedSystemProtocol.transport_plan` 建立自己的 executable session；
- `runtime/`、`monitors/` 和 `analysis/` 已划定目标职责，其中后两者当前保留包入口。

逐协议覆盖、明确缺口和阶段边界统一记录在
[实现状态](../../docs/architecture/implementation-status.md)与
[Roadmap](../../docs/architecture/technical-route/08-roadmap.md)。

## 架构护栏

- `SystemProtocol.connections` 是 interface connection 与 directed transport hop 的唯一 topology 权威；
  resolved transport plan 是它的只读投影。
- topology 记录连接关系。decode、route、broadcast、arbitrate 和 response return 等 module 行为由具名
  `VirtualDut` backend 与显式 system contract 共同闭合。
- construction 在 runtime 之前展开便捷声明；生成的 module 和 connection 进入 canonical topology。
- resolution 只读消费 frozen 声明，返回不可变计划，并保持既有 `VirtualDut` 实例不变。
- runtime 执行已经固定的 topology 和 resolved plan；转换方案的选择与 lowering 属于 construction。
- monitor 消费系统事件并维护 reference ledger；协议事件由 `VirtualDut` backend 发出。
- analysis 只读消费 topology、plan、trace 或资源快照，并返回派生证据。

## 相邻链接

- [InterfaceProtocol、VirtualDut 与 SystemProtocol](../../docs/architecture/system-protocol.md)
- [SystemProtocol 组网架构](../../docs/architecture/network-construction.md)
- [通信建模的三张视图](../../docs/architecture/communication-scope-and-transport.md)
- [VirtualDut 源码导航](../virtual_dut/README.md)
