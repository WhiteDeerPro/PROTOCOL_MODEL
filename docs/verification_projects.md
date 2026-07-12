# Verification Projects

## 用户面对的对象

验证工程师主要操作 Project，而不是直接操作 engine。Project 表示一个可以创建、配置、
运行、判断和归档的验证任务：

```text
Project
├── cases                 激励参数与预期结果
├── component inventory  protocol link、VirtualDut、renderer
├── verification plan    项目内部的连接和调用关系
├── lifecycle history    当前执行阶段
├── state                verdict、fault、event count
└── artifacts            波形、因果图、HTML
```

每个不同项目使用独立、有意义的包名：

```text
projects/
├── base.py
├── prj_axi4_read_bridge/
├── prj_apb_peripheral/       # future
└── prj_uart_fabric/          # future
```

## 最小项目：prj_ready_valid_sink

```text
ScriptedSource VirtualDut
    ↓ ReadyValidSample
ReadyValid ProtocolSpec / ClockedReadyValid
    ↓ DATA_TRANSFER
Sink VirtualDut
```

这个项目刻意不含网络和专用报告，用于证明最小组合边界：Source 可以产生任意 pin sample，
但只有 Protocol 接受的 transfer 才会到达 Sink。

合法 case 包含一次 stall：

```text
samples=4 → transfers=2 → sink.received=2 → CHECKED
```

mutation 在 stall 期间改变 payload：

```text
data.ready_valid.payload_stability → sink.received=0 → CHECKED
```

直接调用 `Project.run_case()` 只返回状态，不生成文件。CLI 命令另外执行项目 renderer，
生成 waveform、event graph、topology 和 HTML：

```bash
.venv/bin/python -m protocol_model ready-valid-sink
```

默认输出位于该 Project 包根目录的 `sims/01/`：

```text
projects/prj_ready_valid_sink/sims/01/
```

可随时整体删除并重新生成。使用者可以指定目录：

```bash
.venv/bin/python -m protocol_model ready-valid-sink --sim-dir /tmp/my_sim
```

case 选择、图的种类、文件命名和 lifecycle publish 均由
`projects/prj_ready_valid_sink/simulation.py` 构造；CLI 只传递 `--sim-dir`。

## 生命周期

```text
CREATED → ELABORATED → EXECUTED → CHECKED → REPORTED → CLOSED
                         │
                         └──────────────→ FAILED → REPORTED/CLOSED
```

`FAILED` 表示观察结果不符合 case expectation，而不是简单地出现 violation。期望触发
4KB crossing 的 negative case，在确实观察到 violation 后进入 `CHECKED`。

## Protocol、VirtualDut 与验证计划

三者责任不同：

```text
Protocol     限定一条link允许哪些通信行为
VirtualDut   选择、终止或转换合法行为，并保存功能状态
Project plan 实例化protocol与VirtualDut并在项目内部组网
```

当前没有顶层 `network/` 包。网络属于具体验证计划，因为 topology、参与节点、连接、case
和期望都由 Project 决定。若未来多个项目出现完全相同的 topology/runtime 机制，再提炼为
通用 foundation；现在不提前制造抽象。

## 当前项目：prj_axi4_read_bridge

```text
AxiReadCase
    │
AXI-A ProtocolSession
    │ AR/R
AxiReadBridge (project VirtualDut)
    │ AR/R
AXI-B ProtocolSession
    │
DumbAxiReadResponder (FunctionResponder specialization)
```

组件清单：

| Name | Category | Implementation | Role |
|---|---|---|---|
| stimulus | test | `AxiReadCase` | 注入读burst及其期望 |
| AXI-A | link | `ProtocolSession[AXI4]` | 上游协议实例 |
| bridge | virtual_dut | `AxiReadBridge` | 非终端转发、ID remap、correlation |
| AXI-B | link | `ProtocolSession[AXI4]` | 下游协议实例 |
| responder | virtual_dut | `DumbAxiReadResponder` | 终止AR并产生R beat |

项目内部 `network.py` 提供：

- `LinkRuntime`：每条 link 独立的 `ProtocolSessionState`；
- `NetworkRecorder`：把 link-local event index 映射到全局 trace 和因果边。

默认合法 case 使用 `ARADDR=0xFF0, ARLEN=3, ARSIZE=2, INCR`：

```text
after AR on A:       A=1 bridge=0 B=0
after forwarded AR:  A=1 bridge=1 B=1
after R beat 0..2:   A=1 bridge=1 B=1
after final R:       A=0 bridge=0 B=0
```

地址改为 `0xFF4` 后越过 4KB，请求在 AXI-A 被拒绝，bridge 和 AXI-B 保持初态。

## 信号与证据

global network timeline 被投影成 AXI-A、AXI-B 两张同周期轴 ready-valid 波形。read-only
case 中 AW/W/B 始终 quiet，因此显示层省略这些通道；隐藏不改变协议验证语义。

运行：

```bash
.venv/bin/python -m protocol_model axi-read-network
```

默认报告：`projects/prj_axi4_read_bridge/sims/01/index.html`。也可以通过
`axi-read-network --sim-dir <path>` 覆盖。

## 当前边界

- Project runner 仍显式调用 link、bridge 和 responder；
- 尚无通用 ComponentGraph、自动 port routing 或 topology elaboration；
- responder 没有 memory 状态，只产生确定性 payload；
- 没有 latency/backpressure policy；
- 没有 literal ring、仲裁、公平性或死锁探索；
- 尚未连接 VCD/FSDB/UVM adapter。
