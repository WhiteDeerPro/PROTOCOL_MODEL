# SystemProtocol 组网架构

组网不引入一个与 `SystemProtocol` 竞争的新顶层对象。这里的 network 是 SystemProtocol 内部的 topology
及其派生关系；同一份 topology 可以渲染成星形、树形或传统的“长总线挂设备”视图。

## 1. 网络由什么组成

```text
VirtualDut instances
  具体、具名的 module；每个边界端口声明 LinkProtocol 和 role

ProtocolLink instances
  一份 LinkProtocol 的具体使用；把协议角色绑定到具体端口

System boundary
  尚未在本层连接、需要暴露给更外层系统的端口

System semantics
  只有观察多个 link/module 才能判断的规则
```

一个 AXI/APB/AHB “总线”如果有 decoder、arbiter 或 response mux，这些功能不会隐含在一条抽象长线上：
它们被建成 bridge/fabric VirtualDut。每一段实际通信仍是具体 ProtocolLink。

```text
manager ─ link 0 ─ [decoder/fabric VirtualDut] ─ link 1 ─ register bank
                                      └──────── link 2 ─ memory
```

传统 bus-strip 只是这张星形 topology 的一种可视化投影。

## 2. 五个构建阶段

### 阶段 A：声明单模块边界

先独立构造 VirtualDut：确定端口、LinkProtocol、role、attachment binding、backend 和对外 capability。
这一阶段不需要知道模块将来连接到谁。

单模块能够长期稳定的关键，是 network 只消费它的边界投影，不反射 backend 私有状态。以后增加网络
route 或 wait-for 分析时，模块内部 AddressSpace、FIFO 实现或外部 RTL 代理不需要随之重写。

### 阶段 B：声明连接意图

近期适合增加 `SystemProtocolBuilder` 作为装配入口：

```text
add_dut(vdut)
connect(link_name, protocol, role -> port reference)
expose(boundary_name, port reference)
add_semantics(fragment)
build() -> SystemProtocol
```

Builder 默认只建立严格直连。调用方显式提供事务转译 plan，或授权一组可接受的 conversion/scheduling/
storage policy 时，Builder 的 construction lowering 可以编译 plan，并展开一个 bridge VirtualDut 与两条 ProtocolLink；
生成节点仍进入最终 topology，不成为 runtime 中不可见的 adapter，也不改变 `SystemProtocol` 作为 lowered
语义对象的定位。预先装配好的具名 recipe 仍可作为便捷入口，但不作为协议对 N² 扩张的核心机制。

### 阶段 C：elaboration

elaboration 将逐步分成几类可解释检查：

1. **结构闭合**：名称、端口引用、唯一占用、role 和 protocol 一致；当前已实现；
2. **transport compatibility**：event/channel/参数形状是否可以直接连接；当前要求相等协议声明；
3. **capability closure**：宽度、burst、ID、ordering、byte enable、clock/reset 能力是否匹配；待实现；
4. **address closure**：地址 claim、route window、重映射和目标可达性；待实现；
5. **construction provenance closure**：若 Builder 已展开 bridge，验证生成节点、links 与选择依据完整；
   core elaboration 不自行搜索或插入 translation stage；待实现。

### 阶段 D：运行

当前 `SystemSession` 已经可以：

- 为每条 ProtocolLink 建立独立 LinkSession；
- 根据 channel direction 找到目标端口；
- 执行目标 VirtualDut backend；
- 传播立即 emission，直到队列为空；
- 记录逐跳事件和因果边。

它目前适合同步、立即反应的点到点和微型网络。deferred/autonomous emission、latency、多时钟和整个多跳
cascade 的事务回滚尚未纳入统一 runtime。

### 阶段 E：网络分析

当 capability、资源和 blocked reason 都有稳定投影后，再增加：

- address reachability；
- request owner / completion return；
- buffer、credit、outstanding occupancy；
- wait-for graph 与 deadlock witness；
- boundary hide 后的行为 refinement。

这些是 SystemProtocol 的派生分析，不应要求 LinkProtocol 或单个 VirtualDut 预先知道完整网络。

## 3. integration 在组网中的位置

Attachment 只服务一个端口：把该 link 的 canonical event 转成 backend operation，再把结果编码回来。
Integration 是协议与 VirtualDut 的依赖汇合区；其中 recipe 可以组合多个 attachment 与跨端口 backend。
SystemProtocol 连接 `ProtocolPort`，不会识别 `ApbCompleterAttachment`、AXI AW/W join state 等私有类型。

桥接时会同时出现三类工作：

- 每个端口的协议 codec、wire fragment join 和运输 context，属于两侧 attachment；
- operation 的 burst fanout、地址/属性变换和 completion fold，属于 typed stage/plan；
- parent queue、serialize、lease、lineage、ID remap 和 owner return，属于 bridge executor/backend。

后两类行为需要同时观察两个端口。把它们塞进任一 attachment，会让两侧各自只看到半个 bridge，无法拥有
统一的资源和完成关系。

## 4. 单入口星形网络示例

一个最小、可解释的星形地址网络如下：

```text
injected manager
      │ APB
      ▼
single-ingress AddressFabric
      ├─ APB → RegisterRegion
      └─ APB → MemoryRegion
```

这个示例分离验证 topology、地址解码、owner return、decode error 和可视化，不要求同时解决异构 bridge。
AHB 与 AXI4-Lite 已能复用同一 fabric backend；AXI4 burst endpoint 使用协议相关 backend。
AXI4-Lite→APB 首个 bridge 已验证异构 attachment、route、owner return 与错误映射。full AXI4→APB
进一步加入有界父事务队列、AW/W join 后的 burst split、严格串行 APB 调度和 AXI completion 聚合。
当前容量满以 VirtualDut fault 表示；READY/backpressure、narrow/width conversion 和 wait-for 投影仍需在
后续边界/runtime 中闭合。

