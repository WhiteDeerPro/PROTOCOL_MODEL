# Repository working agreement

本文件只保留在仓库内工作的自动化助手必须优先看到的风险护栏。规则用于保护当前架构目标，不是不可复审的
永久约束；当规则妨碍明确目标时，应回到它保护的风险，调整适用范围，而不是增加绕行层。

## 权威入口

- 稳定概念与职责边界从 [`docs/architecture/README.md`](docs/architecture/README.md) 进入。
- 已实现能力、明确缺口与阶段边界以
  [`docs/architecture/implementation-status.md`](docs/architecture/implementation-status.md) 为准。
- 当前工作顺序只在
  [`docs/architecture/technical-route/08-roadmap.md`](docs/architecture/technical-route/08-roadmap.md) 维护；
  根 `ROADMAP.md` 只描述长期方向和依赖。
- 贡献、文档写作与 claim 规则见 [`CONTRIBUTING.md`](CONTRIBUTING.md)；测试与生产实现的边界见
  [`tests/README.md`](tests/README.md)。

## 工作范围与变更控制

- 默认只修改 `protocol_model/`、当前架构文档、对应测试，以及用户明确要求的 `showcase/` 发布材料。
- 每个工作包在动手前写明四项：目标、边界、验收条件、非目标。可以记录在任务计划、PR 或工作说明中，
  不为此制造新的长期状态文档。
- 工作中发现的事项只分为三类：
  - **阻塞依赖**：不先处理就无法满足当前验收条件；
  - **基线缺陷**：当前基线违反已经声明的合同、架构护栏或回归；
  - **相邻机会**：有价值但不是当前切片的必要条件。
- 只有阻塞依赖和基线缺陷进入当前切片；相邻机会记录到合适的状态或路线入口，不顺手实现。任一时刻只保留
  一条主要 WIP 主线，完成或明确阻塞后再切换。
- 迁移语义和可复用方法，不按旧目录批量复制。adapter 只服务明确、短期的边界；若它只是让旧工程继续驱动
  新架构，应停止扩展。已退役实现通过版本控制审计，不恢复兼容包或旧回归入口。
- 若形成“增加兼容代码 → 为兼容代码增加测试 → 因测试继续维护旧结构”的循环，回到当前工作包的验收条件，
  删除无助于新架构的扩展。

## 规则解释与文档措辞

- 避免无边界的“绝对、永远、完全、不可能”等表述；这不是对“必须”“不得”等词的机械禁用。
- 强约束说明其来源和适用范围，并在属于阶段性选择时给出重新评估条件。
- 区分“当前不实现”“职责上不属于此层”和“协议本身不允许”。本节不触发全仓词汇清扫、新增 lint 或额外
  绕行层。

## 核心架构护栏

- 区分构造依赖、规则判定作用域和表示/运输三种关系，不把它们画成一条统一的“底层到上层”阶梯。
  `InterfaceProtocol` 是完整逻辑接口内的合同作用域；`TransportLink` 只表示单向 hop 或等价 flow-control
  connection；`SystemProtocol` 组合接口、VirtualDut 和系统合同形成更大判定范围。
- transaction 首先表示完成 operation 的生命周期与 correlation；message→packet→flit 是按协议需要采用的
  可选表示链，不要求每个协议实例化全部形式。
- `semantics` 持有 scope-neutral event 与共同语义，`interface` 持有接口局部通用设施，具体标准位于
  `protocols/<family>/...`。具体协议可以依赖通用设施，通用内核不反向依赖协议族。
- 协议专用 observation/generator 跟随协议族；通用 pin/frame lowering 留在 `observation`。
  `InterfaceConnection` 表示完整接口 bundle，规范中的 Link layer、hop、lane 和 topology edge 继续使用
  `link`；不对普通英文词做无边界全局替换。
- CHI 的 TxnID/DBID/Retry/P-Credit 属于 protocol transaction/interface 合同，message/packet 与 NodeID 字段属于
  network representation，flit/L-Credit/Resource Plane/activation 属于 transport，address/home authority、
  coherence 和多节点 progress 属于 system。

## VirtualDut、SystemProtocol 与互连

