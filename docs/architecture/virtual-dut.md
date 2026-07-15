# VirtualDut：从局部行为到外部 module

## 1. 定位

`VirtualDut` 是协议网络中的一个具体、具名、虚拟 module。对本项目而言，它首先是外部通信参与者：

- 内部状态可以不透明、不可枚举；
- backend 提供的功能行为在当前验证范围内作为权威输入；
- 本项目检查它在端口上表现出的协议和网络行为，不证明 backend 内部算法；
- AXI、AHB、APB 等协议通过 `ProtocolPort` 绑定，不形成设备继承树。

为了构造随机激励、理想 responder、bridge、crossbar 等测试环境，工程也允许用通用算子组合一个
可执行 backend。这是可选构造路径，不限制外部 VirtualDut 的状态空间。

因此存在两条等价入口：

```text
External/RPC/RTL/Trace backend ─────────────────────┐
                                                    ▼
primitive semantics → behavior operators → constructed backend
                                                    │
                                                    ▼
                                              ProtocolPort
                                                    │
                                                    ▼
                                               VirtualDut
                                                    │
                                                    ▼
                                              SystemProtocol
```

## 2. 与协议分层的对应关系

协议和 VirtualDut 都采用 bottom-up 建模，但关注内容不同：

```text
Protocol path                         VirtualDut path

Constraint / Resource / Obligation    token / local transition / resource
              │                                      │
SemanticFragment                      behavior operator graph
              │                                      │
LinkProtocol                          opaque or constructed backend
              │                                      │
              └────────────── ProtocolPort ──────────┘
                                      │
                                  VirtualDut
                                      │
                              ProtocolLink / topology
                                      │
                                SystemProtocol
```

`LinkProtocol` 回答“一条 link 上什么通信语言合法”；backend 回答“这个 module 想做什么”；
`ProtocolPort` 把 backend 的行为绑定到一个协议角色；`SystemProtocol` 再判断多个 module 连接后的
全局行为。

## 3. 局部行为语义

最底层只描述一次局部状态转移，不出现 AXI、DMA、crossbar 等名称：

```text
(local state, input tokens, available resources)
    → (new state, output tokens, resource changes)
```

该层关注：

- 一次转移原子消费和产生哪些 token；
- guard 在什么条件下使转移可执行；
- resource 在何处 acquire/release；
- request、completion、notification 的因果关系；
- reset、cancel、error 如何结束未完成生命周期。

状态机是这一层的执行语义，但不是主要编写界面。复杂 backend 应由局部转移组合，不要求用户维护
一个包含所有端口和资源组合的单体 FSM。

事件的角色也在这里区分：

| 事件作用 | 生命周期含义 |
|---|---|
| request/initiation | 开启 obligation |
| completion/response | 依赖并解除 obligation |
| notification | 由内部变化产生新的外部可见事件 |
| acknowledgement | 接受或关闭 notification |

因此 `signaling` 不需要成为独立设备类别；它是 emission 的因果角色。

## 4. 可复用行为构造

可构造 backend 使用一组正交 token-flow 算子：

| 算子 | 关注内容 | 典型用途 |
|---|---|---|
| `Source/Choice` | 创建 token、脚本、随机或环境选择 | manager、流量发生器 |
| `Sink/Observe` | 消费、记录、断言或丢弃 token | monitor、scoreboard endpoint |
| `Transform` | map、filter、rewrite、拆分和合并字段 | width/field converter |
| `Store/Resource` | FIFO、table、pool、counter、register、reorder buffer | 高流水、乱序、反馈环 |
| `Correlate/Join` | 按 FIFO、key 或 descriptor 归并多个 token | AW/W、request/response |
| `Route/Fork` | decode、owner-return、multicast 和分支 | decoder、crossbar、router |
| `Select/Arbitrate` | 从多个 enabled 候选中选择 | fixed/round-robin/weighted |
| `Compose/Hide` | 连接算子、反馈、隐藏内部 token、封装边界 | bridge、DMA、复合 Vdut |

