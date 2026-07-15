# 协议集成与端口绑定：把线上语言翻译成模块操作

[返回架构地图](README.md) · [VirtualDut](03-virtual-dut.md) · [端到端 APB 示例](07-apb-read-walkthrough.md)

这一源码接缝专门收纳“既必须理解某个协议，又必须理解某类模块操作”的代码。它不是新增的协议语义层；
关键是把单端口翻译和完整模块装配分开，并避免耦合扩散到 LinkProtocol、VirtualDut 核心或
SystemProtocol。

<a id="integration"></a>
## 1. Integration：协议与模块操作的依赖边界

Integration 是协议定义与 VirtualDut operation SPI 的依赖汇合区。协议包只定义 link language；VirtualDut
核心只定义模块边界和行为接口；具体 attachment/recipe 可以同时认识二者。

这个依赖方向使新增协议不要求 VirtualDut 核心维护协议名单，也使 LinkProtocol 不必认识 AddressSpace、
backend 或 bridge 等模块构造对象。把 `attach(vdut)` 直接放进 APB 定义会反转这条依赖，因此不作为公共
构造入口。

本工程把依赖收口为：

```text
LinkProtocol / APB definition ─────┐
                                   ├─ integrations/attachments/amba/apb
VirtualDut attachment SPI ─────────┘
                                             │
                                             ▼
                              integrations/recipes/amba
```

具体 attachment 可以同时依赖协议定义和 VirtualDut SPI，recipe 再依赖 attachment 与 backend；两侧核心
不反向导入集成实现。当前 APB 翻译位于
[`integrations/attachments/amba/apb/`](../../../protocol_model/integrations/attachments/amba/apb/)，
构造入口位于
[`integrations/recipes/amba/endpoints/apb.py`](../../../protocol_model/integrations/recipes/amba/endpoints/apb.py)。

## 2. 静态对象与运行状态

| 对象 | 回答的问题 | 是否保存动态状态 |
|---|---|---|
| `ProtocolPort` | module 对外是哪种协议、哪种 role？ | 否 |
| `ProtocolAttachment` | event 如何转换成 operation，反向怎样编码？ | 声明初态；实际状态由 backend state 持有 |
| `PortAttachmentBinding` | 这个具体 port 装了哪个 attachment？ | 否，静态不可变 |
| `ProtocolLink` | 这个 port 在系统里连接到谁？ | 静态 topology；运行状态在 LinkSession |

相应的动作也不同：

```text
bind_port()  在一个 VirtualDut 内装配端口实现
connect      在 SystemProtocol 中用 ProtocolLink 连接不同模块
```

使用同一个 `attach` 动词表示两者，会把局部实现和全局 topology 混在一起。

<a id="attachment"></a>
## 3. Attachment：单端口翻译器

通用 SPI 只要求 attachment 声明所支持的 LinkProtocol、role、初始运输状态和 quiescent 条件。它没有
强行规定一个万能 `decode()`，因为 address、stream、interrupt 的 operation 类型并不相同。

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

`PortAttachmentBinding` 在运行前检查：

- attachment 与 port 属于相同 protocol family；
- event、字段、方向和参数构成相同 transport shape；
- role 相同。

Transport shape 不比较 monitor 内 lambda 的对象身份，因此独立构造但配置相同的 AXI 协议仍可兼容；
它也不宣称两份语义 profile 完全相等，额外语义继续由实际 LinkSession 检查。

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
ProtocolPort("apb", protocol, role="completer")
        ↓
PortAttachmentBinding
        +
PassiveAddressSpaceBackend(address_space, same binding)
        ↓
VirtualDutBuilder
        ↓
