# SystemProtocol：从两个端点到协议网络

[返回架构地图](README.md) · [Integration 与 binding](04-integration-and-binding.md) · [术语表](glossary.md)

LinkProtocol 只能观察一条逻辑连接。只要出现“这个具体端口连到谁”“bridge 应该选哪个下游”“response
应该归还哪个上游”，判断范围就已经扩大到多个模块和 link，需要 SystemProtocol。

<a id="why-system"></a>
## 1. 点到点与网络使用统一系统表示

最简单的系统只有：

```text
VirtualDut A ── one ProtocolLink ── VirtualDut B
```

它没有额外全局约束，但已经包含具体模块身份、具体端口和一份 link 实例状态。把它也提升为
SystemProtocol，可让点到点、`A → bridge → B` 和星形 fabric 使用同一个执行入口，不需要先建一套“简单
场景 API”，以后再迁移成网络 API。

`SystemProtocol.from_link()` 提供这种退化形式。

<a id="protocol-link"></a>
## 2. ProtocolLink：具体连接，不是协议定义

LinkProtocol 是可复用合同；ProtocolLink 是这份合同的一次具体使用：

```text
ProtocolLink "apb_bus"
├── protocol: APB4 LinkProtocol
├── requester: manager.apb
└── completer: registers.apb
```

每个 protocol role 都必须绑定一个具体 `VirtualDutPortRef`。两条使用同一 AXI4 定义的 link 仍有独立
LinkSession 和独立 outstanding 状态。

定义见 [`system/protocol.py`](../../../protocol_model/system/protocol.py)。

<a id="elaboration"></a>
## 3. Elaboration：运行前把声明解析清楚

当前 elaboration 检查：

- VirtualDut 与 ProtocolLink 名称映射一致；
- port reference 指向存在的模块和端口；
- port role 与 link endpoint role 一致；
- port 与 link 当前使用相等的 LinkProtocol 声明；
- 一个 port 只能属于一条内部 link 或一个 system boundary；
- 所有声明端口都必须连接或暴露为 boundary；
- 各 DUT、link、system semantic fragment 获得独立 namespace。

当前尚未实现 profile 协商、clock/reset compatibility、capability negotiation 和 address closure。因此
“ProtocolPort 有 capability 字段”不等于系统已能自动判断所有能力组合。

实现见 [`system/elaboration.py`](../../../protocol_model/system/elaboration.py)。

<a id="runtime"></a>
## 4. SystemSession：立即反应传播到固定点

一次 `SystemAction` 指定某个 VirtualDut port 发出 canonical event。SystemSession：

1. 找到该端口属于哪条 link；
2. 检查事件方向是否允许该 role 发送；
3. 推进这条 link 自己的 LinkSession；
4. 记录具体 source、destination、channel 和全局 event index；
5. 把事件交给目标 VirtualDut backend；
6. 将 backend 的立即 emissions 放回队列；
7. 重复到队列为空或超过 `max_internal_steps`。

这里的 fixed point 表示“当前立即反应队列已空”，不是一个 RTL cycle，也不是 deadlock 证明。当前没有
deferred emission、timer、latency 或多时钟调度。

如果传播中后续出现 fault，当前实现保留此前已经通过的逐跳状态与事件；整个 cascade 还不是全局事务式
回滚。

实现见 [`system/session.py`](../../../protocol_model/system/session.py)。

<a id="bridge-fabric"></a>
## 5. 互连模块的内外边界

一个物理 bridge/crossbar 可以作为单个多端口 VirtualDut：

```text
SystemProtocol topology
  A ─ link A ─ [bridge VirtualDut] ─ link B ─ B
                    │
                    └─ backend 内部保存 transform / route / owner
```

- wire fragment join 属于各端口 attachment；operation fanout/fold 与 route policy 属于 stage/plan；
  queue、schedule、lease 和返回 owner 属于这个 VirtualDut executor/backend；
- bridge 外部端口连到哪些模块属于 SystemProtocol；
- 每条外部 link 的局部合法性属于各自 LinkProtocol。

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
- hide internal links 后的 boundary refinement。

地址 gap 若 fabric 明确返回 DECERR，不一定是结构错误；全地址覆盖可以是具体验证场景的 property。系统层
需要区分结构闭合与更强的场景目标。

<a id="recursive-composition"></a>
## 7. 递归组合与物理尺度

`SystemProtocol.as_virtual_dut()` 将 system boundary 重新包装成 VirtualDut：

```text
module → subsystem → SoC → chiplet/package → board
```

因此跨片协议仍由 LinkProtocol、VirtualDut、SystemProtocol 递归表达，不必为每个物理尺度增加固定顶层
类。当前封装完成结构与语义投影，外层 runtime 尚不会自动执行嵌套 subsystem 的内部 session。

更完整的系统架构见 [SystemProtocol 文档](../system-protocol.md)。下一步阅读：
[组网构建阶段](../network-construction.md) 或 [观察、执行与证据](06-observation-execution-evidence.md)。
