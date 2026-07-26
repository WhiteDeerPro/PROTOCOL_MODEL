# 容量、接纳与背压

## 1. 定位

有限 FIFO、outstanding table、owner table 和 completion slot 都会把“这次输入是否合法”之外的问题带入
可执行模型：输入本身可能符合协议，但接收 module 此刻没有资源接纳它。为了让场景生成、参考执行和后续
网络分析使用同一种解释，本项目把容量不足表示为显式的接纳结果。

一次动作在容量边界上有三种通用结果：

| 结果 | 输入是否已接纳 | 对外结果 | 后续含义 |
|---|---:|---|---|
| `BLOCK` | 否 | typed `ResourceDemand` | 调用方可在资源变化后重试同一动作 |
| `ERROR_COMPLETION` | 是 | 协议可见的普通错误完成 | 失败也进入该协议的 correlation 和 ordering 生命周期 |
| `FAULT` | 不作为正常事务接纳 | `SemanticFault` | 模型配置、调用方式或构造合同被违反 |

三者不能仅凭“FIFO 已满”互换。选择哪一种结果，取决于被建模 module 的公开合同：一个支持流控的接收端
通常采用 `BLOCK`；一个明确声明“容量不足时接纳请求并返回错误”的设备可以采用
`ERROR_COMPLETION`；调用方超过了模型承诺的使用范围时才适合 `FAULT`。

传感器等持续产生数据的物理源还有第四种局部策略 `DROP_NEWEST`。它表示一次采样机会已经发生，但 FIFO
无法保存新样本，于是保留旧数据、丢弃新数据并更新 overrun 状态。这项策略属于具体 backend，不扩充所有
资源的通用耗尽枚举。

## 2. 术语

### 2.1 容量与占用

`capacity` 是资源可同时持有的条目数，`available` 是当前还可分配的条目数。二者只描述数量；条目何时
获得、由哪个完成释放、是否允许乱序释放，仍由相应 VirtualDut 和协议生命周期决定。

例如 AXI bridge 可以分别拥有：

- 尚未完成 AW/W correlation 的输入状态；
- 已经形成、等待调度的 parent transaction；
- 下游 outstanding transaction；
- 等待返回上游的 B/R completion；
- 用于恢复上游 ID 或入口端口的 owner table。

把这些对象都写成一个笼统的“FIFO depth”，会掩盖真正的阻塞位置，也无法形成有用的 wait-for 证据。

### 2.2 接纳

接纳意味着 module 已经取得该动作的所有权。接纳以后，即使功能结果为错误，module 也需要履行对应的
完成义务，或者执行协议允许的取消/复位流程。

`ERROR_COMPLETION` 因而包含两个事实：请求已经接纳，工作以普通协议错误结束。该错误完成需要按照协议的
相关键和顺序保存，直到响应真正发出并被对端接纳。queued responder 与 scheduled crossbar 为容量溢出
各保留一个有界应急错误槽：marker 排在同入口旧请求之后，推进到队首时才编码响应。普通 immediate endpoint
仍可能在同一个系统步内编码完成；两种实现都需要遵守 completion 生命周期。

### 2.3 背压与阻塞

背压描述接收方暂不接纳输入。事件级执行用 `BLOCK` 和 `ResourceDemand` 表示这一事实：

```text
action + current state
        │
        ├─ resource available ──> accepted state + possible emissions
        │
        └─ resource unavailable -> original state + ResourceDemand
                                      └─ retry after relevant progress
```

`ResourceDemand` 至少指出资源名称和作用域，也可以携带所需数量、可用数量、总容量、位置及解释。它是运行时
证据，同时为以后构造 wait-for graph 提供输入。

当前 `BLOCK` 是 event-level admission 结果，还没有直接生成 AXI `READY`、AHB `HREADY` 或 APB
`PREADY` 波形。这些信号各自还有稳定 payload、通道独立性、transfer phase 和 reset 等周期规则，需要观察/
驱动层做协议专属 lowering。

`SteppedEmissionBackend` 补充了相邻但不同的能力：它把一个 immediate backend 已经算出的 output batch 放入
有限 event FIFO，由调用方显式推进，每次最多释放一个事件。wait policy 可以在首个事件前或相邻事件之间
插入空的 service opportunity。AXI4 AddressSpace endpoint 可选用该 profile，因而一个 R burst 可以逐 beat
释放；只有当 scenario 明确把一次 advance 映射到一个 ACLK 周期时，空 advance 才能投影为候选
`RVALID=0` bubble。它仍不生成 `RREADY`，也不替代 stall 时保持 R payload 的 pin-level driver。
默认 batch scheduler 为 FIFO；可选 round-robin 在不同 ordering key 的 batch 间逐事件轮转，同 key 的后一
batch 必须等待前一 batch 完成。AXI4 recipe 把 `(port, R/B, ID)` 作为 ordering key，因此不同 RID 的 R
可以逐 beat 交织，相同 RID 则保持 AR 接纳顺序。地址不参与该调度键。
调度器同时提供 `prepare_offer()`、`current_offer()` 和 `accept_offer()`：选中的 event 在 accept 前仍
占用 FIFO 且反复查询保持不变。这已经给 `RREADY=0` 时的 payload ownership 留出状态边界；将
offer 降低为 `RVALID/RID/RDATA/RRESP/RLAST` 并在 handshake 后调用 accept，仍属于 AXI pin/cycle driver。

