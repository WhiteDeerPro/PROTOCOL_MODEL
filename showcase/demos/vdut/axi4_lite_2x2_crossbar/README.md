# AXI4-Lite 2×2 crossbar VirtualDut demo

本例使用公共构造 API 装配一个最小的双入口、双出口 AXI4-Lite 地址网络：

```text
manager0 ─┐                    ┌─ target0 · 0x1000..0x10ff
          ├─ 2×2 crossbar ─────┤
manager1 ─┘                    └─ target1 · 0x2000..0x20ff
```

运行故事让两个 manager 同时读取 `target0`，从而显示每入口 FIFO、共享地址
decode/remap、每出口 round-robin arbiter，以及 completion 返回时使用的 owner table。
`DutAdvanceAction` 表示一次显式 service opportunity，不表示固定的硬件周期。

从任意工作目录运行：

```bash
python3 showcase/demos/vdut/axi4_lite_2x2_crossbar/run.py
```

默认发布到 `showcase/generated/vdut/axi4-lite-2x2-crossbar/`。脚本保留每张
SVG 的 DOT 源、运行结果、provenance 和 manifest，并在完整 staging 成功后原子
替换自己的发布目录。使用 `--publish-root <directory>` 可以生成 scratch 版本。

发布包还包含一张 `model-steps.svg`：横轴每列表示一次完成的模型 action 或
service opportunity，状态 lane 是该步结束后的 crossbar post-state。它不是 ACLK、
VALID/READY 或 RTL pin waveform。

`trace-conformance.svg` 特别说明 reference executor 与 RTL 对比的边界：当前
deterministic schedule 只产生一条 execution witness；协议 observation 可以在检查
stall stability、reset 等 pin-local 规则后折叠无 transfer 的 stutter frame。默认
应比较 operation/effect、correlation 和必要偏序，而不是要求 RTL 每个采样周期与
这条 witness 相同。只有具名 `PIN_CYCLE` contract 才能把相应周期安排纳入 golden
约束；这一 checker 当前尚未实现。
