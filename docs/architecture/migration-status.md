# 新架构当前状态

这份状态表只描述 `protocol_model/`。v0.1 实现已经完成方法审计并退出源码树；“尚未实现”表示需要按
当前层级重新设计，不表示应从旧目录复制。

## 已进入主线

| 层级 | 当前能力 |
|---|---|
| 基础语义 | typed canonical event、value domain、constraint/resource/obligation、CausalGraph、可组合 fragment |
| observation | `AtomicFrame`、ready-valid lowering、stall stability、reset epoch、quiet tied/stable policy |
| LinkProtocol | channel role/direction、schema validation、profile refinement、event prohibition、bounded resource profile |
| 通用 pattern | keyed cardinality、burst assembly、FIFO join、completion ledger |
| AXI4 | 五通道、burst/narrow/unaligned、read interleave、AW/W/B、exclusive、ordering 边界、状态驱动生成 |
| AXI4-Lite | 原生五通道 schema、单 beat/in-order、多 outstanding、AXI4 embedding、ready-valid observation |
| AXI4-Stream | 单 T channel、byte qualifier、packet/interleave/order、Continuous_Packets profile、生成与 observation |
| AHB | AHB-Lite transaction/pipeline observer；AHB5 extended HPROT、secure、sparse strobe、exclusive signaling、User payload |
| APB3/APB4/APB5 | 独立 variant package、single outstanding、SETUP/ACCESS observation；APB5 user/wakeup/RME profile |
| ACE-Lite data | AXI4 五通道语义加 ACE-Lite domain/snoop/bar 组合检查；不含 barrier/CMO |
| VirtualDut | 具名 module、typed ProtocolPort、attachment SPI/binding/builder、APB/AHB/AXI AddressSpace endpoint、Stream capture、单入口 AddressFabric 与首批 bridge witnesses |
| SystemProtocol | topology、ownership、elaboration、同步 fixed-point 路由、系统 trace、递归封装 |
| 产物与展示 | run store、manifest、记录投影、renderer/publisher、系统 topology/trace DOT |

## 当前边界

| 能力 | 状态与下一落点 |
|---|---|
| raw RTL pin adapter | `AtomicFrame` 边界已建立；AXI 字段采集、VCD/UVM transaction adapter 后续位于协议 observation adapter |
| AXI WaveJSON | 通用显示 policy 已有；各 AXI variant 的 lane/field 投影应留在对应 link 子包 |
| bounded capacity | LinkProfile 能拒绝并回滚超限事件；translation runtime 已有 typed pool/lease、usage 与 `ResourceDecl` 投影；attachment admission 向 READY/backpressure 的闭合尚未实现 |
| wait-for/deadlock | 需要 blocked reason、动态资源和非立即 emission 后再进入 SystemProtocol 分析 |
| AXI bridge | AXI4-Lite→APB 同宽、单活动 profile，以及 AXI4→APB 有界 parent FIFO、逐 beat burst split、地址重映射和错误回传已实现；width conversion、narrow beat 转换、有限 ID pool 和并发 APB 执行尚未实现 |
| typed transaction translation | signature/profile、unary/fanout stage、双向 plan closure、fan-out ledger、capacity pool/lease 与 operation-level serial executor 已落地；attachment-aware 事务式 codec 外壳、`AddressBurst` stages 和现有 AXI bridge 迁移待完成，blocked/deferred demand 属于后续 runtime 阶段 |
| 异步 DUT emission | 当前暂缓；同步 fixed-point 用于点到点和微小 bridge 网络 |
| protocol attachment | APB/AHB/AXI4-Lite address 两面已实现；AXI4 有 burst-aware subordinate 与 serialized requester；AXI4-Stream 有独立 StreamTransfer 两面 |
| empty endpoint | APB/AHB/AXI idle source 与 blackhole sink 已可构造；请求—响应 blackhole 会保留 pending，正常 error responder 尚未实现 |
| external backend | VirtualDut 的外部性已经确立；opaque/RPC/RTL/trace backend binding 和不可枚举 state ownership 尚未进入代码 |
| constructed backend | 单入口 AddressFabric 已执行 Route/Correlate；operation-level serial translation executor 已实现，但还不是 attachment-aware `VirtualDutModel`；当前 full-AXI pair backend 仍负责具体 bridge 调度；Stream capture 可保存规范化 beat；通用 Arbitrate/Compose 尚未实现 |
| boundary runtime/嵌套执行 | 可以封装 subsystem；外部边界注入与内部 session 生命周期仍需统一 |
| ordering | 单 link 的 beat、same-ID、AW/W/B 与同帧可见性可判定；内存可见性和跨 link ordering 尚未建模 |
| requirement catalog | 协议语义已有声明；官方章节、执行 monitor 和覆盖状态的逐条目录仍待建立 |

