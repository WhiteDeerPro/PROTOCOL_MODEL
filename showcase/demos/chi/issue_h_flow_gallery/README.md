# CHI Issue H flow gallery

本目录保存 5 个确定性、可执行的 CHI flow 场景。它们从生产 participant、
resolved authority/capability/transport runtime 取得消息与状态证据，再通过
`protocol_model.protocols.amba.chi.issue_h.observation` 投影到协议无关的
`TransactionTimeSpaceView`。

## 场景

| case | 观察重点 | 执行边界 |
|---|---|---|
| `clean-read-unique-fanout` | 两路 `SnpUnique` fan-out、response join、`CompData/CompAck` | resolved direct topology |
| `dirty-peer-clean-unique` | `SnpCleanInvalid`、dirty DAT 回收、Home backing 更新 | resolved direct topology |
| `make-unique-local-intent` | dataless permission lifecycle 与 RN-local full-line intent | resolved direct topology |
| `clean-evict-retry` | `RetryAck → PCrdGrant → credited reissue → Comp_I` | resolved direct topology |
| `writeback-snoop-cancel` | 延迟 `WriteBackFull`、同址失效 Snoop、零字节取消 DAT | scenario-controlled participant ordering |

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
每案保存拓扑/participant boundary、时空图、显式因果图、语义事件时间线，
以及对应 JSON/DOT/WaveJSON 源。前四案的拓扑边来自 resolved
`SystemProtocol`；WriteBackFull 案只有 participant-level 执行，因此以虚线
记录实际 packet 交互并明确不声称 transport hop。timeline 使用离散
`model_step`，不是 pin/cycle/RTL 波形。

当前四个 resolved flow 都是 direct participant topology，没有构造 XP/router，
所以图中不会补画不存在的路由节点。投影器会把实际
`forwarding_bindings` 显示为 `routing forwarder (XP abstraction)`；独立的
ring/star 与 4×4 mesh witness 则确实构造并执行了这种节点。

flow 时空图过滤不改变 coherence state 的逐 hop transport `MOVE` 事件，只保留
endpoint acceptance 与所选状态提交。原 `model_step` 标签可能出现间隔，但该间隔
不是周期、物理时延或可比较的 XP latency。

这些例子是选定 lifecycle 的 executable witness，不是完整 CHI opcode catalog、
规范条款覆盖、CDC/deadlock 证明或芯片实现。
