# 协议集成与端口绑定：把线上语言翻译成模块操作

[返回架构地图](README.md) · [VirtualDut](03-virtual-dut.md) · [端到端 APB 示例](07-apb-read-walkthrough.md)

这一源码接缝收纳“同时理解具体协议与模块操作”的代码，并分成单端口翻译、可复用 typed translation、
协议约束下的模块执行和完整模块装配。InterfaceProtocol、VirtualDut 核心与 SystemProtocol 通过这些具名
构件协作，同时保持各自的事实所有权。

<a id="integration"></a>
## 1. Integration：协议与模块操作的依赖边界

Integration 是协议定义与 VirtualDut operation SPI 的依赖汇合区。接口协议包只定义 interface-local language；VirtualDut
核心只定义模块边界和行为接口；具体 attachment、protocol-bound translation/backend 和 recipe 可以同时认识
二者。

这个依赖方向让 VirtualDut 核心保持协议中立，让 InterfaceProtocol 聚焦线上合同。具体协议包向 integration
提供 family asset，recipe 再把 attachment、AddressSpace、backend 或 bridge 组合为 module。公共构造入口
沿这一方向放在 integration recipe。

本工程把依赖收口为：

```text
InterfaceProtocol definition + VirtualDut contracts
                 │
                 ├── integrations/attachments     单端口 event ↔ operation
                 ├── integrations/translations    可复用 typed lower/lift
                 └── integrations/backends        按需的协议约束 controller
                                      │
                                      ▼
                           integrations/recipes    最终装配
```

具体 attachment 可以同时依赖协议定义和 VirtualDut SPI；被多个 plan 复用的 typed lower/lift 进入
`integrations/translations`；当跨端口 controller 直接受协议 channel、ID 或 ordering 约束时，它进入
integration-owned backend；recipe 再选择这些构件。依赖从 integration 指向两侧核心。当前 APB 翻译位于
[`integrations/attachments/amba/apb/`](../../../protocol_model/integrations/attachments/amba/apb/)，
构造入口位于
[`integrations/recipes/amba/endpoints/apb.py`](../../../protocol_model/integrations/recipes/amba/endpoints/apb.py)。

## 2. 静态对象与运行状态

| 对象 | 回答的问题 | 状态归属 |
|---|---|---|
| `InterfacePort` | module 对外是哪种协议、哪种 role？ | 静态 boundary |
| `InterfaceAttachment` | event 如何转换成 operation，反向怎样编码？ | 声明初态；运行快照进入 backend state |
| `InterfaceAttachmentBinding` | 这个具体 port 装了哪个 attachment？ | 静态、不可变 |
| `InterfaceConnection` | 这个 port 在系统里连接到谁？ | 静态 topology；运行状态在 InterfaceSession |

相应的动作也不同：

```text
bind_port()  在一个 VirtualDut 内装配端口实现
connect      在 SystemProtocol 中用 InterfaceConnection 连接不同模块
```

这两个具名动作分别表达局部实现装配和全局 topology 连接。

CHI participant recipe 中的 `attach_chi_issue_h_{coherence,home}` 是一个具名 composition helper：
输入是协议中立 `CacheCore` 或 `FullLineBackingCore`，输出是第一个新的 VirtualDut assembly。如果调用方
已经构造最终 boundary，则使用 `bind_chi_issue_h_*_vdut()`，返回的 facet 引用同一个 canonical object。
未来的 immutable boundary refinement 由通用 VirtualDut construction 先定义 lineage 与 topology 注册前的
replacement 语义。

<a id="attachment"></a>
## 3. Attachment：单端口翻译器

通用 SPI 要求 attachment 声明所支持的 InterfaceProtocol、role、初始接口侧状态和 quiescent 条件。
address、stream、interrupt 等 operation family 分别提供适合自身数据形状的 typed 转换接口。

Address operation family 再派生两面接口：

