# CHI family 源码导航

`protocol_model.protocols.amba.chi` 拥有 CHI 标准专用的协议合同、表示、运输和系统切面。Family 根入口公开稳定
身份 `CHI_FAMILY`，具体资产按规范 issue 和工程视图组织。一个 CHI family 可以同时具体化完整逻辑接口、
network representation、Link transport、participant behavior 与 system authority。

## Family ownership

| CHI 事实 | 判定范围与 owner |
|---|---|
| 一笔 operation 的请求、response 和 completion correlation | protocol transaction ledger |
| REQ/RSP/SNP/DAT opcode、字段与 typed message | network representation / message profile |
| source/target route identity 与 packet cardinality | network representation / packet |
| packet 在相邻 Link 上占用的 transport envelope | protocol flit |
| Link activation、channel FIFO、Resource Plane 与 L-Credit | 单向 `TransportLink` runtime |
| RN、HN、SN 或 forwarding facet 的局部状态与行为 | participant profile + `VirtualDut` |
| NodeID ownership、address→Home、coherence domain、flow 与 progress | `SystemProtocol` contracts、resolution 和 monitors |
| raw pin、lane、phit 与外部 trace lowering | observation / external integration |

`InterfaceProtocol` 用于完整逻辑接口内可判定的合同；CHI family 另外使用 representation、transport 和 system
对象承载其余判定范围。依赖方向从 CHI 具体资产指向通用 `semantics`、`interface`、`virtual_dut` 与 `system`
设施。

## Transaction、message、packet 与 flit

```text
operation
└── transaction lifecycle
    └── protocol message
        └── one or more network packets
            └── protocol flit on one directed Link
                └── phit / pin observation
```

| 形式 | 表达的事实 | 主要交接 |
|---|---|---|
| transaction | operation 从 issue 到 completion 的 lifecycle 与 correlation | 组合多条 protocol messages 和 participant state transition |
| protocol message | opcode、TxnID/DBID、address、response 与 operation attributes | packetizer 加入 route identity |
| network packet | 一份可独立路由的 message 表示、source/target NodeID 与 packet index/count | router 按 route identity 转发 |
| protocol flit | packet 在一条相邻 Link 上的 transport envelope | Link runtime 执行接纳、FIFO 与 L-Credit |
| phit/pin sample | physical transfer 的 observation input | observer lowering 为 normalized transport fact |

CHI Issue H 为 protocol packet、protocol flit 和 phit 定义一对一运输粒度；代码仍分别保存 packet route ownership
与 flit resource lifecycle。`LCrdReturn` 等 Link-maintenance flit 在当前 hop 产生和终止，直接服务 Link
maintenance。

Snoop target 由 system/network 选择。System construction 为每个 Snoopee 形成带显式 `target_id` 的 packet
copy，typed SNP message 保持规范字段集合；fanout copy identity 与同一 message 的内容分片分别使用 route
identity 和 packet index/count。

## Protocol Credit 与 Link Credit

| 资源 | 含义与作用域 | 获得、使用和释放 |
|---|---|---|
| P-Credit | completer 对 protocol transaction resource 的接纳保证 | `PCrdGrant` 经 Home→Requester RSP flow 授予；credited request 在 REQ flow 消费；未使用 credit 由 `PCrdReturn` 经 Requester→Home REQ flow 归还 |
| L-Credit | 相邻 receiver 接纳一个 flit 的能力 | 每个有向 Link、channel 和适用 Resource Plane 独立管理；flit enqueue 消费，receiver/link maintenance 归还 |

P-Credit 属于 Retry/transaction ledger，L-Credit 属于 hop-local transport state。两者可以复用通用
resource/lease primitive，并分别保持自己的 key、capacity、epoch 和 retirement 条件。

相关身份与资源继续按判定范围分工：

- TxnID、DBID、RetryAck 和 P-Credit 由 transaction/interface contract 关联；
- NodeID 字段与 packet route identity 由 representation 携带，NodeID 唯一 ownership 由 system resolution 闭合；
- flit、L-Credit、Resource Plane 与 activation 由 transport runtime 持有；
- address/Home authority、coherence domain 和跨 participant progress 由 system contracts 与 monitors 持有。

## 源码入口

```text
chi/
├── __init__.py             family identity：CHI_FAMILY
└── issue_h/
    ├── representation/     typed messages、logical-field record、packet 与 flit
    ├── interface/          transaction correlation、Retry 与 P-Credit ledgers
    ├── transport/          directed Link、activation、L-Credit、endpoint 与 network runtime
    ├── participants/       RN/Home transaction behavior、cache/directory state 与 forwarding facet
    ├── system/             identity、authority、flow/capability resolution、composition 与 progress
    └── observation.py      Issue H normalized observation helpers
```

- Family identity 从 [`chi/__init__.py`](__init__.py) 导入。
- Issue H 公共对象与可执行 profile 从
  [`protocol_model.protocols.amba.chi.issue_h`](issue_h/__init__.py) 及对应 view 的 leaf facade 导入。
- 当前 Issue H 源码切面和使用入口见 [`issue_h/README.md`](issue_h/README.md)。
- CHI participant 与具体 module 的装配入口位于
  [`integrations/recipes/amba/chi`](../../../integrations/recipes/amba/chi/)。

## VirtualDut 与 System construction 交接

Participant 将 cache、directory、pending transaction 和局部 policy 绑定到具名 `VirtualDut`；forwarding facet
表达 router 等 module 的转发行为。Module 通过 `TransportPort` 暴露 CHI directed channels，并由
`DirectedTransportConnection` 形成显式 transmitter→receiver hop。

System construction 注册 VirtualDuts、connections、NodeID/address/coherence contracts，并在 resolution 阶段
闭合 identity ownership、Home authority、可运行 flow、participant capability 与 topology route。Family runtime
消费 resolved topology 执行逐 hop transport 和端到端 lifecycle，system monitor 在稳定点判定跨节点 invariant
与 progress property。通用 SystemProtocol 职责见 [`system/README.md`](../../../system/README.md)。

每类 evidence 的 claim 跟随判定范围：codec round-trip 支持表示 claim，Link session 支持 hop/credit claim，
transaction session 支持所选 lifecycle claim，resolved system witness 支持其声明的 authority、flow 和 invariant。
扩展到其他 issue、profile 或性质时，由对应合同与证据建立新的 claim。

## Canonical 文档与实现状态

- 三张工程视图与通用术语：
  [`communication-scope-and-transport.md`](../../../../docs/architecture/communication-scope-and-transport.md)
- ACE/CHI 作用域映射：
  [`ace-chi-communication-scopes.md`](../../../../docs/architecture/ace-chi-communication-scopes.md)
- 当前实现覆盖、明确边界与证据：
  [`implementation-status.md`](../../../../docs/architecture/implementation-status.md)
- 当前施工顺序与下一切片：
  [`technical-route/08-roadmap.md`](../../../../docs/architecture/technical-route/08-roadmap.md)

本页维护稳定 family ownership 和导航；Issue H feature 清单由 Issue H README 与 implementation status 维护，
工作顺序由 roadmap 维护。
