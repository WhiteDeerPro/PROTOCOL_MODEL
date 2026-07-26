# Protocol-bound execution backends

本目录保存同时依赖具体 `InterfaceProtocol` 和 `VirtualDutBackend` 合同的执行实现。它们属于一个
constructed VirtualDut 的内部行为，但不够协议中立，因而不进入 `protocol_model.virtual_dut.backend`。

允许的依赖方向为：

```text
attachments / translations  ←  backends  ←  recipes
attachments / translations  ←──────────── recipes
```

- attachment 只解释一个 port 的 event/operation 边界及接口侧状态；
- translation 声明 typed operation 之间的可复用 lower/lift 与 effect；
- backend 保存跨端口 FIFO、route lock、owner、partial transaction 等 module 私有状态；
- recipe 选择 port、binding、profile 和 backend，最终构造 `VirtualDut`。

Backend 不导入 recipe，也不在运行中搜索或隐式插入 bridge。面向一般使用者的构造入口仍由 recipe facade
公开；本目录的叶模块主要供 recipe、定向验证和高级 inspection 使用。

当前 AXI4 纵向切片位于 `amba/axi/axi4/`：

- `address_space.py`：burst-aware AXI4 endpoint 执行；
- `read.py`：AR/R N×M route、RID destination lock 与 return-owner 生命周期；
- `write.py`：AW/W assembly、BID destination lock 与 B return-owner 生命周期。

每个文件暂时共置其 profile、immutable state records 和 controller，以便完整阅读同一生命周期。只有两个
切片确认 key、取得、释放和错误语义一致后，才提取 common helper；read/write 都使用映射或 ID 并不足以建立
通用 owner-table 基类。

`amba/` 当前只有 AXI4 不是 APB/AHB 的实现缺口，也不要求按协议名称补齐目录。APB 的 SETUP/ACCESS context
和 AHB 的 address/data phase context 都属于单端口 attachment state；其 endpoint、单入口 fabric 和 serial
bridge 目前分别可复用协议中立的 address、fabric 或 translation backend。AXI4 则有 burst、多 outstanding
ID、AW/W join、same-ID ordering 与跨端口 return owner，这些协议规则直接塑造 controller 生命周期，才达到
本目录的准入条件。

如果后续 AHB exclusive/atomic、协议保持型 burst/lock 或多端口仲裁形成不能由 attachment 与通用 operation
表达的跨事务状态，再建立 `amba/ahb/` backend。APB 当前没有同等级需求。CHI coherent Home 的
directory/transaction behavior 仍是 family participant/facet；它注入的 full-line backing prepare/commit
core 是协议中立状态，因此也不为目录对称建立 `backends/amba/chi/`。
