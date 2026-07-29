# Runtime

## 定位

`runtime` 执行已经 elaborated 的 system topology 和 resolved plan，并保存 action loop、session state、trace、
scheduler 与 emission lineage。转换选择与 topology lowering 在 construction 阶段完成。

## 输入

当前根 `SystemSession` 接收：

- `ElaboratedSystemProtocol`；
- 从具体 VirtualDut port 发出的 `SystemAction`；
- 推进具备显式 advance contract 的 backend 的 `DutAdvanceAction`。

transport family session 读取 `ElaboratedSystemProtocol.transport_plan`，按 family profile 执行 caller
声明的 directed hops。

## 输出与状态归属

| 对象 | 持有的运行事实 |
|---|---|
| `SystemSessionState` | interface session state、DUT state snapshot、全局事件索引和 causal edges |
| `SystemEvent` | 一次跨 connection 传播的 source、destination 与 canonical event |
| `SystemTrace` | 已接纳事件与因果图投影 |

根 session 当前执行 `InterfaceConnection`，并沿传播队列处理因果触发的 backend emission。
family transport session 保存 hop/router 的 transport 状态。通用 scheduler、延迟 emission lineage 和统一
interface/transport action loop 按 Roadmap 收敛。

## 公共入口

当前可执行对象实现在 [`../session.py`](../session.py)，并从根 facade 导入：

```python
from protocol_model.system import (
    DutAdvanceAction,
    SystemAction,
    SystemEvent,
    SystemSession,
    SystemSessionState,
    SystemTrace,
)
```

`protocol_model.system.runtime` 当前提供职责包入口，`__all__` 为空；可执行名称保留在根 facade。

## 相邻链接

- [SystemProtocol 源码导航](../README.md)
- [Resolution](../resolution/README.md)
- [Monitors](../monitors/README.md)
- [Analysis](../analysis/README.md)
- [Roadmap](../../../docs/architecture/technical-route/08-roadmap.md)
