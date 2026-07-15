# Repository working agreement

本文件约束在此仓库内工作的自动化助手，目的是避免旧实现、回归和文档措辞互相强化，偏离当前
架构目标。

这些约定是当前阶段的协作默认值，不是不可复审的永久规则。当一条约定开始妨碍明确的用户目标或造成明显的
使用摩擦，应先回到它原本保护的风险，调整适用范围或替换规则；不要为了维护旧文字而建立额外绕行层。

## 工作重心

- 默认只修改 `protocol_model/`、当前架构文档、对应的新测试，以及用户明确要求的 `showcase/` 发布材料。
- v0.1 实现已退出源码树；历史方法需要审计时使用版本控制，不恢复兼容包或旧回归入口。

## 迁移方式

- 迁移语义和可复用方法，不按目录批量复制旧实现。
- 每次迁移先说明目标层级：基础语义、LinkProtocol、VirtualDut、SystemProtocol、观察层或展示层。
- adapter 应服务于明确、短期的迁移边界；如果 adapter 只是让旧工程继续驱动新架构，应暂停并重新判断。
- 每次只打通一条可解释、从输入到结果的小型完整路径，记录尚未迁移的部分及原因，不用“大量已有用例通过”
  替代架构论证。

## VirtualDut 建模

- VirtualDut 首先表示具体虚拟 module；协议通过端口 attachment 绑定，不按 AXI、AHB、APB 建立设备继承树。
- 可复用 backend 优先抽取协议无关的状态和操作；协议 attachment 负责单端口 CanonicalEvent 转换和运输状态。
  bridge/crossbar 中由协议直接决定的跨端口关系可以保留在 backend 或 boundary contract，不为追求通用性
  强行拆入彼此独立的 attachment。
- decode miss、只读写入等正常设备结果由 attachment 映射为协议响应，不默认当作模型自身的语义故障。
- 优先增加少量行为核心和组合 recipe；协议绑定产生的具体设备数量不作为扩展核心类型的理由。

## VirtualDut 源码组织

- `virtual_dut/boundary` 声明 module/port 边界，`backend` 放执行契约和 constructed backend，
  `address` 放协议无关地址操作与 reference region，`attachments` 放单端口转换，`fabric` 放跨端口
  route/owner，`recipes` 负责最终装配。
- 内部模块使用叶模块 import，不从 `protocol_model.virtual_dut` 根 facade 反向导入。根 facade 面向常用
  构造入口，具体 attachment state、pending owner 等实现 DTO 从所属子包访问。
- `recipes` 可以组合各职责包；其余层不导入 recipe。attachment 不导入 fabric/boundary，fabric backend
  不直接创建 `VirtualDut`。

## Fabric、bridge 与 crossbar

- `fabric` 是组合和展示概念，不预设为新的语义层。具名互连 module 默认表示为多端口
  `VirtualDut`；只有当前验证目标需要观察内部 module/link 时，才展开成内部 `SystemProtocol`。
- Decoder、mux 和 arbiter 不因名称自动成为 topology 节点。局部组合行为放在 constructed backend；
  独立 RTL/module、观测点或需要单独验证的资源与公平性才构成独立 `VirtualDut`。
- 局部 decode、仲裁状态、owner/ID table、内部 FIFO 和跨端口 correlation 属于 interconnect backend；
  全局地址归属、可达性、link ownership、端到端 response return 和网络 wait-for/deadlock 属于
  `SystemProtocol`。
- 协议无关 operation 是优先复用方向，不是硬性边界。AXI/AHB/APB 的 channel、ID、ordering 或
  completion 关系直接影响模块行为时，允许使用协议相关 backend，并说明其适用 profile。
- Bridge、decoder-mux、arbiter-mux 和 crossbar 优先作为少量 Route、Transform、Store、Correlate、
  Arbitrate 算子的 recipe，不建立按协议或设备名称扩张的继承树。
- 便捷的 bus/fabric 系统声明应展开为明确的 interconnect `VirtualDut` 与 `ProtocolLink`，不维护一套
  与 topology 并行的隐式路由运行语义。