- VirtualDut 首先表示具体虚拟 module；协议通过端口 attachment 绑定，不按 AXI/AHB/APB 建设备继承树。
  backend 优先保存协议无关状态与操作，attachment 负责单端口事件转换和接口侧状态；协议直接决定的跨端口
  关系可留在具名 interconnect backend 或 boundary contract。
- decode miss、只读写入等正常设备结果由 attachment 映射为协议响应，不默认视为模型自身的语义故障。
- `virtual_dut/{boundary,backend,address,attachments,fabric,recipes}` 分别承担边界、执行、地址操作、单端口转换、
  跨端口 route/owner 和最终装配。内部模块使用叶模块 import；recipe 可以组合其他职责包，反向依赖不允许；
  attachment 不导入 fabric/boundary，fabric backend 不直接创建 `VirtualDut`。
- `system/topology` 只表达弱结构图，不从星形或 N×M 外观推断 crossbar、广播或转发行为。
  `contracts` 声明系统事实，`construction` 显式 lowering，`resolution` 闭合并冻结 plan；它们不持有 VirtualDut
  私有运行状态。runtime 只执行已固定 topology，monitor 只消费事件形成 verdict，analysis 只读派生结果。
- 具名互连 module 默认是多端口 VirtualDut；只有验证目标需要观察独立 module/connection/hop 时，才展开为内部
  SystemProtocol。decoder、mux、arbiter 不因名称自动成为 topology 节点。
- 局部 decode、仲裁、owner/ID table、FIFO 与跨端口 correlation 属于 interconnect backend；全局地址归属、
  可达性、connection ownership、端到端 return 和 wait-for/deadlock 属于 SystemProtocol。
- bridge、decoder-mux、arbiter-mux、crossbar 优先由少量 Route/Transform/Store/Correlate/Arbitrate 算子组合；
  便捷声明必须展开为明确的 interconnect VirtualDut 与连接，不维护平行的隐式路由 runtime。
- 地址事实只保留一个权威来源：生成式 fabric 从 system contract 派生或核对配置；外部 RTL 的本地 decode
  作为 boundary contract 由系统校验。尚未闭合的投影必须明确记录边界，不复制第二份独立路由事实。
- 仲裁字段合法性属于 InterfaceProtocol，端口支持属于 capability，选择算法与状态属于 VirtualDut，
  最大等待、公平性、带宽和 QoS 目标属于 system/scenario property。

## 回归触发矩阵

`smoke` 是编辑循环的代表集，`target` 按职责选择受影响测试，`active` 是除具名迁移哨兵外的全部维护合同，
`full` 是仓库统一入口 `make test`。测试数量不是架构进度，但回归是变更合同；当前 full 低于三秒，不以
耗时为由跳过。

| 触发条件 | 最低验证要求 |
|---|---|
| 修改生产代码或测试 | 先跑 `make smoke` 与受影响的 `make test-target TARGET=<name>` |
| 变更跨越 protocol、attachment、backend、recipe 或 system 边界 | 增加或运行 `make test-integration`，完成前再跑 full |
| 修改包结构、facade、import 或职责归属 | 运行 `make test-target TARGET=architecture`，完成前再跑 full |
| 交付任何代码变更 | 运行 `make test`；汇报与本次判断直接相关的结果 |
| 仅修改文档 | 定向检查链接、术语和 claim；只有源或生成参数变化时才重建资产 |

- 普通测试和预览写入临时目录或调用方指定的 scratch/run root，不写入版本控制中的发布树。
- 写入 `docs/` 或 `showcase/generated/` 只能由具名生成/发布脚本显式触发，并且必须是当前工作包的授权范围。
  脚本保存可检查的 DOT、WaveJSON 等源、参数和 provenance，只替换自己拥有的子树；发布后检查 diff。
- 回归失败先判断它是当前变更、基线缺陷还是过期兼容/发布耦合，不用增加兼容层来掩盖架构问题。

## 汇报与资源提示

- 汇报先给结论、影响和未完成项；区分协议要求、架构边界、实现阶段选择与性能/复杂度取舍。
- 当工作跨越多个架构层、需要审计较多规范/代码区域或存在长距离一致性风险时，可在自然边界提醒用户考虑
  EX HIGH / ULTRA；局部机械修改可提示使用较低资源层级。
- 资源提示只是一次性建议，不宣称切换已经发生，也不暂停仍可继续的工作；除非复杂度明显变化，不重复提示。
