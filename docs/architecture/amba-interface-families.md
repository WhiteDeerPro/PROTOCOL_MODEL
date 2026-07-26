# AMBA interface 家族与 CHI 边界

AMBA 是标准家族名称，不是一个可以直接运行的统一协议，也不代表其中所有标准都能放进同一种工程对象。
AXI、AHB、APB 和当前 ACE-Lite profile 进入 InterfaceProtocol catalog；CHI 在同一标准族目录中跨 protocol、
network representation、transport 和 system 视图组织。

```text
protocol_model/protocols/amba/
├── axi/
│   ├── axi4/          memory-mapped、多 outstanding、burst 与 ID
│   ├── axi4_lite/     memory-mapped、single-beat、无 ID
│   └── axi4_stream/   单向 packet/stream interface
├── ahb/
│   ├── ahb_lite/      AHB-Lite address/data pipeline 与 cycle observer
│   └── ahb5/          Issue C interface-property InterfaceProtocol
├── apb/
│   ├── apb3/          APB3
│   ├── apb4/          APB4
│   ├── apb5/          APB5 optional-signal profile
│   └── _common/       不公开的 phase/completion 派生层
├── ace/
│   └── ace_lite/      ACE-Lite ordinary-data profile
├── chi/               CHI Issue H 多视图 family；含受限 representation/transport/participant/system slice
└── byte_lanes.py      不依赖具体协议字段名的 AMBA byte-lane 几何
```

## 家族分包原则

源码按标准家族和共享语义分包，使依赖关系与协议关系一致。相较于把所有名字平铺在一个通用接口根部，这种
组织可以明确三种关系：

1. 它们都属于 AMBA 标准族，但不都属于 InterfaceProtocol；
2. AXI4、AXI4-Lite 和 AXI4-Stream 属于 AXI 家族，但不是同一个 event schema 的子类；
3. 只依赖标准化 transfer 几何的代码可以提升到 AMBA 共享区，不让 AHB 反向依赖 AXI。

公共导入路径相应为：

```python
from protocol_model.protocols.amba.axi.axi4 import build_axi4_interface
from protocol_model.protocols.amba.axi.axi4_lite import build_axi4_lite_interface
from protocol_model.protocols.amba.axi.axi4_stream import build_axi4_stream_interface
from protocol_model.protocols.amba.ahb.ahb_lite import build_ahb_lite_interface
from protocol_model.protocols.amba.ahb.ahb5 import build_ahb5_interface
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.apb.apb5 import build_apb5_interface
from protocol_model.protocols.amba.ace.ace_lite import build_ace_lite_data_interface
```

不保留原来的平铺导入 facade。`apb` 根包只导出供 integration/system 识别协议家族的
`APB_FAMILY`；AHB 根包同样只导出 `AHB_FAMILY`。具体 config、signal DTO、observer 和 builder 由版本包导出。

## Interface、integration 与 System 的边界

```text
protocols/amba/* profiles + VirtualDut contracts
          │
          ├──── integrations/attachments/amba
          │       单端口 event ↔ operation 与接口侧状态
          ├──── integrations/translations/amba
          │       bridge plan 复用的 typed lower/lift stage
          └──── integrations/backends/amba（按需）
                  协议规则直接塑造的 module controller
          │
          └──────────────────────────┐
                                     ▼
integrations/recipes/amba
  选择 attachment、translation/backend 与 port，构造具体 VirtualDut
          │
          ▼
VirtualDut port + binding + backend
  形成一个具体 module 的协议边界和行为
          │
          ▼
SystemProtocol
  连接具体端口，闭合 topology 与跨 connection 规则
```

因此 `integrations/attachments/amba`、`integrations/translations/amba`、`integrations/backends/amba` 和
`integrations/recipes/amba` 不迁入 `protocols/amba`。它们需要同时认识协议及 VirtualDut 的边界、转换、执行或
构造契约，是两个独立核心之间有意设置的接缝，而不是 InterfaceProtocol 定义本身。

## ACE 与 CHI 不能按目录外观视为同形接口

完整 ACE 的 AC/CR/CD 等 channel 关系可由相应 InterfaceProtocol profile 表达。CHI 的一部分规则也能在一个 node
interface 或 transport hop 局部判定，但它们分别属于 protocol transaction、network representation 或 Link-layer
transport。它们复用共同 EventSchema、monitor、resource 和 session product，不通过塞进 InterfaceProtocol 来复用。

但一致性是否正确通常还依赖多个节点和多条 connection/hop：

- request/snoop 最终路由到哪个 node；
- 某条 cache line 当前由谁持有、哪些副本需要失效；
- home node、request owner 与 completion return 是否闭合；
- 跨 virtual channel 的资源依赖是否可能停滞。

这些规则由使用 ACE/CHI interfaces 与 transport contracts 的 SystemProtocol 或 coherence 语义组件组合。
当前 ACE-Lite 已有一个明确缩小的
ordinary-data profile；CHI 已有受限的 direct-read/retry 与 transport-network slice，但还不是完整 RN/HN/SN/MN
或 coherence profile。具体范围见
[ACE/CHI 接口与系统边界](ace-chi-communication-scopes.md)。
