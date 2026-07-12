# VirtualDut Methodology

## 它是什么

VirtualDut 是验证环境中的可执行功能节点，不是 RTL 生成器，也不要求逐周期模拟硬件。

```text
Protocol      规定端口上哪些通信行为合法
VirtualDut    在合法行为中选择输入处理、功能状态变化和输出
Project       把Protocol link、VirtualDut、case和证据连接起来
```

统一接口仍是：

```python
step(state, input_action) -> SemanticStep(
    state=new_state,
    emissions=(output_actions...),
    fault=...,
)
```

此外 VirtualDut 声明：

- `kind`：source、sink、responder、transform、proxy；
- `ports`：拥有的输入和输出；
- `capabilities`：可查询的能力；
- `contract.assumptions`：对输入的假设；
- `contract.guarantees`：对输出的保证；
- `contract.invariants`：功能状态不变量。

## 基础原语

公共 `virtual_dut/` 当前只包含能跨项目复用的构造块：

| Primitive | 行为 |
|---|---|
| `Sink` | 消费输入，不产生输出；可选择保留输入用于诊断 |
| `ScriptedSource` | 按配置顺序发射动作；scheduler用`EmitNext`推进 |
| `FunctionResponder` | 通过一个Python callable把输入映射为零个或多个输出 |

registry：

```python
registry = VirtualDutRegistry.standard()
sink = registry.create("sink", name="dropper")
source = registry.create("scripted_source", sequence=(a, b, c))
```

最小端到端用法见 `projects/prj_ready_valid_sink/`：`ScriptedSource` 发出逐周期样本，
ready-valid protocol monitor 只在握手完成时产生 transfer，`Sink` 只消费这些已接受事件。

具体 AXI bridge、APB peripheral、UART device 不注册为全局原语；它们先放在使用它们的
Project 中。出现真正复用后再提升。

## Virtual FPU

测试 FPU RTL 时，可以把 bit-exact reference model 包装成一个 VirtualDut：

```python
@dataclass(frozen=True)
class FpuRequest:
    op: str
    lhs: int
    rhs: int
    rounding: str

@dataclass(frozen=True)
class FpuResult:
    value: int
    flags: int

backend = SoftFloatCProxy("libsoftfloat_model.so")

virtual_fpu = FunctionResponder(
    lambda request: (backend.execute(request),),
    name="virtual_fpu",
    capabilities=frozenset({"fp32", "fp64", "ieee754_flags"}),
    contract=VirtualDutContract(
        assumptions=("request encoding is valid",),
        guarantees=("result is bit-exact for the selected rounding mode",),
    ),
)
```

后端可以是：

- 纯 Python；
- NumPy 或其他数值库（注意 NaN payload/rounding 差异）；
- `ctypes`/`cffi` 调用 C/C++ reference model；
- subprocess/RPC 代理外部模型；
- 已有 ISS、SoftFloat 或算法库。

VirtualDut 不关心 RTL 使用 ready-valid、APB 寄存器还是自定义 request/response。Project
负责把 monitor 输出的 canonical transaction 转为 `FpuRequest`，并把 RTL 输出与
`FpuResult` 对齐比较：

```text
RTL pins → protocol monitor → FpuRequest ─┐
                                          ├→ correlation/scoreboard
VirtualFpu backend → FpuResult ───────────┘
```

如果要模拟 pipeline latency、out-of-order tag 或 backpressure，应在 VirtualDut state/policy
中显式增加 pending queue、latency clock 和 output ownership；不要把这些测试策略写进 FPU
数学函数。

## C Proxy 的边界

C proxy 是功能 backend，不是协议 checker。建议固定：

- 明确 ABI 和 bit-vector 编码；
- 记录库版本和构建 hash；
- 相同输入必须确定性地产生相同输出；
- C exception/error 转成 `SemanticFault(scope="DUT")`；
- NaN、subnormal、rounding 和 exception flags 使用位级值，而不是宿主浮点近似；
- backend 调用与协议 handshake 分离，便于替换 Python/C/remote 实现。

## 何时提升为公共 VirtualDut

满足以下条件再从 Project 移入公共 `virtual_dut/`：

1. 至少两个 Project 使用同一行为；
2. 不依赖某个 Project 的 topology、case 或 artifact；
3. ports、contract 和 capability 可以独立说明；
4. 输入输出不包含某个测试的临时字段；
5. 有一个正向行为和一个 fault witness。