VirtualDut "registers"
```

Recipe 是 composition root：它有权依赖端口、attachment 和 backend，但不重新定义它们的运行语义。APB
recipe 见
[`integrations/recipes/amba/endpoints/apb.py`](../../../protocol_model/integrations/recipes/amba/endpoints/apb.py)。

## 6. 状态所有权

| 状态 | 所有者 |
|---|---|
| APB sole pending、AXI incomplete fragment/AW-W join、AHB phase context | attachment state，由 backend state 容纳 |
| 已 decode parent 的 opaque reply context、token 和 continuation | bridge/fabric executor envelope |
| register/memory 内容 | endpoint backend |
| route、内部 request ID、completion owner | fabric/bridge backend |
| link transaction monitor | LinkSession |
| 多模块运行快照 | SystemSession |

Binding 只保存静态关系。若它也保存运行状态，就会与 backend snapshot 形成两个真相，破坏回滚和重放。

## 7. Integration 与系统构造的边界

SystemProtocol 只消费 VirtualDut 的 ProtocolPort 和边界投影：它连接 role、拥有 topology，SystemSession
再把 canonical event 送入目标 backend。SystemProtocol 不识别 `ApbCompleterAttachment` 类，也不查看
pending transport state。

未来 capability/address closure 也应消费 VirtualDut 的边界投影，而不是反射 attachment/backend 私有对象。
当前使用显式 bridge recipe；目标 construction lowering（V1/T8 后）再允许经用户授权的
`SystemProtocolBuilder` 选择 plan，并生成 bridge VirtualDut 与两条 links。core SystemProtocol elaboration
只检查生成后的 topology。若没有被授权的 plan，构造阶段报告 operation/capability mismatch，不在运行期
静默插入 adapter。

## 8. AMBA operation families 的具体化

AHB 与 AXI memory-mapped 已有功能性 integration。它们优先复用 AddressAccess，但运输形状要求不同时
允许使用协议相关 backend：

- AHB-Lite/AHB5 non-Exclusive profile：保存 WRITE address context，等待 WRITE_DATA 后形成 AddressWrite，
  并在 bus lanes 与 narrow AddressAccess value 之间转换；
- AXI4-Lite：处理 AR/R 与 AW/W/B，尤其是 AW/W FIFO join，并复用通用 AddressSpace/fabric backend；
- AXI4：当前 subordinate 将 INCR/FIXED/WRAP burst 展开成逐 beat AddressAccess，再形成对应数量的 R 或
  聚合 B；V1 公共 plan/executor 已能保存 operation 与 opaque reply context，下一段迁移会让 attachment
  产出 `AddressBurst`，再由 typed stage 展开为 AddressAccess。通用 manager attachment 当前是 aligned
  single-beat、单 outstanding profile；
- AXI4-Stream：使用独立 StreamTransfer contract，保留 keep/strobe、packet end、ID/destination，不进入
  AddressAccess。

通用 AHB AddressSpace backend 当前显式拒绝配置了 Exclusive signaling 的 AHB5 link。原因不是 LinkProtocol
不能携带 HEXCL/HEXOKAY，而是普通 AddressSpace 没有可观察其他写入者的 Exclusive Access Monitor。
little-endian mapping 已实现；其他 AHB endian mapping 需要独立 profile。

AXI4 AddressSpace endpoint 当前处理 normal access，并明确拒绝 exclusive descriptor；reservation 与跨入口
冲突仍需 exclusive-aware backend。AXI4-Stream capture 已有，accept 触发之外的自主 source emission 仍等待
runtime 扩展。

跨端口的 serialize、ID remap、burst split 和 owner return 属于 bridge VirtualDut 的 translation plan/
executor，不拆到互相看不到的两个单端口 attachment 中。完整设计见
[Bridge 与类型化事务转译](../typed-transaction-translation.md)。

## 9. 多端口 integration 产物

调用 AMBA recipe 得到的仍是普通 `VirtualDut`。更准确的说法是：一个 constructed backend 通过具体 AMBA
attachments 实例化为 **AMBA-bound module realization**。AMBA 描述其端口边界，不成为 VirtualDut 的父类
或永久设备身份；若同类行为改用 TileLink attachment，应构造另一个模块实例，而不是把既有对象变形。

Endpoint 的主要语义通常是“请求进入本地状态并形成结果”。Bridge 和 crossbar 更特殊：它们的主要语义
就是多个端口之间的关系，包括 transform、route、arbitrate、owner/correlation、capacity、ordering 和
completion return。因此逐个 attachment 正确，并不足以推出整个互连模块正确；这些跨端口事实必须由同一
backend 或 boundary contract 统一拥有。

Bridge/crossbar 仍作为普通 VirtualDut 放进 SystemProtocol：

- bridge 常见形态是 1→1，突出协议或传输形状转换；
- crossbar 常见形态是 N→M，突出路由、仲裁、并发和 owner/ID 表；
- 当验证目标需要观察其内部 module/link 时，才把同一逻辑展开为内部 SystemProtocol。

互连的结构化边界投影应从 plan/executor 的唯一配置派生 ingress/egress、route、transfer policy、capacity
和 completion policy，不另建一份可独立修改的重复 route contract。它也不要求建立
`BridgeDut`/`CrossbarDut` 继承树。

## 10. 当前实现状态的归属

本页的稳定合同是：operation family 各自提供小型 attachment SPI，binding 保证静态一致性，recipe 完成
依赖汇合，运行状态由 backend/attachment snapshot 唯一拥有。它不需要随着每个协议 profile 的覆盖进度
反复改写。

易变化内容由以下页面维护：

- [当前迁移状态](../migration-status.md)：各协议 integration、capability 和 runtime 已实现范围；
- [Bridge V1 实施计划](../translation-v1-plan.md)：pair backend 向 typed plan/executor 的迁移；
- [AMBA 协议专题](../amba-link-families.md)：协议族的具体 profile；
- [项目 Roadmap](../../../ROADMAP.md)：signaling、外部 backend 和异步 emission 等后续方向。

下一步阅读：[Bridge 与类型化事务转译](../typed-transaction-translation.md) 或
[SystemProtocol](05-system-protocol.md)。
