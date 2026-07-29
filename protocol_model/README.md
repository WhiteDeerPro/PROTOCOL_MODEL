# `protocol_model` 源码导航

本目录实现从单接口合同、虚拟 module 到通信网络的可组合模型。源码组织使用两条轴：

1. 顶层包确定一项事实的解释权、存储位置和判定范围；
2. 同一职责内按声明、策略、运行状态、生命周期控制、投影和最终装配组织构件。

这两条轴形成组合关系：`semantics` 提供共同语言，具体协议族按标准需要具体化接口、表示、运输和系统规则，
`VirtualDut` 保存 module 局部状态，`SystemProtocol` 闭合跨连接事实。各对象通过明确的合同协作。

## 顶层职责

| 包 | 接收或解释 | 产出与权威职责 | 相邻交接 |
|---|---|---|---|
| `semantics` | 通信中的共同概念 | scope-neutral event schema、fault、resource 和共同值对象 | 为其余各包提供共同语言 |
| `patterns` | event 与协议关系声明 | 可复用关系、约束构件和 monitor 状态 | 由 interface 与具体协议组合 |
| `observation` | pin、frame 和 cycle sample | event candidate 及通用 lowering 结果 | 交给具体协议解释和 session 接纳 |
| `interface` | 一个完整逻辑接口内的 event | 合同、局部约束和可执行 session | 供具体协议具体化，并由 system 绑定连接 |
| `protocols` | 通用语义、接口和观察设施 | AXI、AHB、CHI 等标准族的具体切面 | 向 integrations 提供协议对象和 typed fact |
| `virtual_dut` | 协议中立 operation 与 module 配置 | 具名 module 边界、局部 backend 状态和执行结果 | 通过 attachment 接入协议，通过 ports 接入 system |
| `integrations` | 具体协议对象与 VirtualDut SPI | attachment、translation、protocol-bound backend 和 recipe | 交付可装配的 module 与显式转换计划 |
| `system` | module、完整接口连接和系统合同 | topology、resolution plan、runtime、monitor 与 analysis | 向 scenario 暴露可运行系统，向视图层提供只读结果 |
| `scenario` | 刺激、已装配系统和运行策略 | 运行编排与有限 execution witness | 将事件和结果交给 artifacts/visualization |
| `visualization` | 权威对象及其派生结果 | 只读图、表和时序视图 | 面向读者呈现模型状态 |
| `artifacts` | 运行记录与发布输入 | 持久化结果、provenance 和可审计资产 | 交付复现、比较和发布流程 |

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

`protocols/<family>` 位于通用设施依赖的叶端，其切面由标准本身和已支持场景决定。CHI 在一个 family 包内组合
interface transaction、network representation、transport link 和 system progress；AXI 当前主要组合 interface、
observation 与 integration。每个 family 目录呈现已经具备合同或实现的切面。

## 同一职责内的组织方式

一条尚在演化的行为优先保持为 feature vertical slice，例如 AXI4 read crossbar 的 profile、pending record、
state 和 controller 放在同一个 `read.py` 中。这样一次事务的 acquire、forward、return、retire 生命周期可以在
一处阅读。

出现独立复用或文件密度过高时，再按以下构件角色继续拆分：

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

这组角色用于指导命名和拆分；各顶层包按实际构件选用。公共提取以至少两个真实消费者为前提，并核对两者的
key、取得、释放、reset 和故障语义。相同的 `dict`、FIFO 或 table 形态提供实现线索，共同生命周期和故障语义
才构成复用依据。

## Integration 的四种构件

`integrations` 内部按产物角色形成单向依赖：

```text
attachments ───────────┬──> backends ──┐
  单端口转换与接口侧状态 │   协议约束下的 │
translations ──────────┘   执行状态     ├──> recipes
  typed stage / plan fragment ──────────┘    最终装配
```

箭头从被使用的构件指向使用者。attachment/translation 形成单端口转换和 typed plan fragment，backend 消费
这些输入并持有协议约束下的执行状态，recipe 组合前三类构件并创建最终 `VirtualDut`。事务生命周期由对应的
attachment 或 backend controller 统一管理。Protocol-bound backend 是按需角色：APB endpoint 可以直接组合
通用 VirtualDut backend；AXI ID/channel 直接塑造 controller 时使用这一中间包。AXI4 的 address-space、read
crossbar 和 write crossbar 已按此结构放在
[`integrations/backends/amba/axi/axi4/`](integrations/backends/amba/axi/axi4/)；用户通常从
[`integrations/recipes/`](integrations/recipes/README.md) 选择成品构造入口。

## 放置新代码时的判断顺序

1. 先确定一条规则的最小判定范围：单个事实、完整接口、一个 module，还是多个连接。
2. 再确定权威状态由谁取得和释放；状态跟随该 lifecycle controller。
3. 如果必须同时理解具体协议和 VirtualDut SPI，进入 `integrations`，再区分单端口 attachment、typed
   translation、执行 backend 与装配 recipe。
4. 如果代码只读取权威对象并改变表示，进入 visualization/artifacts，并保持对运行状态的只读访问。
5. 第二个真实调用方证明不变量一致后，再把方法提到共同包。

稳定概念与设计理由见 [`docs/architecture/`](../docs/architecture/README.md)，当前完成度与已知迁移边界见
[`implementation-status.md`](../docs/architecture/implementation-status.md)。根 `protocol_model` facade 目前是
延迟加载的方向入口，只保留四个概念锚点与版本号；详细 API 从本表所列的所属包导入。
