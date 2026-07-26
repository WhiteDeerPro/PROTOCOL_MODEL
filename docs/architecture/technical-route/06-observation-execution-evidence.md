# 观察、执行与证据：一次验证如何从输入变成结论

[返回架构地图](README.md) · [SystemProtocol](05-system-protocol.md) · [术语表](../terminology.md)

当前 runtime 有两条入口。它们共享 CanonicalEvent 和协议语义，但尚未由一个统一 boundary runtime 自动
连接：

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
流量，不是 raw RTL pin、VALID/READY 周期或 VCD。

Observation 表示读取已有信号或 trace，不等于模型在驱动 DUT。

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

“Atomic”表示这些观察不会在 lowering 前被随意拆散，不表示整个事务、整个系统或多个 clock domain 在
同一时刻原子发生。tick 也是本地采样编号，不是默认全系统时间。

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
表达同一采样沿的可见性，不表示五个 channel 天然可交换。

现有说明见 [Observation 层](../observation-layer.md)。

<a id="interface-session"></a>
## 4. InterfaceSession：接口局部历史判定

InterfaceSession 执行 schema、transaction monitors、causal predecessor 和有界 resource 检查。它保存每条
具体 interface connection 独立的状态，并能给出当前允许生成的 EventOffers。

单 event 的 fault 不提交候选状态；step_batch 的 fault 回滚这一批。它不负责把事件送到另一个模块，那是
SystemSession 的任务。

实现见 [`interface/session.py`](../../../protocol_model/interface/session.py)。

<a id="system-session"></a>
## 5. SystemSession：topology 路由、立即反应与显式推进

SystemSession 路由 canonical events，执行目标 backend，并处理所有立即 PortEmission，直到队列为空。
它记录每次投递属于哪条 connection、source/destination port、event kind 和因果边。

实现了 `ExplicitlyAdvanceableBackend` 的 backend 还可以接收 `DutAdvanceAction`。SystemSession 原子写回该
VirtualDut 的新状态，并把 advance 产生的 PortEmission 送回正常 connection 路由。当前 queued address responder
用它表达“又获得一次服务机会”；advance step 没有预设时间单位，也不会在后台自行发生。

当前边界：

- 没有 autonomous wakeup、定时队列或后台 emission 调度；
- 没有 latency、timeout 或多 clock；
- 两个独立 origin 的“同刻动作”没有统一 system batch；
- `max_internal_steps` 是防止零时间自激的护栏，不是 livelock/deadlock 证明器；
- 后续 fault 不会把整个多跳 cascade 全局回滚。

实现见 [`system/session.py`](../../../protocol_model/system/session.py)。

<a id="verdict"></a>
## 6. PASS、FAIL、INCONCLUSIVE

| 结果 | 含义 |
|---|---|
| `FAIL` | 已观察到明确规则破坏，并有 rule、reason、scope、location |
| `PASS` | 输入处理结束、无 fault，相关 monitor/backend 已 quiescent |
| `INCONCLUSIVE` | 尚未看到违规，但有限 trace 结束时仍有 pending/obligation |

所以 blackhole sink 通常把请求留成 INCONCLUSIVE，而不是立即 FAIL。是否要求环境最终回应，需要 progress
assumption、时间边界或更强的 scenario property。

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

- 图是语义结果的投影，不参与协议判定；
- deterministic executor 或 scenario 生成的是一条 execution witness。外部 RTL conformance 通常应先由
  observer 检查 pin-local 规则，再按 identity、operation/effect 和必要偏序比较；它不默认要求 raw cycle
  与该 witness 相等；
- 尽量同时保存可检查的图源和 SVG，不让证据只剩图片；
- manifest 是一次运行的目录和元数据索引；当前不使用内容哈希；
- 原子写入用于避免半写文件，不等于防篡改；
- 测试和普通运行不隐式改写发布树；长期示例由具名脚本显式发布。

实现见 [`artifacts/`](../../../protocol_model/artifacts/) 与
[`visualization/`](../../../protocol_model/visualization/)。

## 8. 证据覆盖范围

证据层从语义对象做只读 projection；图形覆盖范围和发布规则统一由
[运行产物管理](../run-output-management.md)维护，未实现的分析见[实现状态](../implementation-status.md)。新增
wait-for、resource occupancy 或 address reachability 视图时，应先定义对应语义对象，再增加 renderer，
不让运行时迁就显示格式。

当前尚未把外部 observation 与 bridge contract 接成通用 stutter-insensitive/partial-order checker。
`INTERFACE_TRANSACTION_ORDER` 和 `PIN_CYCLE` 仍是声明边界，不是已经生成的证明证据。详细边界见
[Bridge 与类型化事务转译](../typed-transaction-translation.md#63-contractexecution-profilewitness-与-rtl-conformance)。

下一步阅读：[端到端 APB 示例](07-apb-read-walkthrough.md) 或 [实施路线](08-roadmap.md)。