本表中的 `Transform` 目前是行为意图和分解词汇，不代表源码里已经存在一个完整的通用算子。跨协议
bridge 需要的可执行版本将收窄命名为 typed `TranslationStage`：它同时声明 source/target operation form、
1→N 基数、属性处理和反向 completion fold；调度、容量 lease 与 correlation 由 plan executor 管理。详见
[Bridge 与类型化事务转译](typed-transaction-translation.md)。

这些是构造方法，不是互斥 facet。一个 crossbar recipe 可以写成：

```text
request ports
    → Route(address)
    → per-target Store(FIFO)
    → Select(arbiter)
    → destination ports

response ports
    → Correlate(owner table)
    → Route(source port)
```

随机序列既可以由外部 oracle 直接提供，也可以由本地 `Choice` 加 RNG state 生成。若流量通过反馈环
循环产生，环上需要显式 `Store`、token capacity 或后续的时间延迟，避免零时间 fixed-point 自激。

## 5. Backend：行为的权威来源

backend 拥有功能状态并决定收到输入后产生什么输出。公共边界不假设它是有限状态：

```text
opaque history + input → zero or more outputs
```

预计支持以下 backend 形态：

| Backend | 状态所有权 | 主要用途 |
|---|---|---|
| external/RTL proxy | 外部 simulator 或真实 DUT | 被观察对象 |
| RPC/Python oracle | 外部程序或参考模型 | 权威功能行为 |
| trace replay | 记录文件 | 可重复场景 |
| nondeterministic environment | 运行引擎的 choice | open-system 假设探索 |
| constructed backend | token-flow 算子图与显式状态 | traffic、memory、bridge、crossbar fixture |
| composite backend | 内部 SystemProtocol | 层次化封装 |

只有需要 bounded exploration、snapshot 或 replay 时，backend 才额外提供可复制状态。外部 backend
不因无法枚举内部状态而失去 VirtualDut 身份。

该层关注：

- input/output 调用边界；
- backend state 的所有权和 reset；
- deterministic、seeded choice、replay 或外部 oracle；
- immediate、blocked、deferred emission；
- 外部错误与模型基础设施错误的区分。

## 6. ProtocolPort 与 attachment：协议边界

`ProtocolPort` 是 backend 与 LinkProtocol 的汇合点：

```text
backend operation/output
        ↕ protocol attachment
CanonicalEvent
        ↕ LinkProtocol
ProtocolLink
```

这里需要区分三个对象，避免用一个 `attach()` 同时表示声明、实现和组网：

| 对象 | 含义 | 状态所有权 |
|---|---|---|
| `ProtocolPort` | module 边界公开的 protocol、role、capability 和 domain | 不保存运输状态 |
| `ProtocolAttachment` | 某 operation family 与 CanonicalEvent 的可复用转换 | 声明初态和静止条件 |
| `PortAttachmentBinding` | 将一个 attachment 实例绑定到一个具体 port | 静态、不可变；动态状态仍在 backend state |

`VirtualDutBuilder.bind_port()` 或 `.bind()` 执行本地绑定；`SystemProtocol` 的 `ProtocolLink` 只连接已经
声明好的端口。SystemProtocol 不调用 APB/AHB/AXI attachment，也不反射 backend 私有状态。
Attachment-aware backend 会投影自己实际使用的 binding；构造 `VirtualDut` 时要求该投影与公开
binding 使用同一对象，避免“声明看见一个 adapter、运行时执行另一个 adapter”的双重配置。

具体协议转换位于 `protocol_model/integrations/`。例如 APB address attachment 同时认识 APB event 和
`AddressAccess`，但 APB `LinkProtocol` 本身不导入 VirtualDut。协议 refinement 通过稳定的 protocol
family 和 transport shape 与 attachment 匹配，不依赖可能变化的显示名称。

