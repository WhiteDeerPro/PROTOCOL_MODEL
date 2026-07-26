# 术语卡片

[返回全书路线](README.md) · [工程 canonical 术语注册表](../docs/architecture/terminology.md)

这里收录正文已经使用的教学卡片，任务是帮助读者建立直觉、场景和边界。工程符号的当前 canonical 定义
由上方注册表负责；两者不一致时先审议 canonical 定义，再同步本页。随着章节增加，新词汇会在正文中完成
首次讲解后进入本页。

## CanonicalEvent：协议可见的通信事实

- **场景**：APB 的 SETUP 和 ACCESS 信号经过采样后，需要形成一条可交给协议 monitor 的记录。
- **直觉**：它用统一形状表达一件候选或已经提交的协议动作。
- **定义**：`CanonicalEvent` 带有 event kind、correlation key、typed payload 和可选 trace index；session
  接受并编号后才成为该次运行 trace 中的 committed event。
- **所有者**：event 本身是不可变值，`InterfaceSession` 和 `SystemSession` 保存接受后的 trace。
- **生命周期**：observation 产生 event，session 接受并编号，monitor 更新状态，artifact 保存证据。
- **边界**：持续若干周期的信号电平先由 observation 解释，event 表示解释后的离散动作。

## AtomicFrame：一次共同解释的采样边界

- **场景**：ready 与 valid 在同一采样点共同决定一次 transfer；reset 也可能在该边界改变解释规则。
- **直觉**：同一个 frame 内的 observation 会一起进入 lowering。
- **定义**：`AtomicFrame` 是 pin/cycle adapter 的原子输入集合。它保存一次观察边界中的各项采样，直到本次
  lowering 完成。
- **所有者**：调用 observation adapter 的一侧创建 frame；adapter 读取它并产生 0..N 个 event。
- **生命周期**：采样时创建，完成 lowering 后即可释放。事务 obligation 可以跨越多个 frame。

## InterfaceProtocol：完整接口合同

- **场景**：两个端点需要确认线上可以交换哪些消息、由哪一侧发送，以及请求怎样得到 completion。
- **直觉**：它给一条逻辑连接规定词汇和语法。
- **定义**：`InterfaceProtocol` 组合 role、`InterfaceEventKind`、event schema、monitor、parameter 和 semantic
  fragment。`InterfaceEventKind` 只声明事件方向，不保证标准中存在一条同名 wire channel。
- **所有者**：协议声明是不可变对象；每条具体 `InterfaceConnection` 使用独立的
  `InterfaceSessionState`。
- **例子**：AXI4 的 AR、R、AW、W、B 是五个 channel，它们共享 correlation、ordering 和资源关系。

## VirtualDut：系统图中的具体虚拟 module

- **场景**：一笔合法请求到达寄存器块、memory、bridge 或 crossbar 后，模块需要决定接下来的动作。
- **直觉**：它是可以放进系统拓扑中的一个具名模块，行为由软件模型或外部 backend 提供。
- **定义**：`VirtualDut` 声明 port、binding、backend 和边界语义；运行状态保存在对应 backend state 中。
- **所有者**：`SystemSessionState.dut_states` 为每个 module 保存一份 backend snapshot。
- **边界**：协议 attachment 处理单端口接口语义；跨端口 route、completion owner 和调度由模块 backend 处理。

## Attachment：端口上的协议翻译器

- **场景**：APB `READ` 进入地址空间前，需要变成后端可以理解的 `AddressRead`。
- **直觉**：它连接线上语言与模块 operation。
- **定义**：attachment 在 `CanonicalEvent` 与 typed operation/completion 之间转换，并保存该端口需要的
  partial transaction state，例如 AXI AW/W 汇合。
- **所有者**：binding 是静态装配关系，attachment state 进入所属 VirtualDut 的 backend snapshot。
- **边界**：涉及多个端口的转译政策和 completion owner 由 bridge backend 或 translation executor 保存。

## TranslationStage：带类型和合同的变换步骤

- **场景**：一笔 AXI burst 需要展开为多笔较窄的地址访问，再把多个结果折回一个 parent completion。
- **直觉**：stage 描述一种可检查、可组合的事务变换。
- **定义**：`TranslationStage` 声明 source/target operation signature、cardinality、capability projection、semantic
  effect，以及 request lowering 和 completion lift/fold。
- **所有者**：stage 实例保持无运行状态；`TranslationFrame`、`FanoutLedger` 和 executor state 保存执行上下文。
- **边界**：stage 本身描述静态转换合同；运行中的 parent/child 状态由 ledger 与 executor 保存。

## Capacity lease、Protocol Credit 与 Link Credit

这两个词都与“还能接收多少工作”有关，计量对象和状态所有者不同：

| 名称 | 计量对象 | 状态所有者 | 释放或归还条件 |
|---|---|---|---|
| capacity lease | backend 内部的一份有限资源，例如 parent slot 或 owner entry | VirtualDut backend / executor | 本地生命周期完成并 release |
| CHI Protocol Credit | completer 对一次 retry request 的协议资源接纳保证 | Requester transaction ledger 与 Home participant | 重发消耗，或由协议规定的 return/cancel 路径处理 |
| CHI Link Credit | 相邻 receiver 接纳一个 flit 的运输许可 | transport-hop session | flit 接纳后补回，或停链时返回未用 credit |

系统级 wait-for 分析可以读取二者的 typed projection，同时保留各自的权威状态。

## SystemProtocol：多模块通信合同

- **场景**：多个 endpoint、bridge 和 link 连接后，需要检查端口唯一占用、route 可达性和端到端返回关系。
- **直觉**：它描述整个通信系统的组成和集体规则。
- **定义**：`SystemProtocol` 包含 VirtualDut、InterfaceConnection/DirectedTransportConnection、boundary 和
  system semantics；elaboration 在运行前
  解析引用与所有权。
- **所有者**：静态 topology 位于 `SystemProtocol`；每个 link 和 DUT 的运行状态仍由各自 session/backend 保存。
- **待补能力**：coherence ledger、全局 wait-for 等跨节点验证状态需要 system monitor 运行接口。
