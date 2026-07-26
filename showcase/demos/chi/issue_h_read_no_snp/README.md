# CHI Issue H：最小 direct-Home read

本例执行一条受限但闭合的 CHI 路径：RN-I 为 `ReadNoSnp` 分配 outstanding，request 经正向 REQ link
到达 direct Home；Home 显式 service 后生成单个 `CompData`，再经反向 DAT link 返回 RN-I 并释放
outstanding。

运行：

```bash
.venv/bin/python showcase/demos/chi/issue_h_read_no_snp/run.py
```

正式产物写入 `showcase/generated/chi/issue-h-read-no-snp/`。脚本实际执行 interface ledger、Home
participant 和两条有限 transport path，再根据执行结果生成事件级时空图、`result.json`、DOT 源、
provenance 与 manifest。

本例不生成 raw waveform。当前 REQ 与 DAT 是两条独立的参考 transport session，还没有统一的 pin/cycle
lowering；事件图按 `event_index` 表达因果顺序，避免把参考调度中的空拍误写成 RTL 时序要求。

当前 profile 固定 `Order=00`、`ExpCompAck=0` 和接受初始请求，且一次读取必须落在一个 DAT payload
chunk 内。它不是完整 RN-I/HN、bit codec、Retry/P-Credit、RSP/SNP、路由网络或缓存一致性实现。
