# 端到端示例：一次 APB 寄存器读取

[返回架构地图](README.md) · [查看总览图](overview.svg) · [术语表](glossary.md)

这份示例不要求读者预先了解 APB 信号时序。只需要把一次读取理解为：“请求方给出地址，目标方返回
数据或错误”。

## 场景

```text
manager VirtualDut
    │
    │ APB ProtocolLink
    ▼
register-bank VirtualDut
    └── AddressSpace
          └── register @ 0x1000 = 0x11223344
```

APB 链路上的请求是：

```python
CanonicalEvent("READ", None, {"addr": 0x1000, "prot": 0})
```

它不是原始 pin 波形，而是 APB observation 或 transaction adapter 已经提炼出的协议事件。

## 事件经过的对象

### 1. 请求进入 SystemProtocol

当前同步执行入口通过 `SystemAction` 指定“哪个 VirtualDut 的哪个端口发出了什么事件”。SystemSession
找到拥有该端口的 `ProtocolLink`，并根据事件所在 channel 判断目标角色。

这里先解决的是连接问题：请求从哪里来、沿哪条 link、应该送到哪个具体端口。

### 2. LinkSession 检查 APB 局部规则

LinkSession 检查：

- 事件名是不是 APB 的 `READ`；
- payload 是否包含合法宽度的 `addr` 和 `prot`；
- requester 是否有权发送它；
- 当前是否已经存在一个尚未完成的 APB transfer。

这些判断只需要观察一条 APB link，因此属于 LinkProtocol，而不是寄存器模块或整个网络。

### 3. 事件到达 completer ProtocolPort

目标 VirtualDut 的端口声明自己承担 `completer` role。它绑定的 `ApbCompleterAttachment` 把 APB 语言
翻译为协议无关操作：

```text
APB READ(addr=0x1000, prot=0)
        ↓ decode
AddressRead(address=0x1000, size=4, attributes={prot: 0})
```

为什么不让 AddressSpace 直接认识 APB？因为同一个 AddressSpace 以后也可以挂到 AHB、AXI4-Lite 或
外部 RPC 接口上。地址访问语义可以复用，协议运输差异留给各自 integration。

### 4. backend 执行 AddressRead

`PassiveAddressSpaceBackend` 把 AddressRead 交给 AddressSpace。AddressSpace 根据 region 找到寄存器，
读取其当前状态并形成 `AccessResult`：

```text
AccessResult(status=OK, data=0x11223344)
```

若地址没有命中，结果是 `DECODE_ERROR`；写只读寄存器则可能是 `ACCESS_ERROR`。这些是设备的正常访问
结果，不默认当作模型基础设施故障。

### 5. attachment 编码 completion

同一个 completer attachment 保存了足够的 reply context，知道这是一次 READ，于是把结果翻译回 APB：

```python
CanonicalEvent(
    "READ_RESPONSE",
    None,
    {"data": 0x11223344, "error": False},
)
```

它在提交自身运输状态前检查输出事件的方向和 schema，避免“已经认为完成，但生成了非法响应”的状态
分叉。

### 6. 响应沿同一 ProtocolLink 返回

SystemSession 将 backend emission 放回传播队列。LinkSession 检查 `READ_RESPONSE` 是否正好解除之前的
pending read，并建立 request → response 的因果边；随后响应送到 manager 端口。

如果 manager 使用 CaptureModel，响应会被记录；如果它是外部 RTL/RPC backend，响应会交给外部实现。

## 这个示例分别验证了什么

| 作用域 | 本例中的判断 |
|---|---|
| Event | 地址、保护位、数据和错误字段是否合法 |
| LinkProtocol | requester/completer 方向、single outstanding、request/response 配对 |
| attachment | APB event 与 AddressRead/AccessResult 之间是否正确转换 |
| VirtualDut | 哪个 AddressSpace 被访问、寄存器返回什么结果 |
| SystemProtocol | 端口连接、事件路由、具体 link 实例和全局因果记录 |

## Blackhole sink 的执行结果

blackhole sink 接收 `READ` 后不返回 `READ_RESPONSE`。这一步本身不一定立即产生 safety fault，但 APB
pending resource 不会释放，系统也不会 quiescent。它表达“请求被环境吞掉”的挂起场景，而不是一个
功能完整的 APB target。

## 当前实现与目标实现的区别

当前示例通常用 `SystemAction` 显式注入最初的 READ。未来增加自主/deferred emission 后，manager backend
可以先产生协议无关 `AddressRequest`，再由 `ApbRequesterAttachment` 编码 READ。后续的 LinkProtocol、
SystemProtocol 和 completer 路径不需要因此改变。
