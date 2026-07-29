# 端到端示例：一次 APB 寄存器读取

[返回架构地图](README.md) · [查看总览图](overview.svg) · [术语表](../terminology.md)

读者可以先把一次读取理解为：“请求方给出地址，目标方返回数据或错误”。后文再把这条关系映射到 APB
接口合同和 VirtualDut operation。

## 场景

```text
manager VirtualDut
    │
    │ APB InterfaceConnection
    ▼
register-bank VirtualDut
    └── AddressSpace
          └── register @ 0x1000 = 0x11223344
```

APB 接口上的请求是：

```python
CanonicalEvent("READ", None, {"addr": 0x1000, "prot": 0})
```

这是 APB observation 或 transaction adapter 从 pin/transaction 输入提炼出的 canonical 协议事件。

## 事件经过的对象

### 1. 请求进入 SystemProtocol

当前同步执行入口通过 `SystemAction` 指定“哪个 VirtualDut 的哪个端口发出了什么事件”。SystemSession
找到拥有该端口的 `InterfaceConnection`，并根据事件所在 channel 判断目标角色。

这里先解决的是连接问题：请求从哪里来、沿哪条 interface connection、应该送到哪个具体端口。

### 2. InterfaceSession 检查 APB 局部规则

InterfaceSession 检查：

- 事件名是否为 APB `READ`；
- payload 是否包含合法宽度的 `addr` 和 `prot`；
- requester 是否有权发送它；
- 当前是否已经存在一个尚未完成的 APB transfer。

这些判断以一条 APB interface connection 为完整观察范围，因此由 InterfaceProtocol 拥有。寄存器模块负责
访问结果，SystemProtocol 负责跨 module 连接。

### 3. 事件到达 completer InterfacePort

目标 VirtualDut 的端口声明自己承担 `completer` role。它绑定的 `ApbCompleterAttachment` 把 APB 语言
翻译为协议无关操作：

```text
APB READ(addr=0x1000, prot=0)
        ↓ decode
AddressRead(address=0x1000, size=4, attributes={prot: 0})
```

AddressSpace 保持协议中立，因此同一地址访问语义可以复用于 AHB、AXI4-Lite 或外部 RPC 接口。各
integration attachment 分别处理协议运输差异。

### 4. backend 执行 AddressRead

`PassiveAddressSpaceBackend` 把 AddressRead 交给 AddressSpace。AddressSpace 根据 region 找到寄存器，
读取其当前状态并形成 `AccessResult`：

```text
AccessResult(status=OK, data=0x11223344)
```

若地址没有命中，结果是 `DECODE_ERROR`；写只读寄存器则可能是 `ACCESS_ERROR`。这些是设备的正常访问
结果，由 attachment 映射为协议响应。模型基础设施故障另用 fault 表达。

### 5. attachment 编码 completion

同一个 completer attachment 保存了足够的 reply context，知道这是一次 READ，于是把结果翻译回 APB：

```python
CanonicalEvent(
    "READ_RESPONSE",
    None,
    {"data": 0x11223344, "error": False},
)
```

它在提交自身接口侧状态前检查输出事件的方向和 schema，使 completion state 与合法响应原子提交。

### 6. 响应沿同一 InterfaceConnection 返回

SystemSession 将 backend emission 放回传播队列。InterfaceSession 检查 `READ_RESPONSE` 是否正好解除之前的
pending read，并建立 request → response 的因果边；随后响应送到 manager 端口。

如果 manager 使用 CaptureBackend，响应会被记录；如果它是外部 RTL/RPC backend，响应会交给外部实现。

## 这个示例分别验证了什么

| 作用域 | 本例中的判断 |
|---|---|
| Event | 地址、保护位、数据和错误字段是否合法 |
| InterfaceProtocol | requester/completer 方向、single outstanding、request/response 配对 |
| attachment | APB event 与 AddressRead/AccessResult 之间是否正确转换 |
| VirtualDut | 哪个 AddressSpace 被访问、寄存器返回什么结果 |
| SystemProtocol | 端口连接、事件路由、具体 connection 实例和全局因果记录 |

## Blackhole sink 的执行结果

blackhole sink 接收 `READ` 后保留 pending resource，并持续处于非 quiescent 状态。有限运行通常把这个
挂起场景判为 `INCONCLUSIVE`；正常 APB target 则通过 `READ_RESPONSE` 解除 obligation。

## 当前实现与目标实现的区别

当前示例通常用 `SystemAction` 显式注入最初的 READ。未来增加自主/deferred emission 后，manager backend
可以先产生协议无关 `AddressRequest`，再由 `ApbRequesterAttachment` 编码 READ。后续的 InterfaceProtocol、
SystemProtocol 和 completer 路径保持同一合同。
