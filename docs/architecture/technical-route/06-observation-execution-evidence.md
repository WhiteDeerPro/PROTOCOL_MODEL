# 观察、执行与证据：一次验证如何从输入变成结论

[返回架构地图](README.md) · [SystemProtocol](05-system-protocol.md) · [术语表](../terminology.md)

当前 runtime 提供两条入口。它们共享 CanonicalEvent 和协议语义；后续统一 boundary runtime 将负责自动
连接两条路径：

```text
外部观察路径
normalized sample → AtomicFrame → protocol observer → InterfaceSession

构造系统路径
scenario/controller → SystemAction → SystemSession → per-connection InterfaceSession → VirtualDut
                                      ↑
                     DutAdvanceAction ┘  （显式服务推进）
```

<a id="external-input"></a>
## 1. 两条输入路径

外部观察路径接收调用方已经归一化的样本。未来 VCD、FSDB、UVM transaction adapter 会负责把工具特有
表示转换成稳定输入；当前这些通用 adapter 尚未完成。

构造系统路径通过 `SystemAction` 显式指定“哪个 VirtualDut 端口发出哪个 canonical event”。这适合测试
点到点链路和微型网络，也解释了为什么 idle source 仍可被测试代码主动注入流量。

`RandomTrafficController` 位于 scenario 层：它按端口 role 过滤当前 `EventOffer`，用调用方提供的 seed/RNG
补全协议合法事件，并持续观察对端事件以保持 InterfaceSession 状态同步。它产生的是可复现的 canonical-event
流量。raw RTL pin、VALID/READY 周期或 VCD 由 observation/driver adapter 负责转换。

Observation 消费已有信号或 trace；driver/generator 承担 DUT 激励。

<a id="atomic-frame"></a>
## 2. AtomicFrame：保住同一采样边界

AtomicFrame 是某个本地 clock tick 上的具名观察信封：

```text
tick = 42
lanes = {
  AW: {...},
  W:  {...},
  R:  {...}
}
```

“Atomic”表示这些观察在 lowering 前保持同一采样边界。事务原子性由协议 monitor 定义，系统级提交由
SystemSession 定义，各 clock domain 保留各自的时间坐标。tick 是本地采样编号。

实现见 [`observation/frame.py`](../../../protocol_model/observation/frame.py)。

<a id="observation"></a>
## 3. Protocol observer：从采样语义降为事件

Observer 负责协议编码知识：

- ready-valid：只有 VALID/READY 接受时产生 transfer；stall 时检查 payload 稳定；
- APB：把 SETUP/ACCESS、wait 和 error 转成 READ/WRITE/response；
- AHB：处理 address/data phase 与两拍 ERROR；
- AXI：按五通道 handshake 形成 AR/R/AW/W/B canonical events。

同一 AXI AtomicFrame 中的事件按协议本地 lowering order `B, R, W, AW, AR` 交给
`InterfaceSession.step_batch()`。Batch 全部接受才提交；某一事件 fault 时回滚整批 interface state。固定顺序用于
表达同一采样沿的可见性；channel 交换性由 AXI monitor 的协议规则决定。

现有说明见 [Observation 层](../observation-layer.md)。

<a id="interface-session"></a>
## 4. InterfaceSession：接口局部历史判定

InterfaceSession 执行 schema、transaction monitors、causal predecessor 和有界 resource 检查。它保存每条
具体 interface connection 独立的状态，并能给出当前允许生成的 EventOffers。

单 event 的 fault 保留原状态；step_batch 的 fault 回滚这一批。SystemSession 负责把已接纳事件送到另一个
module。

实现见 [`interface/session.py`](../../../protocol_model/interface/session.py)。

<a id="system-session"></a>
## 5. SystemSession：topology 路由、立即反应与显式推进

SystemSession 路由 canonical events，执行目标 backend，并处理所有立即 PortEmission，直到队列为空。
它记录每次投递属于哪条 connection、source/destination port、event kind 和因果边。

