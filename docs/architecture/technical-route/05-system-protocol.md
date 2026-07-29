# SystemProtocol：从两个端点到协议网络

[返回架构地图](README.md) · [Integration 与 binding](04-integration-and-binding.md) · [术语表](../terminology.md)

InterfaceProtocol 只能观察一条逻辑接口连接。只要出现“这个具体端口连到谁”“bridge 应该选哪个下游”“response
应该归还哪个上游”，判断范围就已经扩大到多个模块和 connection，需要 SystemProtocol。

<a id="why-system"></a>
## 1. 点到点与网络使用统一系统表示

最简单的系统只有：

```text
VirtualDut A ── one InterfaceConnection ── VirtualDut B
```

它没有额外全局约束，但已经包含具体模块身份、具体端口和一份 connection 实例状态。把它也提升为
SystemProtocol，可让点到点、`A → bridge → B` 和星形 fabric 共用同一个执行入口和 topology model。

`SystemProtocol.from_interface()` 提供这种退化形式。

<a id="connection-kinds"></a>
## 2. Canonical topology 中的两种连接

### 2.1 InterfaceConnection：完整逻辑接口的一次使用

InterfaceProtocol 是可复用合同；InterfaceConnection 是这份合同的一次具体使用：

```text
InterfaceConnection "apb_bus"
├── protocol: APB4 InterfaceProtocol
├── requester: manager.apb
└── completer: registers.apb
```

每个 protocol role 都必须绑定一个具体 `VirtualDutPortRef`。两条使用同一 AXI4 定义的 interface connection 仍有独立
InterfaceSession 和独立 outstanding 状态。

定义见 [`system/topology/model.py`](../../../protocol_model/system/topology/model.py)。

### 2.2 DirectedTransportConnection：一条有向 transport hop

显式展开 flit transport 时，`DirectedTransportConnection` 将一个 transmitter `TransportPort` 指向一个
receiver `TransportPort`。它与 `InterfaceConnection` 共用 `SystemProtocol.connections`，因此不会形成第二份
拓扑权威；elaboration 从中派生只读 `ResolvedTransportPlan`。连接携带的 profile 由具体 transport family
解释，例如 CHI 的 activation 与 L-Credit。

根 `SystemSession` 目前执行完整逻辑接口。CHI Issue H 的 family session 消费 resolved transport plan；line、
ring、mesh 是调用方 recipe/fixture，不固化在 session 类中。

<a id="elaboration"></a>
## 3. Elaboration：运行前把声明解析清楚

当前 elaboration 检查：

- VirtualDut 与两种 connection 的名称映射一致；
- port reference 指向存在的模块和端口；
- `InterfacePort` role/protocol 与 InterfaceConnection 一致；
- `TransportPort` direction/family 与 DirectedTransportConnection 一致；
- 一个 port 只能属于一条内部 connection 或一个 system boundary；
- 所有声明端口都必须连接或暴露为 boundary；
- 各 DUT、interface connection、system semantic fragment 获得独立 namespace；
- 显式 address router route 与 direct-neighbor endpoint claim 唯一闭合；
- generated address router 的实际 route boundary projection 与 construction contract 一致。

当前这组检查形成 structure 与 direct-neighbor address closure。profile 协商、clock/reset compatibility、
capability negotiation、多跳 address resolution 和 external/opaque DUT projection 核对属于后续 resolution
passes；覆盖范围集中记录在[实现状态](../implementation-status.md)。

实现见 [`system/elaboration.py`](../../../protocol_model/system/elaboration.py)。

<a id="runtime"></a>
## 4. SystemSession：立即反应传播到固定点

一次 `SystemAction` 指定某个 VirtualDut port 发出 canonical event。SystemSession：