### 2.4 丢弃

`DROP_NEWEST` 适合不能由数字总线暂停的生产者，例如固定采样率 ADC 前端。FIFO 已满时，采样机会仍被
消费，`service_index` 和 `overrun_count` 前进，已有样本保持不变。软件可轮询 overrun 状态，后续也可以由
notification/interrupt attachment 把它投影为事件。

能够真正停止采样的传感器模型也可选 `BLOCK`。此时被拒绝的是本次显式 service action，采样序列不会前进。
场景需要说明这代表时钟门控、外部流控，还是仅供验证使用的理想化环境。

## 3. 运行机制

### 3.1 VirtualDut 局部转移

VirtualDut backend 在 `accept()` 或 `advance()` 中检查本地资源。容量足够时，它更新占用并返回正常
`DutTransition`；容量不足时按所选合同产生下列结果之一：

```text
BLOCK
  state' = state
  emissions = ()
  blocked = ResourceDemand(...)

ERROR_COMPLETION
  state' = state with accepted/ordered-completion lifecycle updates
  emissions = immediate error completion, or () until a deferred marker is served

FAULT
  state' follows fault atomicity of the owning component
  fault = SemanticFault(...)
```

`BLOCK` 不能同时提交 emission。否则一次动作会出现“对一部分接收者已经生效、对调用方却宣称未接纳”的
矛盾。`ERROR_COMPLETION` 已经转移请求所有权，可以立即产生 emission，也可以先保存有序 marker，再由后续
service action 发出。

### 3.2 SystemSession 的整步回滚

一次 `SystemAction` 或 `DutAdvanceAction` 可能沿多条 connection 立即传播，并触发一串 VirtualDut 转移。当前
`SystemSession` 遇到任意 `blocked` 结果时返回调用前的 `SystemSessionState`：

```text
external action
  -> interface event
  -> DUT A emission
  -> interface event
  -> DUT B reports BLOCK

result: the complete external step is unaccepted; state and trace use the
        snapshot from before the action
```

这种整步原子性让重试语义清晰，也避免留下半条因果链。它目前是偏保守的运行时边界。对于一个多 egress
crossbar，如果同一外部步先让出口 A 取得进展，随后出口 B 阻塞，整步回滚会撤销出口 A 的进展。于是两个
本来可以独立推进的出口出现暂时的跨出口耦合。

后续可通过分阶段 admission、预留全部所需资源、每个输出独立提交，或带 transaction identity 的 deferred
调度减小这种耦合。采用哪一种机制，需要先固定并行 emission、取消和可观察原子性的合同；当前实现仍保留
整步回滚。

### 3.3 `ERROR_COMPLETION` 的响应资源

错误响应可以关闭某个已经接纳请求的 obligation，因此常用于避免请求方无限等待。然而它不直接证明系统
无死锁：

- response FIFO 也可能已满；
- 返回路径可能等待 arbiter、credit 或 owner-table entry；
- 上游可能停止接纳错误响应；
- module 可能持有下游资源，同时等待上游释放另一个资源。

如果容量不足策略选择 `ERROR_COMPLETION`，构造者仍需为该 completion 的存储、排序和发送提供资源。将
“生成一个错误码”视为无资源动作，会隐藏 response-path deadlock。无死锁判断还需要等待关系、已持有 lease、
可释放条件和必要的公平性假设。

## 4. 设计理由

### 4.1 保留正常流控与模型错误的区别

队列暂时满通常是可达运行状态。把它统一升级为 `SemanticFault` 会让随机场景把合法拥塞报告成模型失败，
也失去重试和等待分析所需的信息。反过来，把配置不一致或内部不变量破坏包装成协议错误，会使模型缺陷看起来
像 DUT 的普通功能结果。

显式三分法让 verdict 保留来源：

- `BLOCK` 供调度器、driver 和进度分析消费；
- `ERROR_COMPLETION` 供协议 monitor、上游 DUT 和软件行为消费；
- `FAULT` 供模型作者修正构造或实现。

### 4.2 容量策略属于公开行为合同