- 地址图避免维护两份独立事实：生成式 fabric 后续从 system route contract 派生配置；外部 RTL 的
  本地 decode 配置作为 Vdut boundary contract 由系统校验。尚未建立该闭合检查时，应明确记录局部
  route table 与 endpoint address claim 的边界。
- 仲裁相关内容按作用域放置：字段合法性属于 `LinkProtocol`，端口支持范围属于 capability，选择算法
  及状态属于 `VirtualDut`，最大等待、公平性、带宽和 QoS 目标属于 system/scenario property。

## 验证与汇报

- 验证规模与本次风险相称。默认运行新代码的定向测试，不把测试数量当作迁移进度。
- 汇报先给结论、影响和未完成项。测试结果只写与当前判断有关的摘要，避免罗列大量 case。
- 失败先判断是否暴露新架构问题；如果仅由历史文档复制、旧报告发布或兼容入口耦合造成，优先移除该耦合。

## 文档措辞

- 避免无边界的“绝对、永远、完全、不可能”等表述。
- 强约束应同时给出适用范围、当前原因，以及必要时的重新评估条件。
- 区分“当前不实现”“架构上不属于此层”和“协议本身不允许”，不要把阶段性选择写成永久事实。
- 运行目录由调用方按用途选择；未指定时 `out/` 只是临时默认，不是唯一合法位置。测试使用临时或明确的
  scratch 目录，不写入受版本控制的发布树。
- 写入 `docs/` 或 `showcase/generated/` 必须由具名生成/发布脚本显式触发。脚本应保存可检查的 DOT、WaveJSON
  等源、生成参数和 provenance，并只替换自己拥有的子树；普通运行不隐式改写宣传材料。

## 解释型文档组织

- 架构文档首先独立说明概念：对象是什么、边界在哪里、与相邻对象怎样协作；其次说明采用该设计的
  必要性、收益、抽象依据和取舍。不要把一次对话的问答顺序直接当作长期目录。
- 页面默认按“定位与术语 → 运行或构造机制 → 设计理由 → 层级边界与取舍 → 示例 → 当前实现与后续”
  组织。并非每页都需要全部章节，但概念和理由应先于状态清单。
- 疑问句适合用于导读、示例或末尾的“常见误解”，不作为整篇文档的主骨架。将“为什么不做 X”改写为
  正面说明所选边界，再在理由部分比较 X 会造成的耦合或损失。
- 稳定架构、当前实现状态和迁移计划分开书写。稳定文档不反复穿插“本轮、刚刚、下一步”；状态页记录
  已实现与未完成，roadmap 记录实施顺序。
- 一个概念指定一篇 canonical 文档。导览页和技术路线只给足以继续阅读的解释并链接 canonical 文档，
  不复制大段细节；协议专题只描述该协议对通用架构的具体化。
- 设计理由需标明性质：协议要求、架构边界、实现阶段选择、性能/复杂度取舍或可视化偏好。避免把“有
  好处”“比较方便”当作唯一论证。

## 防止正反馈失控

当工作形成“增加兼容代码 → 为兼容代码增加测试 → 因测试继续维护旧结构”的循环时，停止扩展，
回到用户当前目标，检查新增内容是否直接改善新架构。历史实现存在于版本控制中，不构成恢复它的理由。

## 资源层级提示

- 当任务开始跨越多个架构层、需要同时审计较多规范或代码区域、要求长距离一致性判断，或当前上下文已
  难以可靠覆盖关键关系时，在自然的工作边界简短提醒用户考虑启用更高资源层级，例如 EX HIGH / ULTRA，
  并说明是哪类复杂度触发了提醒。
- 当任务已经收敛为局部、机械、低风险修改，较低资源层级足以可靠完成时，可以提醒用户降级，以免让
  简单工作占用不必要的资源。
- 提示只作为建议，不宣称资源切换已经发生，也不把可以继续完成的工作无故暂停。一次任务阶段通常提示
  一次；除非复杂度发生明显变化，不重复强化同一建议。
- 不以“任务看起来困难”作为唯一依据。优先观察是否存在跨层依赖、规范歧义、上下文跨度、不可逆决策或
  大范围一致性风险，避免资源提示本身形成正反馈。
