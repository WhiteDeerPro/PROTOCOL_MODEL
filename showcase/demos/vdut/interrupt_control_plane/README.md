# Edge-interrupt control-plane VirtualDut demo

本例实际装配并执行一个最小的中断通知系统：

```text
scenario-driven notifier A --\
                              priority controller --> explicit-EOI target
scenario-driven notifier B --/
```

A 先提交 `interrupt_id=40, priority=7`，B 后提交
`interrupt_id=11, priority=1`。controller 保留两项后选择数值更小的 priority，
所以 CPU target 先处理 11；CPU 显式 EOI 后，controller 才投递 40。

从仓库根目录运行：

```bash
.venv/bin/python showcase/demos/vdut/interrupt_control_plane/run.py
```

脚本仅原子替换
`showcase/generated/vdut/interrupt-control-plane/`，同时保存 DOT、WaveJSON、
运行结果、provenance 和 manifest。`--publish-root <directory>` 可以把同一份
证据发布到 scratch 目录。

图中的横向“波形”是模型步骤视图：一列表示一次完成的 `SystemSession` action
或 service opportunity。它不表示时钟、物理延迟、RTL pin 或 cycle-exact
中断时序。

两个 notifier 在这个演示中是由 scenario 驱动的 `CaptureBackend` 边界，用于提供
真实 InterfaceProtocol 输入并接收 completion；它们不是已经实现的传感器中断源。
controller 与 explicit-EOI target 是 constructed `VirtualDut`。本例也不声称
实现 GIC、PLIC、APIC、CSR 地址接口、level interrupt、mask、affinity 或抢占。