相同深度的 FIFO 可以有不同外部语义。桥入口 FIFO 满时通常暂停请求；某些寄存器接口可能返回错误；数据
采集前端可能覆盖旧数据或丢弃新数据。容量数字可以作为参数复用，耗尽策略需要由具体 recipe/profile 明确
选择，并在 boundary projection 或展示材料中可见。

### 4.3 为网络级进度分析保存证据

`ResourceDemand` 比一个布尔 `ready=False` 多保留了“在等什么”。当 backend 后续公开 held resource、
outstanding obligation 和 unblock transition 后，SystemProtocol 才能连接如下关系：

```text
transaction/DUT A waits for resource R
resource R is held by transaction/DUT B
DUT B waits for completion/path/resource S
```

只有形成闭环还不足以判定协议死锁；可撤销路径、超时、环境进度和仲裁公平性也要纳入条件。本项目当前尚未
实现 wait-for/deadlock 分析，因此现有 `ResourceDemand` 是必要输入之一，还不是最终 verdict。

### 4.4 AXI 中“停住”的三个作用域

AXI 的停顿需要先按作用域分类。单个 `VALID/READY` 接口上的依赖错误、互连内部的有限资源循环，以及多个
节点形成的网络等待环，需要的证据并不相同。

1. **单接口与跨通道依赖。** 信息发送方不能等待对应 `READY` 才断言 `VALID`；接收方可以等待
   `VALID` 再给出 `READY`。写响应必须等待地址和最后一个写数据传输完成，但不能继续等待 `BREADY`；读
   响应也不能等待 `RREADY` 才出现。这些属于 AXI transport 规则，可在 pin/cycle observation 和
   InterfaceProtocol lifecycle 两侧分别检查。参见
   [Arm AMBA AXI Protocol Specification, Issue L](https://documentation-service.arm.com/static/68b03beb01ae952d9559f9eb)。
2. **单个 interconnect/bridge 的资源依赖。** AW/W route ownership、ID/order table、response slot、burst
   拆分项和 downstream FIFO 可能互相等待。每个外部 interface connection 都可能保持合法，此时问题属于 VirtualDut 的
   admission、持有资源和完成策略。
3. **跨节点网络依赖。** 同一 ID 的事务先后访问不同 target，而多个 source/target 又以不同次序返回时，
   ordering table 可以形成闭环。工程实现常用 “single slave per ID” 限制减少这种环，相关二主二从示例见
   [AMD AXI Interconnect：How Deadlock Occurs](https://docs.amd.com/r/en-US/pg059-axi-interconnect/How-Deadlock-Occurs)
   与
   [Avoiding Deadlock Using Single Slave Per ID](https://docs.amd.com/r/en-US/pg059-axi-interconnect/Avoiding-Deadlock-Using-Single-Slave-Per-ID)。

环形或 mesh 拓扑并不自动意味着死锁；需要检查逻辑资源依赖图。不同物理路径、virtual channel 或独立
request/response class 可以拆开一部分依赖环，但无法修复 NoC 外部 endpoint 的相互等待。AMD 对其 NoC
保证范围也明确排除了外部相互依赖，见
[NoC Deadlock Avoidance](https://docs.amd.com/r/en-US/pg313-network-on-chip/NoC-Deadlock-Avoidance)。

一次有限时长的 `BLOCK` 是背压证据，尚不足以称为死锁。死锁 verdict 还要证明一组参与者各自持有资源、
等待其他成员释放资源，并且在给定环境与公平性假设下没有可逃逸动作。系统仍在服务其他事务、但某一请求长期
得不到仲裁属于 starvation；反复重试却不能完成更接近 livelock。这三种进度问题应分别报告。

## 5. 层级边界

| 层级 | 容量相关职责 | 当前不由该层决定的事项 |
|---|---|---|
| 基础语义 | 声明 `ResourceDemand`、`ResourceExhaustionPolicy` 和 blocked transition 不变量 | 某个协议的错误码及 pin 时序 |
| InterfaceProtocol | 定义响应种类、correlation、ordering、outstanding 合法性 | 某个 VirtualDut 的真实 FIFO 深度和丢弃策略 |
| VirtualDut/backend | 拥有 FIFO/table occupancy，执行 admission、drop、error 或 fault 策略 | 整个网络能否形成等待环 |
| attachment/integration | 把 `AccessStatus` 等操作结果编码为 AXI/AHB/APB completion | 凭空提供 backend 缺失的响应存储资源 |
| System runtime | 传播事件、定位 blocked demand、维护当前整步回滚边界 | 推断 READY/HREADY/PREADY 周期波形 |
| System analysis | 目标上消费 blocked、lease、obligation 和 topology，构造 wait-for/deadlock 证据 | 代替 DUT 决定发送错误或丢弃数据 |
| observation/driver | 将 event admission lowering 为协议 pin/cycle 行为，核对信号稳定和 phase 规则 | 改写上层已经声明的接纳语义 |
| scenario/project | 选择 producer rate、service schedule、重试和公平性假设 | 把环境假设伪装成协议要求 |

一个 AXI requester 是否允许 16 笔 outstanding 属于端口 capability/profile 与实现资源的交界；实际已占用
多少 entry 属于 backend 状态；网络是否保证这些 transaction 最终得到响应属于 system/scenario progress
property。分开记录这三项，能够避免把“模型数组只有八格”误写成 AXI 协议限制。

## 6. Sensor → DMA → Memory 示例

当前最小场景由四个 constructed VirtualDut 组成：

```text
Sensor FIFO --fixed address read--> AXI4-Lite crossbar
                                         |
Serialized DMA --------------------------+
                                         |
                                         +--> queued memory
```

更准确的事务方向是 DMA 通过 crossbar 反复读取 sensor data register，再把每个 sample 写入连续 memory
address。DMA descriptor 使用固定 `source_stride=0` 和递增的 destination stride。一次样本搬运经历：

1. sensor 的显式 service step 依据确定性 sample policy 产生样本；
2. FIFO 有空位时保存样本；满且采用 `DROP_NEWEST` 时增加 `overrun_count`；
3. DMA 对固定 data register 发起 read；非空时 sensor 弹出最旧样本并完成读取；
4. DMA 保存该 beat，随后向 memory 发起 write；
5. memory 完成写入后，DMA 推进 descriptor，继续下一 beat。

该场景可以分别观察三类容量边界：

- sensor 产生速度高于 DMA 搬运速度：`DROP_NEWEST` 保留较早样本，并留下 overrun 证据；
- DMA 在 sensor FIFO 为空时读取：默认 `BLOCK`，也可配置为 address access error；
- crossbar 或 queued memory 的 ingress FIFO 已满：默认 `BLOCK`，动作在资源释放后重试。

对不可背压 sensor 采用 `ERROR_COMPLETION` 不能保存已经丢失的样本。更合适的组合是
`DROP_NEWEST + overrun status`，需要异步通知时再附加 interrupt/notification 路径。该通知路径自身也有
queue、active slot 和 completion/EOI 资源，应使用同一套接纳语义建模。

## 7. 当前实现与限制

当前实现已经覆盖以下最小闭环：

- 基础语义提供 `ResourceExhaustionPolicy` 和带位置/容量信息的 `ResourceDemand`；
- `SemanticStep`、`DutTransition` 和 `SemanticRun` 能区分 blocked 与 fault；
- queued address responder 与 AXI4-Lite address crossbar 支持 `BLOCK`、有序 deferred
  `ERROR_COMPLETION` 和 `FAULT`；错误策略为每个 responder port/crossbar ingress 提供一个应急槽；正常
  FIFO 仍满且该槽已占用时，再次发生 overflow 会返回 `BLOCK`；
- protocol-neutral `SteppedEmissionBackend` 可为 immediate backend 增加有限 output-event FIFO、动态 wait
  policy 和逐 advance 单事件释放；AXI4 Full AddressSpace recipe 已把它公开为可选 response profile；
- `SystemSession` 在传播中遇到 blocked demand 时执行整步回滚，并把 demand 定位到具体 DUT/port；
- sensor FIFO 支持 empty `BLOCK`/access error 以及 full `BLOCK`/`DROP_NEWEST`；
- sensor、serialized DMA、crossbar 和 memory 已能组成 event-level 搬运场景。

当前边界包括：

- event-level admission 尚未 lowering 为 AXI `READY`、AHB `HREADY`、APB `PREADY` 及相应的 pin/cycle
  稳定规则；
- 整步回滚会在多 egress cascade 中产生保守的跨出口耦合；
- blocked transition 目前没有统一的自动唤醒或 scheduler，场景显式安排资源释放和重试；
- stepped output FIFO 已形成一个局部合同；queued work、held lease、自动唤醒和跨步 causal lineage 仍未统一；
- wait-for graph、deadlock witness、livelock 与 fairness 分析尚未实现；
- 当前应急错误槽只覆盖一笔 overflow；更深的 response FIFO、多个 response class 或乱序完成 backend 仍需
  显式声明容量并保存 correlation/order state；
- sensor overrun 已保存在 backend state，寄存器化状态和 interrupt/notification 联动仍由后续 recipe 决定。

近期扩展应先让 capacity、held resource、completion storage 和 unblock condition 形成稳定 boundary
projection，再加入 wait-for 分析。pin/cycle driver 可在同一语义上分别实现 AXI、AHB 和 APB 的背压时序，
无需把周期信号规则放回通用 backend。
