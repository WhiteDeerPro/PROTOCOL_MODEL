# Four-phase asynchronous handshake showcase

本例展示两类彼此相关、但不能混为一谈的证据：

1. `FourPhaseObserver` 实际执行合法四相传输、ACK 抢跑和等待期间 payload 覆盖三个场景；
2. 有限异步 FIFO 面对高差频与近同频 `1 GHz + 1 Hz` 时的容量/速率直觉。

从任意工作目录运行：

```bash
.venv/bin/python showcase/demos/link/four_phase_handshake/run.py
```

脚本原子替换自己拥有的
`showcase/generated/link/four-phase-handshake/`，并保存 WaveJSON、DOT、运行结果、
provenance 和 manifest。使用 `--publish-root <directory>` 可发布到 scratch 目录。

四相波形的横轴是 edge-complete observation order，不是共享 clock cycle。频差图中的 FIFO
轨迹是显式标注的理想化 capacity/admission 投影，不冒充 Gray pointer synchronizer、RTL、VCD、
MTBF 或 STA 结果。近同频案例采用解析计算，因为 `1 Hz` beat period 在 `1 GHz` 下展开一轮
需要约十亿个周期。