该层关注：

- 绑定的 LinkProtocol 和 role；
- 可接受、可发出的 channel/event direction；
- typed capability/profile；
- clock/reset domain；
- pin、cycle、UVM transaction 与 CanonicalEvent 的 observation/driver；
- backend operation 与协议事务的 translation；
- 协议运输状态，例如 AXI ID、burst、AW/W join、AHB phase context。

空端点也沿用同一边界：`idle source` 的本地 backend 不自主发出事件；`blackhole sink` 接收后不产生
completion。后者在 APB、AHB 和 AXI 这类请求—响应协议上会留下未完成 obligation，适合挂起和
deadlock 场景，不等价于正常 responder。当前 `SystemAction` 仍是显式外部注入入口，因此可驱动一个
idle source；严格的 emission authority 留给后续 boundary runtime，而不是让 SystemProtocol 识别某个
协议 attachment。

`Addressable` 和 `Initiating` 不必是核心 facet：前者由端口接受的 address operation 表达，后者由
端口能够发出开启型事件推导。`AddressSpace`、RegisterBank 和 Memory 是 constructed backend 的
可选 reference fixture，不是所有 VirtualDut 的内部结构。

decode miss、只读写入等正常设备结果在 attachment 中映射为 AXI `DECERR/SLVERR`、AHB `ERROR`
或 APB error，不默认提升为模型基础设施故障。

## 7. VirtualDut module：完成模块边界

到这一层才形成 topology 中的具体节点：

```text
VirtualDut
  name / identity
  ProtocolPorts
  boundary contract
  backend binding
  optional external resource/capability projection
  optional hidden internal composition
```

该层关注一个 module 的多端口关系：

- 哪些输入可以触发哪些端口输出；
- 跨端口 transaction ownership/correlation；
- externally visible capacity、backpressure 和 completion；
- assumption/guarantee；
- 内部事件隐藏后的边界 trace。

`Storing`、`Transforming` 和 `Routing` 在这一层不是身份标签：它们是 constructed backend 使用的
算子。外部 backend 可以具有同样行为而不公开内部 FIFO、table 或 route 实现。

一个物理 crossbar 可以作为单个 routing VirtualDut；也可以展开成 decoder、FIFO、arbiter 和 router
构成的内部 SystemProtocol，再封装回相同边界。两种形式的关系应由隐藏内部 link 后的 boundary
refinement 描述。

## 8. SystemProtocol：连接具体模块

SystemProtocol 不查看 backend 私有状态，只组合 VirtualDut 的端口与边界 contract：

- topology 和 link ownership；
- address/route 闭合；
- 跨 link ID、owner 和 response return；
- network buffer、credit、outstanding 和 wait-for；
- deadlock、livelock、starvation、QoS 和 fairness；
- internal link hide 与整体 refinement。

Routing 的层级依作用域区分：crossbar module 内部的 route 选择属于其行为构造/backend；多个 VirtualDut 之间
的端到端路径属于 SystemProtocol。展开或封装不应改变外部协议意义。

## 9. Bottom-up 构造流程

构造一个可执行 VirtualDut 时按以下顺序推进：

1. 确定验证目标和外部端口，不从完整设备功能开始。
2. 能使用 external/oracle backend 时直接绑定，不重建其内部状态。
3. 需要本地构造时，将行为分解成 token-flow 构造方法。
4. 为 Store、table、pool 等声明容量和生命周期。
5. 用 Correlate、Route、Arbitrate 表达多通道和多端口关系。
6. 将 backend operation 通过 attachment 绑定到 ProtocolPort。
7. 声明 module 边界的 assumption、guarantee 和 externally visible resource。
8. 放入 SystemProtocol 检查全局闭合。
9. 只有验证目标需要时才加入 deferred emission、time window 或 clock domain。

构造复杂度按关注范围增加：

