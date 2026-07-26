# AXI attachment implementations

这里保存 AXI4、AXI4-Lite 和 AXI4-Stream 单端口的 event↔operation 转换：

- `axi4/`：burst-aware subordinate、serialized requester 和 AW/W 等接口侧状态；
- `axi4_lite/`：single-access requester/completer；
- `axi4_stream/`：`StreamTransfer` transmitter/receiver。

Attachment 只拥有一个端口的 codec 与接口侧状态。跨端口 parent/child 调度、completion fold、route、FIFO 和
owner table 属于 bridge/fabric backend；完整 module 由
[`integrations/recipes/amba`](../../../recipes/amba/README.md)装配。公共 AXI 接口定义位于
[`protocols/amba/axi`](../../../../protocols/amba/axi/README.md)。
