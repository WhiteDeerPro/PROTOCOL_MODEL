# 实施路线与阶段边界

[返回架构地图](README.md) · [查看总览图](overview.svg) · [项目 Roadmap](../../../ROADMAP.md)

这条路线按“下一层真实需要什么”递归补基础能力，而不是按协议名称或软件包数量推进。

## 当前已经打通的一条小型完整路径

```text
基础语义
  → 通用 pattern
  → AXI/APB/AHB LinkProtocol
  → ProtocolAttachment + binding
  → AddressSpace / AddressFabric VirtualDut
  → point-to-point / bridge SystemProtocol
  → 同步执行、trace、causality、artifact
```

它已经能回答：单 link 上发生的事务是否合法；一个 APB endpoint 如何执行地址访问；一个简单 fabric
如何解码、转发并归还 completion；多个具体模块如何组成可执行系统。

## 依赖驱动的推进顺序

当前瓶颈不是可声明的协议名称数量，而是跨协议组合时两端能力是否匹配、burst 如何拆分、资源何时释放、
等待是否形成闭环。继续增加协议容易复制协议专用 adapter/backend，却不给这些共同问题提供构造能力。

因此下一阶段按以下顺序推进。

### S1 · 已具备的局部 attachment baseline

APB、AHB、AXI4-Lite 和 AXI4 normal-access integration 已打通首个同步请求—处理—响应路径；AXI4-Stream 也已有独立
StreamTransfer contract：

- AHB 已保存 address/data phase context，并完成 narrow bus-lane mapping；后续边界是 Exclusive Access Monitor；
- AXI4-Lite 已处理 AW/W FIFO join；
- AXI4 subordinate 已展开 burst 并聚合 response，generic manager 当前是 serialized single-beat；
- AXI4-Stream 已能 capture，width conversion 与 autonomous source 后续处理。

这里列出的 Exclusive、width conversion 和 autonomous source 是各 profile 的后续扩展，不阻塞 typed bridge
T1–T6。当前 baseline 的成立依据是 attachment 的运输状态、quiescent 条件、错误映射和 backend binding
已经可被执行和检查。

### S2 · 类型化 bridge 与容量资源

AXI4-Lite→APB 与 full AXI4→APB 已提供实际抽取压力。typed stage、fanout ledger、capacity lease 和
operation-level serial executor 已实现；下一步用显式 route/profile 补 attachment transaction 外壳和
`AddressBurst` stages，再接入第一个协议对。这一步不以自动 capability planner 为前置条件。等第二个
egress 证明 plan/executor 可复用后，再进入基于 capability 的 construction-time 自动选择。

稳定架构见[Bridge 与类型化事务转译](../typed-transaction-translation.md)，具体阶段与验收只在
[V1 实施计划](../translation-implementation.md)维护。

### S3 · capability、address projection 与自动构造

VirtualDut 将对系统可见但不泄漏内部实现的事实投影出来：

- 支持的 transfer size、byte enable、burst、ID、ordering；
- address claim 和 route window；
- externally visible capacity。

Builder construction lowering 与 core elaboration 只消费这些边界事实，不反射 backend 的私有
AddressSpace。前者在用户授权后选择 translation plan，后者检查展开后的 topology；未授权时保持 direct
或报告 mismatch，不在 runtime 插入 adapter。

### S4 · Resource-aware runtime extension

V1 的同步边界在入口容量满时仍报告结构化 fault。后续需要补两阶段 admission 或等价契约，使 runtime 能
区分“事件尚未被接纳”和“工作已经接纳但等待资源”，并表示 blocked reason、deferred emission、held lease
与 waiting demand。这个阶段扩展现有 fixed-point runtime，不要求同时引入物理时钟。

### S5 · wait-for 与 deadlock 证据

有了显式 blocked reason、动态资源和非立即 emission 后，SystemProtocol 才能构造 wait-for graph。分析目标
不是简单寻找拓扑环，而是寻找可达、非 quiescent、无 enabled transition、且 obligation 未完成的状态。

输出应包含：等待谁、持有什么资源、哪条 obligation 未关闭、是否存在 escape transition。

### S6 · 自主 emission 与时间窗口

当前同步 fixed-point 适合点到点和微型 bridge。异步扩展需要区分：

- backend 自主 emission 与外部 injection；
- blocked、deferred、scheduled output；
- 本地时钟和跨域不可比时间；
- deadline/time window，而不是强行使用一个全局 cycle。

这一步以后才能严谨表达 timer、CDC、异步 FIFO、长期 fairness 和 timeout。

## 贯穿所有阶段的验证方式

每条小型完整路径只需要与风险相称的证据：

1. 一个合法 witness；
2. 一个只违反目标规则的负例；
3. 可以解释的 state/resource/causal projection；
4. 明确记录仍未覆盖的规范条款和基础能力。

测试是验证架构判断的手段，不以 case 数量代替架构进度。