```text
AddressCompleterAttachment
  request event → AddressAccess + reply context
  AccessResult  → completion event

AddressRequesterAttachment
  AddressRequest  → request event
  completion event → AddressCompletion
```

APB requester 保存唯一 pending request ID；APB completer 保存足够的 reply context，以便把 AccessResult
编码为正确的 READ_RESPONSE 或 WRITE_RESPONSE。

通用 SPI 见 [`attachments/base.py`](../../../protocol_model/virtual_dut/attachments/base.py)，地址接口见
[`attachments/address.py`](../../../protocol_model/virtual_dut/attachments/address.py)。

<a id="binding"></a>
## 4. Binding：构造期的一致性证明

`InterfaceAttachmentBinding` 在运行前检查：

- attachment 与 port 属于相同 protocol family；
- event、字段、方向和参数构成相同 interface shape；
- role 相同。

Transport shape 比较 event、字段、方向和关键参数。独立构造但配置相同的 AXI 协议因此可以兼容；
monitor lambda 的对象身份与额外语义继续由实际 InterfaceSession 处理。

Attachment-aware backend 会投影自己真正使用的 bindings。VirtualDut 构造时要求公开 binding 与 backend
使用的是同一对象，防止出现：

```text
文档/可视化宣称 attachment B
运行时 backend 实际执行 attachment A
```

实现见 [`binding/port.py`](../../../protocol_model/virtual_dut/binding/port.py) 和
[`boundary/module.py`](../../../protocol_model/virtual_dut/boundary/module.py)。

## 5. APB endpoint 的装配过程

```text
ApbCompleterAttachment(protocol)
        +
InterfacePort("apb", protocol, role="completer")
        ↓
InterfaceAttachmentBinding
        +
PassiveAddressSpaceBackend(address_space, same binding)
        ↓
VirtualDutBuilder
        ↓
VirtualDut "registers"
```

Recipe 是 composition root：它依赖端口、attachment 和 backend，并沿用各构件已经声明的运行语义。APB
recipe 见
[`integrations/recipes/amba/endpoints/apb.py`](../../../protocol_model/integrations/recipes/amba/endpoints/apb.py)。

## 6. 状态所有权

| 状态 | 所有者 |
|---|---|
| APB sole pending、AXI incomplete fragment/AW-W join、AHB phase context | attachment state，由 backend state 容纳 |
| 已 decode parent 的 opaque reply context、token 和 continuation | bridge/fabric executor envelope |
| register/memory 内容 | endpoint backend |
| route、内部 request ID、completion owner | fabric/bridge backend |
| interface transaction monitor | InterfaceSession |
| 多模块运行快照 | SystemSession |

Binding 保存静态关系；backend snapshot 唯一保存 attachment/backend 运行状态，从而支持一致的回滚和重放。

## 7. Integration 与系统构造的边界

SystemProtocol 消费 VirtualDut 的 InterfacePort 和边界投影：它连接 role、拥有 topology，SystemSession
再把 canonical event 送入目标 backend。具体 attachment 类型与 pending interface state 由 VirtualDut
realization 持有。

capability/address closure 同样消费 VirtualDut 的边界投影。当前 bridge 由显式 recipe 构造；后续
construction lowering 可由经用户授权的 `SystemProtocolBuilder` 选择 plan，并生成 bridge VirtualDut 与两条
interface connections。core elaboration 检查生成后的 topology。缺少授权 plan 时，构造阶段返回
operation/capability mismatch；runtime 始终执行已经固定的 topology。

## 8. AMBA operation families 的具体化

AHB 与 AXI memory-mapped 已有功能性 integration。它们优先复用 AddressAccess，但运输形状要求不同时
允许使用协议相关 backend：

- AHB-Lite/AHB5 non-Exclusive profile：保存 WRITE address context，等待 WRITE_DATA 后形成 AddressWrite，
  并在 bus lanes 与 narrow AddressAccess value 之间转换；
