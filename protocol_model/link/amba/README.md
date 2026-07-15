# AMBA LinkProtocol families

这个目录只收纳 AMBA 家族的 **link-local 协议定义**：事件格式、端点角色、单链路事务关系、
observation 和生成策略。它不收纳具体设备行为，也不拥有网络 topology。

```text
amba/
├── axi/
│   ├── axi4/          AXI4 memory-mapped
│   ├── axi4_lite/     AXI4-Lite 原生 link 与显式 AXI4 embedding
│   └── axi4_stream/   AXI4-Stream packet link
├── ahb/
│   ├── ahb_lite/      AHB-Lite 基线与 sampled-cycle observer
│   └── ahb5/          Issue C configurable interface properties
├── apb/
│   ├── apb3/          APB3 独立 pin schema/API
│   ├── apb4/          APB4，PPROT/PSTRB 独立可选
│   ├── apb5/          APB5 user/wakeup/RME，当前关闭 parity
│   └── _common/       私有 SETUP/ACCESS 和 completion 引擎
├── ace/
│   └── ace_lite/      当前实现 ordinary-data profile
├── chi/               CHI Issue H 的设计边界，尚未进入执行代码
└── byte_lanes.py      memory-mapped AMBA 共用、但不依赖协议字段名的几何
```

分层关系：

- `protocol_model.link.amba`：规定线上允许出现什么；
- `protocol_model.integrations.attachments.amba`：把单端口 AMBA event 翻译为 VirtualDut operation；
- `protocol_model.integrations.recipes.amba`：装配带 AMBA 端口的具体 VirtualDut；
- `protocol_model.system`：连接具体端口，并承担跨 link 的 route、owner、容量和全局一致性。

ACE 和 CHI 的消息/channel/credit 等局部规则属于这里；目录、home node、跨 link snoop、cache-line
ownership 和全局 coherence progress 需要在 SystemProtocol 或专门的系统语义组件中组合。当前
ACE-Lite 公开 builder 名称包含 `data`，用来明示它尚不接受 barrier/CMO；CHI 则等待
conditional schema、credit frame 和 retry ledger 后再建立第一个 basic profile。
