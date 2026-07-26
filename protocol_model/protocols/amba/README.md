# AMBA protocol-family assets

这个目录按 AMBA 标准族聚合具体资产。AXI、AHB、APB 和当前 ACE-Lite profile 主要表现为一个完整接口内
的 schema、transaction lifecycle、observation 和生成策略；CHI 则跨越 protocol transaction、network
representation、transport hop 和 system coherence，不能整体称作一个 `InterfaceProtocol`。

```text
amba/
├── axi/
│   ├── axi4/          AXI4 memory-mapped
│   ├── axi4_lite/     AXI4-Lite 原生 interface 与显式 AXI4 embedding
│   └── axi4_stream/   AXI4-Stream interface
├── ahb/
│   ├── ahb_lite/      AHB-Lite 基线与 sampled-cycle observer
│   └── ahb5/          Issue C configurable interface properties
├── apb/
│   ├── apb3/          APB3 独立 pin schema/API
│   ├── apb4/          APB4，PPROT/PSTRB 独立可选
│   ├── apb5/          APB5 user/wakeup/RME，当前关闭 parity
│   └── _common/       私有 SETUP/ACCESS 和 completion 引擎
├── ace/
│   └── ace_lite/      当前 ordinary-data interface profile
├── chi/               CHI 的跨视图归属与 Issue H 实施边界
└── byte_lanes.py      memory-mapped AMBA 共用、但不依赖协议字段名的几何
```

相邻职责的源码落点：

- `protocol_model.interface`：具体标准复用的接口合同/session 内核；
- `protocol_model.integrations.attachments.amba`：单端口 AMBA event 与 VirtualDut operation 的转换；
- `protocol_model.integrations.recipes.amba`：带 AMBA ports 的具体 VirtualDut 装配；
- `protocol_model.system`：module connections、全局身份/路由闭合和跨接口 monitor。

当前 ACE-Lite 入口名称中的 `data` 用来明示 barrier/CMO 边界。CHI 已有独立的 Issue H REQ/RSP/DAT
representation/transport slice，以及受限 direct-Home read/retry lifecycle。它分别公开 representation、
transport、interface ledger、participant behavior 和 system composition，不建立一个包揽全部职责的 CHI
interface builder。具体范围见 [`chi/README.md`](chi/README.md) 和
[实现状态](../../../docs/architecture/implementation-status.md)。
