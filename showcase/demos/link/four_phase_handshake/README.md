# Four-phase asynchronous handshake showcase

本例并列展示两类各有判定范围的证据：

1. `FourPhaseObserver` 实际执行合法四相传输、ACK 抢跑和等待期间 payload 覆盖三个场景；
2. 有限异步 FIFO 面对高差频与近同频 `1 GHz + 1 Hz` 时的容量/速率直觉。

从仓库根目录运行：

```bash
python3 showcase/demos/link/four_phase_handshake/run.py
```

脚本原子替换自己拥有的
`showcase/generated/link/four-phase-handshake/`，并保存 WaveJSON、DOT、运行结果、
provenance 和 manifest。使用 `--publish-root <directory>` 可发布到 scratch 目录。

四相波形的横轴是 edge-complete observation order。频差图中的 FIFO 轨迹是显式标注的理想化
capacity/admission 投影；Gray pointer synchronizer、RTL、VCD、MTBF 和 STA 由 CDC/实现级工具提供。
近同频案例采用解析计算，因为 `1 Hz` beat period 在 `1 GHz` 下展开一轮需要约十亿个周期。
