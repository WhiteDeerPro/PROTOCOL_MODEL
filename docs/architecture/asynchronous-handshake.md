# 异步 REQ/ACK 握手的建模边界

## 1. 定位与术语

REQ/ACK 握手首先是一种点到点传输的信号编码。它规定发送方和接收方怎样交替改变控制线，使一次 token
或一份 bundled data 被接收。它可以承载控制通知、数据 beat 或某个已有协议 channel 的 event；承载内容由
上层 `EventSchema` 决定。

异步电路资料通常使用两类名称：

- **four-phase / return-to-zero / level signalling**：REQ 和 ACK 每轮各有上升、下降两个动作；
- **two-phase / non-return-to-zero / transition signalling**：REQ 和 ACK 每轮各翻转一次，上升沿和下降沿等价。

“three-phase REQ/ACK”在不同材料中指代不同。有些材料把 data change、request transition、acknowledge
transition 口语化为“三步”，对应的控制编码仍属于 two-phase。采用
`REQ↑ → ACK↑ → combined return` 的 DUT 需要另外声明 return 偏序、完成点和下一请求条件；observer 按两条
独立信号的实际 transition 保存顺序。公共模型因此使用具名的 four-phase RTZ profile，后续 two-phase 采用
独立 toggle profile。

## 2. 四相运行机制

当前 profile 使用 active-high REQ/ACK，正常状态循环为：

```text
               receiver accepts
                      │
                      ▼
idle 00 ──REQ↑──► requested 10 ──ACK↑──► acknowledged 11
   ▲                                             │
   │                                             │ REQ↓
   └────────────── ACK↓ ───── returning 01 ◄────┘
```

每个状态都允许停留任意数量的 observation samples。这一自环表达发送端或接收端的等待，profile 本身
保持 latency 开放。安全规则如下：

| 当前状态 | 合法的下一控制动作 | 稳定条件或效果 |
|---|---|---|
| idle `00` | `REQ↑` | 进入 requested |
| requested `10` | `ACK↑` | ACK 前保持 REQ；接纳一个 canonical `TRANSFER` |
| acknowledged `11` | `REQ↓` | REQ 前保持 ACK |
| returning `01` | `ACK↓` | ACK 下降后释放 wire slot，随后可开始下一请求 |

一个 observation step 承载一条相关控制 transition。完整归零负责释放 wire slot，每轮只在 ACK 上升时产生
一次 event。

有限 trace 停在 `10`、`11` 或 `01` 时，结果为 `INCONCLUSIVE`。“REQ 最终得到 ACK”属于 progress
obligation，其证明还需要接收端公平性和相关 clock 最终运行等环境假设；相位状态机提供这一证明的 safety
前提。

## 3. Bundled data 的有效窗口

four-phase 只规定控制线次序，data-valid window 仍需要 profile 明确选择。当前 observer 提供：

| profile | event identity 的稳定窗口 | 适用直觉 |
|---|---|---|
| `EARLY` | REQ 上升至 ACK 上升 | 接收方在 ACK 时已经 capture；默认的较宽松约束 |
| `EXTENDED_EARLY` | REQ 上升至 REQ 下降 | `REQ=1` 期间 data 始终可解释 |
| `BROAD` | REQ 上升至 ACK 下降 | 整轮 return-to-zero 都保留 data |

observer 比较 canonical event identity，即 kind、key 和 payload，并报告稳定窗口内的数据覆盖或 token
替换。离散 snapshot 覆盖逻辑事件顺序；CDC/STA 约束、结构检查或更具体的 physical observation profile
负责证明 REQ 前的物理 setup、capture 后的 hold，以及 bundled-data datapath 相对同步后 REQ 的裕量。

## 4. 工程中的落点

```text
raw REQ / ACK / bundled data
            │ edge-complete snapshots
            ▼
AsynchronousSample                 observation：保存顺序，不宣称共享 clock
            │
            ▼
FourPhaseObserver                  encoding：相位、reset、data window
            │ accepted TRANSFER
            ▼
InterfaceSession / InterfaceProtocol  interface-local event schema 与语义
            │ InterfaceConnection
      ┌─────┴─────┐
      ▼           ▼
sender port   receiver port        VirtualDut boundary：role/domain 声明
      │           │
 attachment   attachment           integration：event 与具体 operation 互译
      │           │
      ▼           ▼
VirtualDut backend                 module 行为
```

