# `protocol_model` 源码导航

本目录实现从单接口合同、虚拟 module 到通信网络的可组合模型。源码组织使用两条轴：

1. 顶层包回答“谁有权解释、保存或判断这项事实”；
2. 同一职责内再区分声明、策略、运行状态、生命周期控制、投影和最终装配。

因此，这里不是一条把 `semantics → protocol → VirtualDut → system` 依次继承起来的类层次。具体协议族可以
同时具体化接口、表示、运输和系统规则；`VirtualDut` 与 `SystemProtocol` 则分别拥有 module 局部状态和跨连接
事实。

## 顶层职责

| 包 | 拥有的事实 | 不应承担的职责 |
|---|---|---|
| `semantics` | scope-neutral event schema、fault、resource 和共同值对象 | 具体协议、设备或网络拓扑 |
| `patterns` | 可复用的协议关系与 monitor 状态 | DUT 内部 FIFO、仲裁或 owner table |
| `observation` | pin/frame/cycle sample 到 event candidate 的解释 | 已接纳事务的设备执行状态 |
| `interface` | 一个完整逻辑接口内的合同与 session | 多 module 路由或具体标准名单 |
| `protocols` | AXI、AHB、CHI 等标准族的具体切面 | 反向定义通用内核的职责 |
| `virtual_dut` | 具名 module 边界、协议中立 operation 和可复用局部 backend | 具体协议族继承树或全局网络事实 |
| `integrations` | 具体协议与 VirtualDut SPI 的依赖汇合 | 新的协议语义层 |
| `system` | topology、跨连接 contracts、resolution、runtime 与 analysis | 私有 backend 状态或隐式插桥 |
| `scenario` | 刺激、运行编排和有限 execution witness | 协议合法性的权威定义 |
| `visualization` | 从权威对象派生的只读视图 | 参与路由、仲裁或状态转移 |
| `artifacts` | 运行记录、持久化和 provenance | 决定模型行为 |

通用依赖的大致形状是：

```text
semantics
├── patterns
├── observation
├── interface
└── virtual_dut

generic facilities ──> protocols/<family>       具体标准叶包
protocols + virtual_dut ──> integrations
interface + virtual_dut ──> system
system / scenario / visualization / artifacts   执行与只读消费侧
```

`protocols/<family>` 是源码所有权的叶包，不是固定的“更低”或“更高”层。CHI 可以在一个 family 包内组合
interface transaction、network representation、transport link 和 system progress；AXI 当前主要组合 interface、
observation 与 integration。没有真实切面的协议无需建立空目录来补齐图形。

## 同一职责内的组织方式

一条尚在演化的行为优先保持为 feature vertical slice，例如 AXI4 read crossbar 的 profile、pending record、
state 和 controller 放在同一个 `read.py` 中。这样一次事务的 acquire、forward、return、retire 生命周期可以在
一处阅读。

只有出现独立复用或文件密度过高时，才按以下构件角色继续拆分：

```text
declaration/config
      ↓
pure policy
      ↓
runtime state/storage
      ↓
lifecycle/controller
      ↓
projection                 recipe（最终装配）
```

这是一组命名和拆分依据，不要求每个顶层包都建立六个同名子目录。公共提取至少需要两个真实消费者，并且
两者的 key、取得、释放、reset 和故障语义相同。容器同为 `dict`、FIFO 或 table 本身不足以证明可复用。

## Integration 的四种构件

`integrations` 内部按产物角色形成单向依赖：

```text
attachments ───────────┬──> backends ──┐
  单端口转换与接口侧状态 │   协议约束下的 │
translations ──────────┘   执行状态     ├──> recipes
  typed stage / plan fragment ──────────┘    最终装配
```

箭头表示右侧可以使用左侧；attachment/translation 不导入 backend 或 recipe，backend 不创建最终
`VirtualDut`，recipe 不重新实现事务生命周期。Protocol-bound backend 是按需角色：APB endpoint 可以直接组合
通用 VirtualDut backend；AXI ID/channel 直接塑造 controller 时才需要这一中间包。AXI4 的 address-space、read
crossbar 和 write crossbar 已按此结构放在
[`integrations/backends/amba/axi/axi4/`](integrations/backends/amba/axi/axi4/)；用户通常从
[`integrations/recipes/`](integrations/recipes/README.md) 选择成品构造入口。

## 放置新代码时的判断顺序

1. 先确定一条规则的最小判定范围：单个事实、完整接口、一个 module，还是多个连接。
2. 再确定权威状态由谁取得和释放；状态跟随该 lifecycle controller。
3. 如果必须同时理解具体协议和 VirtualDut SPI，进入 `integrations`，再区分单端口 attachment、typed
   translation、执行 backend 与装配 recipe。
4. 如果代码只读取权威对象并改变表示，进入 visualization/artifacts，不回写运行状态。
5. 只有第二个真实调用方证明不变量一致后，才把方法提到共同包。

稳定概念与设计理由见 [`docs/architecture/`](../docs/architecture/README.md)，当前完成度与已知迁移边界见
[`implementation-status.md`](../docs/architecture/implementation-status.md)。根 `protocol_model` facade 目前是
延迟加载的方向入口，只保留四个概念锚点与版本号；详细 API 从本表所列的所属包导入。