- AXI4-Lite：处理 AR/R 与 AW/W/B，尤其是 AW/W FIFO join，并复用通用 AddressSpace/fabric backend；
- AXI4：`Axi4BurstTranslationAttachment` 负责 AW/W 或 AR assembly、burst geometry 与 opaque reply
  context，产出 `AddressBurst`；`BurstToAccessStage` 再将 INCR/FIXED/WRAP burst 展开为逐 beat
  AddressAccess，由公共 executor 严格串行发行并折回对应 R 或聚合 B。通用 requester attachment 当前仍是
  serialized single-access transport profile；
- AXI4-Stream：使用独立 StreamTransfer contract，保留 keep/strobe、packet end、ID/destination。

通用 AHB AddressSpace backend 的当前准入 profile 采用 ordinary access，并要求 Exclusive signaling
关闭。HEXCL/HEXOKAY 属于 InterfaceProtocol 合同；启用它们的 endpoint 需要可观察其他写入者的 Exclusive
Access Monitor。little-endian mapping 已实现；其他 AHB endian mapping 需要独立 profile。

AXI4 AddressSpace endpoint 当前处理 normal access；exclusive descriptor 的准入要求 exclusive-aware
backend 持有 reservation 与跨入口冲突状态。AXI4-Stream capture 已有，自主 source emission 随 boundary
runtime 扩展。

跨端口的 serialize、ID remap、burst split 和 owner return 由 bridge VirtualDut 的 translation
plan/executor 统一拥有。完整设计见
[Bridge 与类型化事务转译](../typed-transaction-translation.md)。

## 9. 多端口 integration 产物

调用 AMBA recipe 得到普通 `VirtualDut`：一个 constructed backend 通过具体 AMBA attachments 实例化为
**AMBA-bound module realization**。AMBA 描述端口边界，module 身份由系统角色决定。同类行为改用 TileLink
attachment 时，recipe 构造具有相应端口合同的另一个模块实例。

Endpoint 的主要语义通常是“请求进入本地状态并形成结果”。Bridge 和 crossbar 更特殊：它们的主要语义
就是多个端口之间的关系，包括 transform、route、arbitrate、owner/correlation、capacity、ordering 和
completion return。这些跨端口事实由同一 backend 或 boundary contract 统一拥有，互连验证同时检查各
attachment 与整体生命周期。

Bridge/crossbar 仍作为普通 VirtualDut 放进 SystemProtocol：

- bridge 常见形态是 1→1，突出协议或传输形状转换；
- crossbar 常见形态是 N→M，突出路由、仲裁、并发和 owner/ID 表；
- 验证目标覆盖内部 module/interface 时，将同一逻辑展开为内部 SystemProtocol。

互连的结构化边界投影从 plan/executor 的唯一配置派生 ingress/egress、route、transfer policy、capacity
和 completion policy。bridge 与 crossbar 以具名 VirtualDut recipe 表达各自组合，类型体系保持统一的
VirtualDut module 边界。

## 10. 当前实现状态的归属

本页的稳定合同是：operation family 各自提供小型 attachment SPI，binding 保证静态一致性；protocol-bound
translation 保存可复用的 typed lower/lift 合同，backend 拥有无法放入通用 VirtualDut core 的执行生命周期；
recipe 完成最终装配。运行状态由 backend/attachment snapshot 唯一拥有。协议 profile 的覆盖进度集中记录在
状态页。

易变化内容由以下页面维护：

- [当前实现状态](../implementation-status.md)：各协议 integration、capability 和 runtime 已实现范围；
- [Bridge V1 实施状态](../translation-implementation.md)：统一 plan/executor、AMBA composition root 与剩余
  system-boundary 接入边界；
- [AMBA 协议专题](../amba-interface-families.md)：协议族的具体 profile；
- [项目 Roadmap](../../../ROADMAP.md)：signaling、外部 backend 和异步 emission 等后续方向。

下一步阅读：[Bridge 与类型化事务转译](../typed-transaction-translation.md) 或
[SystemProtocol](05-system-protocol.md)。