实现了 `ExplicitlyAdvanceableBackend` 的 backend 还可以接收 `DutAdvanceAction`。SystemSession 原子写回该
VirtualDut 的新状态，并把 advance 产生的 PortEmission 送回正常 connection 路由。当前 queued address responder
用它表达“又获得一次服务机会”；advance step 没有预设时间单位，也不会在后台自行发生。

当前执行合同与后续扩展点：

| 主题 | 当前合同 | 后续 owner |
|---|---|---|
| 推进 | scenario 显式提交 `DutAdvanceAction` | autonomous wakeup 与定时队列进入 scheduler |
| 时间 | advance 表示 service opportunity | latency、timeout 与多 clock 进入 time/domain profile |
| 并发 | 每个 `SystemAction` 独立提交 | 多 origin system batch 需要显式 batch contract |
| 内部步数 | `max_internal_steps` 限制零时间自激 | livelock/deadlock 由 progress analyzer 判定 |
| fault | 多跳 cascade 采用逐 hop 提交 | 全局回滚需要独立 system transaction contract |

实现见 [`system/session.py`](../../../protocol_model/system/session.py)。

<a id="verdict"></a>
## 6. PASS、FAIL、INCONCLUSIVE

| 结果 | 含义 |
|---|---|
| `FAIL` | 已观察到明确规则破坏，并有 rule、reason、scope、location |
| `PASS` | 输入处理结束、无 fault，相关 monitor/backend 已 quiescent |
| `INCONCLUSIVE` | 尚未看到违规，但有限 trace 结束时仍有 pending/obligation |

blackhole sink 接受请求后保留 pending obligation，因此有限运行通常得到 INCONCLUSIVE。progress assumption、
时间边界或更强的 scenario property 可以把“环境最终回应”提升为可判定要求。

<a id="evidence"></a>
## 7. 从运行状态到可阅读证据

```text
events / state / faults / causal edges
        ↓ 只读 projection
DOT / WaveJSON / stable records
        ↓ renderer
SVG / report
        ↓ RunArtifactStore
caller-selected run root / manifest.json
        ↓ 显式 publish
docs/ 或 showcase/generated/
```

- 图是语义结果的只读投影；协议判定在 monitor/backend/runtime 完成；
- deterministic executor 或 scenario 生成一条 execution witness。外部 RTL conformance 先由 observer 检查
  pin-local 规则，再按 identity、operation/effect 和必要偏序比较；raw-cycle 等价需要单独声明
  `PIN_CYCLE` profile；
- 图源与 SVG 一起保存，支持检查和重新渲染；
- manifest 索引一次运行的目录与元数据；内容认证可在后续 hash/signature profile 中加入；
- 原子写入防止半写文件，来源认证由版本控制或签名机制提供；
- 测试和普通运行写入临时或调用方指定目录；具名脚本负责发布长期示例。

实现见 [`artifacts/`](../../../protocol_model/artifacts/) 与
[`visualization/`](../../../protocol_model/visualization/)。

## 8. 证据覆盖范围

证据层从语义对象做只读 projection；图形覆盖范围和发布规则统一由
[运行产物管理](../run-output-management.md)维护，未实现的分析见[实现状态](../implementation-status.md)。新增
wait-for、resource occupancy 或 address reachability 视图时，应先定义对应语义对象，再增加 renderer，
运行时结构继续由语义合同驱动。

通用 stutter-insensitive/partial-order checker 将连接外部 observation 与 bridge contract。当前
`INTERFACE_TRANSACTION_ORDER` 和 `PIN_CYCLE` 定义 comparison profile；实际证明证据需要对应 checker
执行后产生。详细边界见
[Bridge 与类型化事务转译](../typed-transaction-translation.md#63-contractexecution-profilewitness-与-rtl-conformance)。

下一步阅读：[端到端 APB 示例](07-apb-read-walkthrough.md) 或 [实施路线](08-roadmap.md)。