这里有两种使用方式：

1. **已有 channel 使用四相编码。** `FourPhaseObserver` 直接接收该 channel 的 `EventSchema`，所以 AXI 之外的
   control event、stream transfer 或项目自定义 event 都可以采用这套 encoding。VirtualDut 仍 attachment
   原有的 InterfaceProtocol/operation，module 类型继续按其业务行为命名。
2. **独立 token interface。** `build_four_phase_token_interface()` 提供 `sender`、`receiver` 两个 role 和一个
   `TRANSFER` channel。它可以直接放在两个 `InterfacePort` 上；可选 `data_width` 决定是否携带 bundled data。

`FourPhaseSignals.event` 由上游 trace importer 或 driver 按目标 `EventSchema` 组装；control-only token 也会携带
一个无 payload 的 `CanonicalEvent`，其 key 作为模型侧 occurrence label。裸 REQ 电平只提供传输编码，
`CanonicalEvent` 提供业务含义；observation sequence 保存有序样本索引。

interface/observation trace 验证在 observer 或 session 处结束。模块消费 token 的场景再增加 integration
attachment，根据用途将 `TRANSFER` 解码成 `Notification`、`StreamTransfer` 或专用 operation；每个
attachment 显式声明自己的业务映射。

## 5. 与 CDC 和 SystemProtocol 的边界

四相信号次序可以跨越两个独立 clock domain。逻辑握手与 CDC 实现分别接受验证；一个常见 CDC 实现会：

- 在接收域同步单比特 REQ，在发送域同步单比特 ACK；
- 源端寄存并保持 bundled data，接收端在看到同步后的 REQ 后整体 capture；
- 对异步 reset 的 deassert 分别做域内同步；
- 将中途或单边 reset 送入独立的 abort/recovery path。

各判定范围拥有以下事实：

| 范围 | 当前输入与判定 |
|---|---|
| `FourPhaseObserver` | edge-complete 逻辑 snapshots、相位顺序、data window 与协调 reset epoch |
| CDC/STA/formal | 同步器结构、首级扇出、亚稳态假设、多位 data 偏斜与域内 reset recovery |
| `SystemProtocol` | clock/reset domain、CDC contract、abort/replay policy 与跨连接 progress |

SystemProtocol 后续闭合：

- 两端 `clock_domain`、`reset_domain` 的声明；
- 跨域连接引用了允许的 CDC module/contract；
- reset abort、epoch 或 replay policy；
- 多条异步连接形成网络后产生的 wait-for 与 progress 关系。

当前 `InterfacePort` 保存 clock/reset domain 名称；这些名称以待解析声明进入后续 system elaboration。

这里的“异步”表示接口两侧使用独立采样 clock。`FourPhaseObserver` 消费调用方提供的有序 samples。
VirtualDut backend 自主调度以及 deadline、timer、跨域全局时间属于 system/runtime 的后续工作。

## 6. 当前实现

- `protocol_model/protocols/asynchronous/four_phase/`：独立 token InterfaceProtocol；
- `protocol_model/observation/asynchronous.py`：无共享 clock 声明的有序 snapshot；
- `protocol_model/observation/four_phase.py`：四相 FSM、三种 data window、协调 reset；
- 维护侧回归覆盖完整周期、停顿、非法 ACK、payload 稳定、reset abort 和跨域端口声明。

下一步适合在出现实际场景时增加 two-phase toggle profile、具体 notification/stream attachment，以及
SystemProtocol 的 clock/reset-domain closure。同步器的物理正确性继续交由 CDC lint、STA 或针对性 formal
harness 检查，Protocol Model 负责保存其抽象合同与端到端语义证据。

## 7. 参考

- [Jens Sparsø, *Introduction to Asynchronous Circuit Design*](https://orbit.dtu.dk/en/publications/introduction-to-asynchronous-circuit-design/)
- [Ivan Sutherland, *Micropipelines*](https://doi.org/10.1145/63526.63532)
- [Furber and Day, *Four-Phase Micropipeline Latch Control Circuits*](https://apt.cs.manchester.ac.uk/ftp/pub/apt/papers/4phCtl.pdf)
