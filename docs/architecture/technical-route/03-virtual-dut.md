# VirtualDut：只把模块描述到通信需要的深度

[返回架构地图](README.md) · [协议集成与绑定](04-integration-and-binding.md) · [术语表](glossary.md)

VirtualDut 首先表示系统图中的一个具体、具名 module。它是“虚拟”的，因为行为可以来自 Python 模型、
外部 RTL、RPC、trace 或嵌套系统；并不意味着它只是一个轻量 agent，也不要求内部状态有限或可枚举。

<a id="operations"></a>
## 1. 协议无关操作：模块真正关心的事情

CPU 或总线看到的是地址、数据和 completion，而不是“某个外设类”。因此构造可执行参考模块时，先抽取
协议无关操作：

- `AddressRead` / `AddressWrite`：访问 byte range；
- `AccessResult`：OK、decode error、access error；
- token/effect：请求、完成、通知和内部影响；
- Source、Sink、Transform、Store、Route、Correlate 等行为意图。

当前代码已经完整实现 AddressAccess、AddressSpace、RegisterRegion、MemoryRegion，以及一套范围有限但
可执行的 AddressFabric 实现。通用 Source/Store/Arbitrate 算子仍主要是目标方法，不应在图中画成已经
齐备的库。

相关实现见 [`virtual_dut/address/`](../../../protocol_model/virtual_dut/address/)。

<a id="backend"></a>
## 2. Backend：模块行为的权威来源

Backend 回答：“收到一个输入后，模块状态怎样变化，会从哪些端口产生什么输出？”

```text
(opaque or constructed state, PortInput)
    → (new state, PortEmission*, fault?)
```

它可以有多种形态：

| backend 形态 | 适用场景 |
|---|---|
| external RTL/RPC | 被测模块或已有权威模型，不重建内部算法 |
| trace replay | 重复已有场景 |
| Python oracle | 功能参考模型 |
| constructed backend | 流量源、寄存器、memory、bridge、crossbar fixture |
| composite subsystem | 把内部 SystemProtocol 封装成更大 module |

项目验证 backend 的协议可见行为，不证明 backend 内部算法。只有验证目标需要时，才把 FIFO、owner table、
route 或随机状态显式构造出来。

公共接口见 [`backend/base.py`](../../../protocol_model/virtual_dut/backend/base.py)。

### 状态放在哪里

- attachment 保存单端口运输状态，例如 APB pending、AHB phase context、AXI AW/W join；
- backend 保存功能状态和跨端口关系，例如寄存器内容、route、request owner；
- LinkSession 保存某条 link 的协议状态；
- SystemSession 保存各 link 与各 VirtualDut 的一次运行状态。

把这些状态合并成一个大 FSM 会使每增加一个协议或端口都产生组合爆炸，因此工程按作用域分别拥有。

<a id="construction"></a>
## 3. VirtualDutBuilder：把边界和实现装配起来

构造顺序是：

```text
声明 ProtocolPort
    + 选择 attachment / binding
    + 选择 backend
    + 可选 capability / clock / reset / semantics
    → VirtualDutBuilder.build()
    → immutable VirtualDut
```

Builder 做构造期一致性检查，不执行协议。最终 VirtualDut 保存具名 ports、静态 bindings、backend 和边界
语义；运行状态属于 Session/backend state，不塞进静态声明。

实现见 [`binding/builder.py`](../../../protocol_model/virtual_dut/binding/builder.py)。

<a id="virtualdut"></a>
## 4. 模块身份与协议端口分离

不建立 `AxiDevice → AxiMemory → AxiDma` 这样的类型树。一个 AddressSpace backend 可以通过不同
attachment 成为 APB、AHB 或 AXI endpoint；一个 bridge 可以同时拥有不同协议端口。

模块名称由具体系统角色决定，能力由端口、binding 和 boundary contract 表达。协议名称不会变成模块的
身份父类。

```text
VirtualDut "peripheral_fabric"
├── upstream : APB completer port
├── control  : APB requester port
├── status   : APB requester port
└── backend  : route + pending owner + response mux
```

这既可以画成传统“一条总线挂设备”，也可以画成星形连接；底层 topology 仍是明确的 port-to-port links。

实现见 [`boundary/module.py`](../../../protocol_model/virtual_dut/boundary/module.py)。

## 5. 互连 module 的行为形态

它们是多端口 VirtualDut 的行为形态，而不是新的协议层：

| 形态 | 主要行为 |
|---|---|
| bridge | 1→1，协议/宽度/burst/ordering/error 转换 |
| decoder-mux | 1→N，地址解码和 completion return |
| arbiter-mux | N→1，admission、选择和 owner 保存 |
| crossbar | N→M，route、arbitration、并发和 response correlation |

若需要验证内部 FIFO 或仲裁器，可以把一个物理 crossbar 展开成内部多个 VirtualDut + SystemProtocol，再
通过 `as_virtual_dut()` 封装回同一外部边界。

Bridge 内部 operation form、typed stage 和 executor 的完整构造见
[Bridge 与类型化事务转译](../typed-transaction-translation.md)。

## 6. 空行为 endpoint fixture

当前 APB、AHB-Lite、AXI4 提供两类空 recipe：

- `idle source`：本地 backend 不自主产生 canonical event；显式 SystemAction 仍可注入测试流量；
- `blackhole sink`：接收后不产生 completion，留下 pending，用于 hang/deadlock 场景。

它们描述 canonical-event 层行为，不表示 raw pin 上已经把 VALID tied-low 或 READY 固定。正常错误 responder
仍需要协议专用 attachment 按规则返回完整 completion。

## 当前实现信息

VirtualDut、address/stream operation、AMBA attachment、fabric 和 bridge 的覆盖范围集中维护在
[当前实现状态](../implementation-status.md)；本页不复制易变化的能力清单。更完整的方法论见
[VirtualDut 架构文档](../virtual-dut.md)。下一步阅读：[协议集成与端口绑定](04-integration-and-binding.md)。