| 级别 | 主要关注 | 示例 |
|---|---|---|
| C0 | 外部端口声明 | opaque RTL/RPC Vdut |
| C1 | 无状态 token 转换 | mapper、field converter |
| C2 | 局部状态和容量 | FIFO、register、ID pool |
| C3 | correlation、route、arbitration | bridge、crossbar |
| C4 | 自主推进和多端口 obligation | DMA、cache controller fixture |
| C5 | deferred、time、clock domain | timer、CDC、async FIFO |

复杂度等级不是设备类别。一个外部 DMA 可以停在 C0；只有要在本项目内部构造 DMA fixture 时，才
逐步进入 C2-C5。

当前能力矩阵由[迁移状态](migration-status.md)维护；bridge/Transform 的拟议源码抽取和实施顺序见
[事务转译 V1 计划](translation-v1-plan.md)。本页后续只说明稳定的源码职责边界。

## 10. 源码职责分层

源码目录显式表达 VirtualDut 内部已有的职责边界：

```text
protocol_model/virtual_dut/
├── boundary/
│   ├── port.py              ProtocolPort
│   └── module.py            VirtualDut、DutFacet
├── binding/
│   ├── port.py              PortAttachmentBinding
│   └── builder.py           VirtualDutBuilder 本地装配
├── backend/
│   ├── transition.py        DutEffect、PortInput/Emission、DutTransition
│   ├── base.py              VirtualDutModel contract
│   ├── simple.py            Capture/Function fixture
│   └── address_space.py     PassiveAddressSpaceBackend
├── address/
│   ├── access.py            AddressRead/Write、AccessResult
│   ├── space.py             region dispatch
│   ├── register.py          register reference region
│   └── memory.py            sparse memory reference region
├── attachments/
│   ├── base.py              ProtocolAttachment SPI
│   ├── address.py           requester/completer contract 与 DTO
│   ├── empty.py             idle/blackhole 空端点意图
│   └── validation.py        emission schema/direction validation
├── fabric/
│   ├── route.py             AddressRoute 与地址重映射
│   ├── state.py             pending owner 与 fabric runtime state
│   └── single_ingress.py    decoder、request/response path
└── recipes/
    └── empty.py             协议无关空端点装配
```

协议专用集成另行放置：

```text
protocol_model/integrations/
├── attachments/amba/        单端口 AMBA event ↔ operation 翻译
│   ├── apb/                 APB ↔ AddressAccess
│   ├── ahb/                 AHB ↔ AddressAccess 与 write phase join
│   └── axi/
│       ├── axi4/            burst transport 与 serialized requester
│       ├── axi4_lite/       AddressAccess 两面
│       └── axi4_stream/     StreamTransfer 两面
└── recipes/amba/            具体 AMBA-bound VirtualDut 的 composition root
    ├── endpoints/           AddressSpace、stream capture 与空端点
    ├── fabrics/             同协议多端口 route/response-mux
    └── bridges/             跨协议 transform/correlation module
```

这些目录是源码职责，不增加新的协议层。`fabric` 仍是一个 VirtualDut 内部的多端口 backend 家族；
只有展开其内部 module/link 时才形成子 SystemProtocol。

依赖规则是：

1. 内部模块从叶文件导入，不通过根 facade 形成反向依赖；
2. attachment 只处理单端口，不依赖 fabric、boundary 或 recipe；
3. fabric 组合 address、attachment contract 和 backend foundation，但不创建 VirtualDut；
4. recipe 位于装配末端，负责把 ProtocolPort、attachment 和 backend 组合成具名 VirtualDut；
5. SystemProtocol 直接依赖 boundary/transition 叶模块，避免加载具体 recipe。

根 `protocol_model.virtual_dut` 只暴露常用构造面。具体 attachment、backend state 和 pending owner 等
实现类型从所属子包访问，避免每次扩展协议都扩大顶层 API。
