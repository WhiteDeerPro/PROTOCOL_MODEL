# SystemProtocol 源码结构

`SystemProtocol` 是一个验证作用域内的通信模型聚合根：它组合具体 `VirtualDut`、连接、系统边界和
需要跨多个连接判断的合同。它复用 `InterfaceProtocol` 与 VirtualDut 语义，但不继承它们的 Python API；
三者观察的 alphabet 和状态范围不同。

```text
InterfaceProtocol / transport profiles + VirtualDut boundaries
                    │
                    ▼
              weak topology
                    │ + system contracts
                    ▼
              SystemProtocol
                    │ elaborate / resolve
                    ▼
        ElaboratedSystemProtocol
          ├─ address_plan
          └─ transport_plan
                    │ execute / monitor / analyze
                    ▼
       trace + verdict + derived evidence
```

“weak topology”只回答谁连接到谁。它用 `InterfaceConnection` 表示完整逻辑接口的一次使用，
用 `DirectedTransportConnection` 表示单向 transmitter→receiver hop；两者位于同一个连接注册表，不维护
一份并行的 transport topology。一个 N×M 多端口节点可能是 crossbar、广播器、静态 demux 或外部
黑盒；SystemProtocol 不根据图形形状猜测 VirtualDut 行为。地址闭合、能力匹配、返回归属和 progress
属于另外的 system contracts、resolution pass 和 monitor。

## 1. 目标目录

```text
system/
├── protocol.py              SystemProtocol 聚合根；迁移期间保留
├── elaboration.py           当前 elaboration 薄入口；迁移期间保留
├── session.py               当前同步 runtime；迁移期间保留
├── topology/                module/port/connection/boundary 弱结构图
├── contracts/               address、capability、identity、domain、property 声明
├── construction/            builder、显式 lowering 与生成 provenance
├── resolution/              closure passes 与不可变 resolved plan
├── runtime/                 action、state、trace、scheduler、延迟 lineage
├── monitors/                跨连接在线 ledger 与 system verdict
└── analysis/                reachability、wait-for、deadlock、refinement
```

这些子包按真实 vertical slice 逐步填充；尚为空的职责包不表示对应能力已经实现。当前 topology model、
address contract/direct-neighbor resolution 和 construction builder 已落地，公共 API 继续从
`protocol_model.system` facade 导入。

## 2. 当前对象的迁移地图

下表把“现在可导入的位置”和“目标职责包”分开，避免把尚未拆分的 skeleton 误读为已落地 API。

| 对象或职责 | 当前所在 | 目标位置/说明 |
|---|---|---|
| `VirtualDutPortRef`、`InterfaceConnection` | `topology/model.py` | 已归位，根 facade 重导出 |
| `DirectedTransportConnection` | `topology/transport.py` | 已归位，与 interface connection 共用 canonical topology 注册表 |
| `PortOwnerRef` | `topology/ownership.py` | 已归位，区分两种 connection 与 boundary 所有权 |
| 端口解析、ownership 校验与连接查询 | 校验仍在根 `elaboration.py`；部分查询由对象映射直接提供 | 后续可在有复用场景时抽入 `topology/queries.py`，该文件当前不存在 |
| `SystemProtocol`、`from_interface()`、`as_virtual_dut()` | `protocol.py` | 保持为 topology + contracts 聚合根和便捷入口 |
| `elaborate_system_protocol()`、`ElaboratedSystemProtocol` | 根 `elaboration.py` | 已携带 `address_plan` 和 `transport_plan`；更广 resolved plan 仍是后续收敛点 |
| `AddressClaim`、router route closure | `contracts/address.py`、`resolution/address.py` | 已归位 |
| directed-hop projection | `resolution/transport.py` | 已产生不可变 `ResolvedTransportPlan` |
| `SystemAction`、`DutAdvanceAction`、`SystemEvent`、`SystemTrace`、`SystemSessionState`、`SystemSession` | 根 `session.py` | `runtime/` 目前只有 skeleton；等 scheduler/lineage 边界稳定后再按 actions/trace/state/session 拆分 |

根 `SystemSession` 目前执行 `InterfaceConnection`。具体 transport family 可从
`ElaboratedSystemProtocol.transport_plan` 构造自己的 session；例如 CHI Issue H 的
`ChiTransportNetworkSession` 读取调用方已声明的有向 hop 和 router 绑定，不在 session 内固定 line、ring 或 mesh。

当前 `elaboration.py` 与未来目录不使用同名，是为了允许旧入口和新 resolution passes 在迁移期共存。

## 3. SystemProtocol 独有的方法

下层对象提供局部事实，SystemProtocol 增加的是跨边界方法：

- topology ownership 和 boundary closure；
- address/home/identity authority 与 reachability；
- path capability 与 bridge/fabric effect closure；
- request origin、跨节点 owner 和 completion return；
- clock/reset/security/coherence membership；
- system monitor、wait-for、fairness 和 boundary refinement。

这些能力优先通过不可变 contract、resolution pass、monitor 和 analysis 组合，不建立
`AxiSystemProtocol`、`CrossbarSystemProtocol` 等设备/协议继承树。若需要类似 `refine()` 的体验，可以由
以后增加的 `derive(...)` 返回添加了合同的新 SystemProtocol。

Crossbar 是第一条 system vertical slice。当前 construction 将同一份显式 `AddressRouterContract` 交给注入的
VirtualDut factory，并把 backend 实际公开的 `AddressRouterBoundaryProjection` 与合同核对；完成 topology 后，
address resolution 再把其 route 闭合到 direct-neighbor claim。crossbar backend 持有 FIFO、arbiter、egress
lease 和 owner table。以后 system monitor
再检查实际端到端 reachability、return 和 ordering，而不复制这些局部可变状态。

## 4. 它是不是工程终点

SystemProtocol 是一份通信模型的聚合终点，不是验证工作流的终点，也不是物理层级的永久顶点：

```text
SystemProtocol
  ├── elaborate / resolve
  ├── execute or explore with scenario
  ├── monitor and produce verdict
  └── project trace into visualization/artifacts

SystemProtocol --as_virtual_dut()--> larger SystemProtocol
```

以后若增加 `Project`，它应是验证编排对象：选择 system、scenario/seed、外部 driver/observer、执行策略、
期望 property 和 artifact policy。Project 不成为更高一层协议，也不继承 SystemProtocol。

稳定架构见 [`docs/architecture/system-protocol.md`](../../docs/architecture/system-protocol.md) 和
[`docs/architecture/network-construction.md`](../../docs/architecture/network-construction.md)。

## 5. 依赖规则

- `topology` 不导入具体 protocol family、attachment、backend 或 recipe。
- `contracts` 声明系统意图，不持有 VirtualDut 的运行状态。
- `construction` 可以装配 VirtualDut/connection，但不在 runtime 隐式插入 bridge。
- `resolution` 只读输入并产生带 provenance 的不可变结果，不修改既有 VirtualDut。
- `runtime` 执行已经固定的 topology/resolved plan，不搜索转换方案。
- `monitors` 观察系统事件并给出 verdict，不冒充 DUT emission。
- `analysis` 只读消费 topology、resolved plan、trace 或资源快照，不参与执行。
- visualization、scenario 和 artifacts 保持顶层包，从系统边界之外消费公共投影。
