# 异步 REQ/ACK 握手的建模边界

## 1. 定位与术语

REQ/ACK 握手首先是一种点到点传输的信号编码。它规定发送方和接收方怎样交替改变控制线，使一次 token
或一份 bundled data 被接收。它可以承载控制通知、数据 beat 或某个已有协议 channel 的 event；承载内容由
上层 `EventSchema` 决定。

异步电路资料通常使用两类名称：

- **four-phase / return-to-zero / level signalling**：REQ 和 ACK 每轮各有上升、下降两个动作；
- **two-phase / non-return-to-zero / transition signalling**：REQ 和 ACK 每轮各翻转一次，上升沿和下降沿等价。

“three-phase REQ/ACK”没有同等明确的通用定义。有些材料把 data change、request transition、acknowledge
transition 三个事件口语化为“三步”，所指控制协议仍可能是 two-phase。若某个 DUT 真的采用
`REQ↑ → ACK↑ → combined return`，还需要定义 return 的偏序、完成点和下一请求条件；异步观察不能把两条
独立信号的同时下降当作隐含的原子动作。因此公共模型先使用具名的 four-phase RTZ，后续 two-phase 也应建立
独立 profile，不提供含义模糊的 `phases=3` 参数。

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

每个状态都允许停留任意数量的 observation samples。这一自环表达发送端或接收端的等待，也避免由模型擅自
加入固定 latency。安全规则包括：

- `00 → 10 → 11 → 01 → 00` 保持顺序；
- 一个 observation step 只出现一条控制线的相关 transition；
- `10` 状态不能在 ACK 前撤销 REQ；
- `11` 状态不能在 REQ 前撤销 ACK；
- `01` 返回 `00` 前不能开始下一请求；
- ACK 上升时产生一个 canonical `TRANSFER`，完整归零只负责释放 wire slot，不重复产生 event。

有限 trace 停在 `10`、`11` 或 `01` 时，结果为 `INCONCLUSIVE`。例如“REQ 最终得到 ACK”属于 progress
obligation，需要接收端公平性和相关 clock 最终运行等环境假设；它不能从相位 safety 状态机单独推出。

## 3. Bundled data 的有效窗口

four-phase 只规定控制线次序，data-valid window 仍需要 profile 明确选择。当前 observer 提供：

| profile | event identity 的稳定窗口 | 适用直觉 |
|---|---|---|
| `EARLY` | REQ 上升至 ACK 上升 | 接收方在 ACK 时已经 capture；默认的较宽松约束 |
| `EXTENDED_EARLY` | REQ 上升至 REQ 下降 | `REQ=1` 期间 data 始终可解释 |
| `BROAD` | REQ 上升至 ACK 下降 | 整轮 return-to-zero 都保留 data |

observer 比较的是 canonical event identity，即 kind、key 和 payload。它能发现稳定窗口内的数据覆盖或 token
替换。模拟离散 snapshot 无法证明 data 在 REQ 前满足物理 setup、在 capture 后满足 hold，也无法证明
bundled-data datapath 相对同步后的 REQ 具备足够裕量；这些条件需要 CDC/STA 约束、结构检查或更具体的
physical observation profile。

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
   原有的 InterfaceProtocol/operation，不需要出现“FourPhaseDut”类型。
2. **独立 token interface。** `build_four_phase_token_interface()` 提供 `sender`、`receiver` 两个 role 和一个
   `TRANSFER` channel。它可以直接放在两个 `InterfacePort` 上；可选 `data_width` 决定是否携带 bundled data。

`FourPhaseSignals.event` 由上游 trace importer 或 driver 按目标 `EventSchema` 组装；control-only token 也会携带
一个无 payload 的 `CanonicalEvent`，其 key 作为模型侧 occurrence label。observer 不从裸 REQ 电平猜测业务
含义，也不把 observation sequence 伪装成物理 timestamp。

只验证一段 interface/observation trace 时无需 VirtualDut attachment。需要模块真正消费 token 时，integration attachment
再根据用途将 `TRANSFER` 解码成 `Notification`、`StreamTransfer` 或某个专用 operation。映射依赖用户语义，
因此当前没有建立一个会把所有 token 强行解释成同一种 VirtualDut 行为的通用 attachment。

## 5. 与 CDC 和 SystemProtocol 的边界

四相信号次序可以跨越两个独立 clock domain，但逻辑握手通过不等于 CDC 实现已经闭合。一个常见实现会：

- 在接收域同步单比特 REQ，在发送域同步单比特 ACK；
- 源端寄存并保持 bundled data，接收端在看到同步后的 REQ 后整体 capture；
- 对异步 reset 的 deassert 分别做域内同步；
- 将中途或单边 reset 作为 abort/recovery，而不是普通四相 edge。

`FourPhaseObserver` 当前检查 edge-complete 逻辑 snapshots 和协调 reset epoch。它没有判断两级同步器结构、首级
扇出、亚稳态概率、多位 data 的逐位偏斜或独立 reset 恢复。SystemProtocol 后续应闭合：

- 两端 `clock_domain`、`reset_domain` 的声明；
- 跨域连接引用了允许的 CDC module/contract；
- reset abort、epoch 或 replay policy；
- 多条异步连接形成网络后产生的 wait-for 与 progress 关系。

当前 `InterfacePort` 已保存 clock/reset domain 名称，system elaboration 尚未执行上述 CDC closure，因此这些名称
仍是待解析声明。

这里的“异步”表示接口两侧不依赖同一个采样 clock。`FourPhaseObserver` 消费调用方已经提供的有序 samples；
它没有启动 VirtualDut backend 的自主调度，也没有建立 deadline、timer 或跨域全局时间。此前暂缓的
asynchronous DUT emission 仍是 system/runtime 的另一项工作。

## 6. 当前实现

- `protocol_model/protocols/asynchronous/four_phase/`：独立 token InterfaceProtocol；
- `protocol_model/observation/asynchronous.py`：无共享 clock 声明的有序 snapshot；
- `protocol_model/observation/four_phase.py`：四相 FSM、三种 data window、协调 reset；
- `tests/test_async_four_phase.py`：完整周期、停顿、非法 ACK、payload 稳定、reset abort 和跨域端口声明。

下一步适合在出现实际场景时增加 two-phase toggle profile、具体 notification/stream attachment，以及
SystemProtocol 的 clock/reset-domain closure。同步器的物理正确性继续交由 CDC lint、STA 或针对性 formal
harness 检查，Protocol Model 负责保存其抽象合同与端到端语义证据。

## 7. 参考

- [Jens Sparsø, *Introduction to Asynchronous Circuit Design*](https://orbit.dtu.dk/en/publications/introduction-to-asynchronous-circuit-design/)
- [Ivan Sutherland, *Micropipelines*](https://doi.org/10.1145/63526.63532)
- [Furber and Day, *Four-Phase Micropipeline Latch Control Circuits*](https://apt.cs.manchester.ac.uk/ftp/pub/apt/papers/4phCtl.pdf)
