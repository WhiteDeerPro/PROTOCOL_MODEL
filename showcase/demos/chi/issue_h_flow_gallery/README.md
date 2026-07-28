# CHI Issue H flow gallery

本目录保存 5 个确定性、可执行的 CHI flow 场景。它们从生产 participant、
resolved authority/capability/transport runtime 取得消息与状态证据，再通过
`protocol_model.protocols.amba.chi.issue_h.observation` 投影到协议无关的
`TransactionTimeSpaceView`。

## 场景

| case | 观察重点 | 执行边界 |
|---|---|---|
| `clean-read-unique-fanout` | 两路 `SnpUnique` fan-out、response join、`CompData/CompAck` | resolved XP-star topology |
| `dirty-peer-clean-unique` | `SnpCleanInvalid`、dirty DAT 回收、Home backing 更新 | resolved XP-star topology |
| `make-unique-local-intent` | dataless permission lifecycle 与 RN-local full-line intent | resolved XP-star topology |
| `clean-evict-retry` | `RetryAck → PCrdGrant → credited reissue → Comp_I` | resolved XP-star topology |
| `writeback-snoop-cancel` | 冻结 `WriteBackFull` XP capture、同址失效 Snoop、零字节取消 DAT | resolved XP star + selected scheduler moves |

前三案在 `coherence_cases.py`，progress/干涉两案在 `progress_cases.py`。
`model.py` 只组合执行结果与 typed view；`presentation.py` 只生成阅读说明；
`run.py` 是拥有发布子树的唯一入口。

## 重建

```bash
npm ci
.venv/bin/python showcase/demos/chi/issue_h_flow_gallery/run.py
```

输出位于
[`showcase/generated/chi/issue-h-flow-gallery`](../../../generated/chi/issue-h-flow-gallery/README.md)。
每案保存 resolved topology、时空图、显式因果图、语义事件时间线，以及对应
JSON/DOT/WaveJSON 源。五案都在 `SystemProtocol` 中构造一个 `xp0` forwarding
VirtualDut；每个 endpoint packet 实际经过 participant→XP 与 XP→participant 两段
transport route。拓扑投影把该 binding 显示为
`routing forwarder (XP abstraction)`。

WriteBackFull 案需要确定的同址干涉顺序：场景先把 WBF REQ 放到 RN→XP link，
再通过公开的具名 scheduler candidate 暂停该 REQ 的 router capture；其余 REQ、
SNP、RSP 和 DAT channel 继续运行，CleanUnique 退休后再释放 WBF。这个选择控制
模型提交顺序，不引入周期、物理时延或 XP 微架构声明。

flow 时空图过滤不改变 coherence state 的逐 hop transport `MOVE` 事件，只保留
endpoint acceptance 与所选状态提交。原 `model_step` 标签可能出现间隔，但该间隔
不是周期、物理时延或可比较的 XP latency。独立 ring/star 与 4×4 mesh witness
继续用于更长 route 和更大结构的观察，不扩大本 gallery 的 opcode 覆盖。

这些例子是选定 lifecycle 的 executable witness，不是完整 CHI opcode catalog、
规范条款覆盖、CDC/deadlock 证明或芯片实现。