Crossbar 可以复用 bridge path 的 codec/stage，但共享出口需要共同的 admission、仲裁租约和
response owner 关系。若每条路径由一个 source 独占，独立 path 组合就足够；若 N 个入口会复用同一出口，
这些共享关系不能由彼此不知道对方的 bridge 实例分别维护。AXI4-Lite 与 AHB SINGLE 的 N→M profile
主要增加 route/arbitration/owner；full AXI 还需要 AW/W 路径关联、ID namespace/remap 与同 ID response
ordering，因此需要更强的协议相关 fabric profile。

## 5. 返回路径与层级边界

“同一路返回”只有在这条路仍能唯一确定原 source 时才足以消除返回表。多个入口共享一个 AXI egress 时，
从该 egress 的 B/R channel 返回只能确定下游出口，不能单独确定最初使用哪个 ingress。

常见实现可以按 source identity 的保留方式归纳：

| 方法 | 保存的关系 | 适用边界 |
|---|---|---|
| 独占返回路径 | path 本身就是 source identity | 每条路径只有一个 owner，或一个 virtual channel 只服务一个 source |
| 单活动 owner | egress → ingress | 无 ID、每个出口一笔活动事务；APB、简单 AHB/crossbar profile |
| AXI ID 前缀 | downstream ID = ingress index + original ID | 下游允许扩展 ID，返回时可直接拆出 ingress |
| ID remap table | downstream tag → ingress、原 ID、顺序 context | 下游 ID 宽度固定、允许多 outstanding |
| 串行化 | 每个 egress 或 egress+ID 同时只有一个 owner | 状态较小，但并发与 head-of-line 行为更受限 |

AXI 的 request/response 本来跨 channel：AR 对应 R，AW/W 对应 B。W 没有 WID，因此即使 B/R 使用 ID
前缀，仍需要 AW→W route FIFO 或等价的 burst-owner 状态。AHB/APB 没有 AXI 式 transaction ID，通常在
地址/setup 被接受时锁存 owner，并在 data/access 完成后释放；burst、lock 或 wait-state 会延长这份租约。

作用域按观察范围区分：

- `LinkProtocol` 检查一条 link 内的 AR→R、AW/W→B、AHB phase/burst 等关系；
- crossbar `VirtualDut` 决定本模块收到下游 completion 后从哪个 ingress port 发出，并维护本地 owner/ID；
- `SystemProtocol` 检查经过多个节点后是否回到原发起者、地址路径是否闭合，以及多个节点资源形成的
  wait-for/deadlock。

因此，多端口不会自动把 crossbar 变成 `SystemProtocol`。隐藏内部实现时它仍是一个 VirtualDut 节点；
只有当 decoder、arbiter、request/return network 被展开为独立 module/link 以供观察时，这些内部对象才组成
一个可再封装的子 SystemProtocol。

当前 `ProtocolLink` 把一个 protocol role 的全部 channel 绑定到一个端口。普通 crossbar 在上下游分别终止
一条 point-to-point link，再由 backend 跨 link correlation；它不把一条 AXI link 的 AR 放在 link A、R 放在
link B。若未来要显式建模 request/response 独立 NoC，应该在 SystemProtocol 中使用不同 link/network 并增加
端到端 transaction correlation，而不是让一个 LinkSession 的 obligation 跨未知 link 隐式闭合。

## 6. Construction lowering：把连接意图展开成显式网络

目标便捷组网 API 可以接受“连接这两个端口，并允许某类事务转译”的意图。V1/T8 后，这个意图由
`SystemProtocolBuilder` 的 construction lowering 处理：

```text
connection intent + endpoint ports + injected translation catalog
                         │
                         ▼
            compile an immutable TranslationPlan
                         │
                         ▼
          bridge VirtualDut + two ProtocolLinks
                         │
                         ▼
              ordinary SystemProtocol
                         │
                         ▼
                 core elaboration
```

Construction lowering 是声明展开，不是 runtime adapter。它与 core elaboration 的边界是：

| 阶段 | 责任 |
|---|---|
| Builder lowering | 在调用方授权范围内选择 codec/stage/policy，生成 bridge 和 links，记录 provenance |
| core elaboration | 检查已经展开的名称、引用、role、port ownership、protocol 和 namespace 闭合 |
| `SystemSession` | 运行固定 topology，不因协议不匹配而修改网络 |

默认连接策略仍是 direct。只有调用方显式授权 transaction translation 才查询 catalog；没有计划时报告
form/capability mismatch，多个计划同时成立时要求消除歧义。属性损失、burst split、错误映射、调度和容量
必须由 policy 闭合。

当前工程可以用显式 route/profile 装配已有 bridge recipe，但 typed address claim、capability projection、
通用 plan/executor 和 `SystemProtocolBuilder` 尚未全部实现。因此近期先完成
[Bridge 与类型化事务转译](typed-transaction-translation.md) 的 V1，再把 plan compilation 接入 Builder。

## 7. 与 Bridge 实施计划的分工

本页只规定网络构造阶段和生成对象的可见性。Operation form、stage、completion fold、resource lease、
AXI/AHB/APB 组合以及具体源码迁移由以下文档负责：

- [Bridge 与类型化事务转译](typed-transaction-translation.md)：稳定概念、设计理由和层级边界；
- [事务转译 V1 实施计划](translation-v1-plan.md)：当前代码起点、实施顺序和验收条件；
- [当前迁移状态](migration-status.md)：已经进入主线的能力。