## 协议策略

- AXI4 继续作为 memory-mapped LinkProtocol 的主要推进对象，优先补 requirement catalog、optional fields 和
  协议本地可视化；AXI4-Lite 已作为原生 schema variant 落地。
- AXI4-Stream 是独立 LinkProtocol；后续 width conversion/packing 属于 stream bridge VirtualDut，不放进
  AXI4 memory-mapped 的继承链。
- APB3/APB4/APB5 由私有 SETUP/ACCESS phase engine 构造，对外暴露独立版本 API。APB4 的
  PPROT/PSTRB 相互独立；APB5 已有 user/wakeup/RME，parity 在当前 profile 中关闭。
- AHB-Lite 是共享 transaction core；AHB5 已派生 Issue C interface properties。多-manager arbitration、
  decoder/response mux、exclusive conflict monitor 和 AHB→APB 转换由 interconnect/memory/bridge VirtualDut
  或 SystemProtocol 组合。
- 当前 ACE-Lite 入口明确命名为 `build_ace_lite_data_link()`；barrier、CMO 和 full ACE snoop
  channel 需要专用 monitor 后再扩大公开名称范围。
- CHI Issue H 已完成 Link/System 边界审计。第一个最小可执行代码路径等待 conditional field、credit-frame
  语义、typed capability negotiation 和 retry ledger，然后以 RN-I basic profile 进入。
- 协议定义不拥有 `attach(vdut)`。VirtualDut 定义 attachment SPI 和本地 binding，具体 AMBA 转换位于
  `protocol_model.integrations.attachments.amba`；对应模块构造位于
  `protocol_model.integrations.recipes.amba`，SystemProtocol 只连接 `ProtocolPort`。
- ready-valid 是 observation encoding；需要一个点到点数据协议时，由具体 EventSchema 和
  ChannelProtocol 组合，不恢复旧的顶层 ready-valid 包。
- `protocol_model.link.tilelink` 已建立家族命名空间，但尚无具体 builder/observer。未来 TL-UL/TL-UH/TL-C
  用于检验 multibeat、source/sink ID、denied/corrupt 和 coherence 作用域。

## 文档与运行产物

- 稳定概念和层级边界维护在 `docs/architecture/`，入口是
  [架构说明索引](README.md)。
- [技术路线](technical-route/README.md)按一次通信经过各层的顺序解释概念，不单独维护第二套定义。
- 本页维护当前实现状态；[根路线图](../../ROADMAP.md)维护长期能力方向，具体施工边界放在对应实施案中。
- 一次运行的 trace、图和报告进入调用方选择的 run root；省略路径时仍可使用临时默认 `out/`。
- 从 protocol record 生成的临时参考文档进入 scratch 或临时目录，不固定依赖仓库内的 `out/doc-build/`。
- 长期示例需要由具名脚本显式发布到 `docs/examples/` 或 `showcase/generated/`；普通测试不写入发布树。
- 历史实现和旧 gallery 不保存在当前文档树；必要时从版本控制审计。
