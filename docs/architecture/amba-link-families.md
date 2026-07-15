# AMBA LinkProtocol 家族组织

AMBA 是协议家族名称，不是一个可以直接运行的统一协议。本工程把它放在 `LinkProtocol` 层，并按照
每个协议实际拥有的 channel、role 和事务关系继续分组：

```text
protocol_model/link/amba/
├── axi/
│   ├── axi4/          memory-mapped、多 outstanding、burst 与 ID
│   ├── axi4_lite/     memory-mapped、single-beat、无 ID
│   └── axi4_stream/   单向 packet/stream link
├── ahb/
│   ├── ahb_lite/      AHB-Lite address/data pipeline 与 cycle observer
│   └── ahb5/          Issue C interface-property LinkProtocol
├── apb/
│   ├── apb3/          APB3
│   ├── apb4/          APB4
│   ├── apb5/          APB5 optional-signal profile
│   └── _common/       不公开的 phase/completion 派生层
├── ace/
│   └── ace_lite/      ACE-Lite ordinary-data profile
├── chi/               CHI Issue H 后续 basic profile 边界
└── byte_lanes.py      不依赖具体协议字段名的 AMBA byte-lane 几何
```

## 家族分包原则

源码按标准家族和共享语义分包，使依赖关系与协议关系一致。相较于把所有名字平铺在 `link/` 根部，这种
组织可以明确三种关系：

1. 它们都属于 AMBA LinkProtocol；
2. AXI4、AXI4-Lite 和 AXI4-Stream 属于 AXI 家族，但不是同一个 event schema 的子类；
3. 只依赖标准化 transfer 几何的代码可以提升到 AMBA 共享区，不让 AHB 反向依赖 AXI。

公共导入路径相应为：

```python
from protocol_model.link.amba.axi.axi4 import build_axi4_link
from protocol_model.link.amba.axi.axi4_lite import build_axi4_lite_link
from protocol_model.link.amba.axi.axi4_stream import build_axi4_stream_link
from protocol_model.link.amba.ahb.ahb_lite import build_ahb_lite_link
from protocol_model.link.amba.ahb.ahb5 import build_ahb5_link
from protocol_model.link.amba.apb.apb4 import build_apb4_link
from protocol_model.link.amba.apb.apb5 import build_apb5_link
from protocol_model.link.amba.ace.ace_lite import build_ace_lite_data_link
```

不保留原来的平铺导入 facade。`apb` 根包只导出供 integration/system 识别协议家族的
`APB_FAMILY`；AHB 根包同样只导出 `AHB_FAMILY`。具体 config、signal DTO、observer 和 builder 由版本包导出。

## Link、integration 与 System 的边界

```text
link/amba
  规定 event、channel、role、单 link ordering/resource
          │
          ▼
integrations/attachments/amba
  把单个 AMBA 端口的 event 翻译为 VirtualDut operation，并编码返回 event
          │
          ▼
integrations/recipes/amba
  组合 attachment、backend 与 port，构造具体 VirtualDut
          │
          ▼
VirtualDut port + binding + backend
  形成一个具体 module 的协议边界和行为
          │
          ▼
SystemProtocol
  连接具体端口，组合 route、owner、容量和跨 link 规则
```

因此 `integrations/attachments/amba` 和 `integrations/recipes/amba` 不迁入 `link/amba`。它们需要同时认识
协议及 VirtualDut 的边界或构造契约，是两个独立核心之间有意设置的接缝，而不是 LinkProtocol 定义本身。

## ACE 与 CHI 的 link-local 子域

ACE 和 CHI 都有可以在单条接口/链路上定义的消息语言，例如 channel schema、方向、credit、retry 和事务
correlation。这部分应建立为 LinkProtocol，才能复用 observation、LinkSession 和单链路生成方法。

但一致性是否正确通常还依赖多个节点和多条 link：

- request/snoop 最终路由到哪个 node；
- 某条 cache line 当前由谁持有、哪些副本需要失效；
- home node、request owner 与 completion return 是否闭合；
- 跨 virtual channel 的资源依赖是否可能停滞。

这些规则由使用 ACE/CHI links 的 SystemProtocol 或 coherence 语义组件组合。换句话说，ACE/CHI 的“线上
语言”在 Link 层，完整一致性系统的“全局事实”在 System 层。当前 ACE-Lite 已有一个明确缩小的
ordinary-data profile；CHI 仍是经过规范审计的待实施边界。具体范围见
[ACE/CHI Link 边界](ace-chi-links.md)。
