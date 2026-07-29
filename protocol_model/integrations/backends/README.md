# Protocol-bound execution backends

本目录保存同时依赖具体 `InterfaceProtocol` 和 `VirtualDutBackend` 合同的跨端口执行实现。它们构成
constructed VirtualDut 的内部 realization，并由 integration recipe 完成最终装配。

## 准入条件

protocol-bound backend 负责具体协议直接塑造的 module 生命周期：

| 事实 | 典型例子 | 状态 owner |
|---|---|---|
| channel correlation | AXI AW/W join | backend controller |
| identity ordering | RID/BID destination lock、same-ID ordering | route/owner ledger |
| 跨端口返回 | downstream completion → ingress owner | owner FIFO/table |
| 协议保持型容量 | outstanding burst、partial transaction | immutable profile + backend state |

单端口 phase context 由 attachment 持有；协议无关的 route、store、address operation 与 typed executor 继续由
`virtual_dut/` 提供。

## 依赖与装配

```text
attachments / translations  ←  backends  ←  recipes
attachments / translations  ←──────────── recipes
```

| 构件 | 向 backend 提供的事实 |
|---|---|
| attachment | 单个 port 的 event/operation 边界及接口侧状态 |
| translation | typed operation 之间的 lower/lift、effect 与 plan fragment |
| backend | 跨端口 FIFO、route lock、owner 和 partial transaction |
| recipe | port、binding、profile 选择及最终 `VirtualDut` 构造 |

依赖方向固定为 attachment/translation → backend → recipe。运行时执行 recipe 已选择的构件；bridge 和
backend 的创建发生在 construction 阶段。一般使用者从 recipe facade 构造 module，本目录的叶模块服务 recipe、
定向验证和高级 inspection。

## 当前纵向切片

AXI4 实现位于 `amba/axi/axi4/`：

- `address_space.py`：burst-aware AXI4 endpoint 执行；
- `read.py`：AR/R N×M route、RID destination lock 与 return-owner 生命周期；
- `write.py`：AW/W assembly、BID destination lock 与 B return-owner 生命周期。

每个 vertical slice 共置 profile、immutable state records 与 controller，使 acquire、forward、return 和
retire 生命周期可以连续阅读。公共提取以第二个真实消费者为前提，并要求 key、取得、释放、reset 和故障语义
一致。

APB 的 SETUP/ACCESS context 和 AHB 的 address/data phase context 属于单端口 attachment state；对应
endpoint、单入口 fabric 与 serial bridge 复用协议中立的 address、fabric 或 translation backend。AXI4 的 burst、
多 outstanding ID、AW/W join、same-ID ordering 与跨端口 return owner 满足本目录的准入条件。

新增 family backend 以一项由具体协议塑造的跨端口或跨事务生命周期为准入证据。例如 AHB
exclusive/atomic、协议保持型 burst/lock 或多端口仲裁形成独立生命周期后，可以建立 `amba/ahb/` vertical
slice。CHI coherent Home 的 directory/transaction behavior 由 family participant/facet 持有；其 full-line
backing prepare/commit core 保持为协议中立状态。