1. 找到该端口属于哪条 interface connection；
2. 检查事件方向是否允许该 role 发送；
3. 推进这条 connection 自己的 InterfaceSession；
4. 记录具体 source、destination、channel 和全局 event index；
5. 把事件交给目标 VirtualDut backend；
6. 将 backend 的立即 emissions 放回队列；
7. 重复到队列为空或超过 `max_internal_steps`。

这里的 fixed point 定义为“当前立即反应队列已空”。RTL cycle 由 time/clock profile 定义，deadlock verdict
由 progress analysis 产生。实现了 `ExplicitlyAdvanceableBackend` 的 backend 可以由 `DutAdvanceAction`
获得显式 service opportunity；queued responder 和 scheduled crossbar 已使用这条路径。自主 wakeup、定时队列、
多时钟调度和延后 emission 的跨 connection lineage 随统一 scheduler 扩展。

传播采用逐跳提交：后续 fault 保留此前已经接受的状态与事件。需要全局事务式回滚的场景应声明独立的
system transaction contract。

实现见 [`system/session.py`](../../../protocol_model/system/session.py)。

Transport family 可以在叶包中提供自己的 session，而不让通用 runtime 反向依赖具体协议。当前
`ChiTransportNetworkSession` 读取 `ElaboratedSystemProtocol.transport_plan`，统一持有 hop、router 与 lineage
状态，并原子提交 capture→router 和 router→downstream 两个跨组件边界。通用 network session 仍由调用方
显式选择 tick、capture、forward 与 drain；受限 direct-read/retry composite session 已提供 family scheduler。
mixed-channel hop、identity/coherence closure 和 deadlock analysis 尚未实现。

<a id="bridge-fabric"></a>
## 5. 互连模块的内外边界

一个物理 bridge/crossbar 可以作为单个多端口 VirtualDut：

```text
SystemProtocol topology
  A ─ connection A ─ [bridge VirtualDut] ─ connection B ─ B
                    │
                    └─ backend 内部保存 transform / route / owner
```

- wire fragment join 属于各端口 attachment；operation fanout/fold 与 route policy 属于 stage/plan；
  queue、schedule、lease 和返回 owner 属于这个 VirtualDut executor/backend；
- bridge 外部端口连到哪些模块属于 SystemProtocol；
- 每条外部 interface connection 的局部合法性属于各自 InterfaceProtocol。

需要验证 bridge 内部微网络时，可以把它展开为内部 SystemProtocol，再封装回相同边界。
Typed operation、stage、plan 和 executor 的内部构造见
[Bridge 与类型化事务转译](../typed-transaction-translation.md)。

<a id="global-properties"></a>
## 6. SystemProtocol 的全局性质

后续 SystemProtocol 将逐步承担：

- address claim、route transform 和 target reachability；
- 多节点端到端 request owner/response return 闭合；单个 bridge/crossbar 的 owner table 仍由该 VirtualDut 持有；
- buffer、credit、outstanding 和 wait-for；
- route loop、broadcast/fork/join；
- deadlock、livelock、starvation、fairness；
- hide internal connections/hops 后的 boundary refinement。

地址 gap 若 fabric 明确返回 DECERR，不一定是结构错误；全地址覆盖可以是具体验证场景的 property。系统层
需要区分结构闭合与更强的场景目标。

<a id="recursive-composition"></a>
## 7. 递归组合与物理尺度

`SystemProtocol.as_virtual_dut()` 将 system boundary 重新包装成 VirtualDut：

```text
module → subsystem → SoC → chiplet/package → board
```

因此各物理尺度直接复用 InterfaceProtocol、VirtualDut、SystemProtocol 的递归组合；具体协议还可以叠加
RepresentationCodec、TransportLink 和物理边界合同。当前封装完成结构与语义投影；
嵌套 subsystem 的 runtime composition 由后续 hierarchical session 扩展。

更完整的系统架构见 [SystemProtocol 文档](../system-protocol.md)。下一步阅读：
[组网构建阶段](../network-construction.md) 或 [观察、执行与证据](06-observation-execution-evidence.md)。
