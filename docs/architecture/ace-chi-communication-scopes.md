# ACE 接口与 CHI 多视图建模边界

ACE 和 CHI 都属于 AMBA 标准族，但不因此成为同形、同作用域的工程对象。ACE 的当前实现自然表现为
AXI 风格 InterfaceProtocol profile；CHI 同时具有 Protocol、Network、Link 表示/运输分层，还需要
ProtocolParticipant、VirtualDut 和 SystemProtocol 承载不同范围的状态。

工程使用 `InterfaceProtocol` 表示接口局部合同。这里的接口作用域不等同于 CHI Link layer：CHI
Protocol/Network/Link 是 transaction relation、message/packet 与 flit transport 的规范分层。三张视图的
canonical 决策见[通信建模的三张视图](communication-scope-and-transport.md)。

本文解释 ACE/CHI 事实应落在哪个架构对象，不维护易变的功能矩阵。当前可导入实现和未完成项集中在
[实现状态](implementation-status.md)，CHI 源码切面见
[`protocol_model/protocols/amba/chi/README.md`](../../protocol_model/protocols/amba/chi/README.md)。

## ACE-Lite ordinary-data profile

`build_ace_lite_data_interface()` 建立原生 ACE-Lite address schema，同时复用 AXI4 已有的 burst、ID、
read interleave、AW/W FIFO join 和 B/R completion monitor。它不是 AXI4-Lite：事务仍可 multibeat，也可有
multiple outstanding IDs。

AR/AW 在 AXI4 字段之外增加：

- `domain`：2-bit AxDOMAIN；
- `snoop`：AR 为 4-bit ARSNOOP，AW 为 3-bit AWSNOOP；
- `bar`：2-bit AxBAR。

当前 profile 支持 ReadNoSnoop/ReadOnce、WriteNoSnoop/WriteUnique/WriteLineUnique 对应的编码/
domain 组合，拒绝 `AxBAR[0]=1`，并拒绝 cacheable + System domain。公开名字包含 `data`，因为
直接复用 `Axi4WriteMonitor` 会把每个 AW 都与 W burst 绑定，而 ACE barrier 的 write 部分没有 W。
要去掉这个后缀，至少需要：

1. AR/AW barrier pair monitor；
2. AW-without-W 的 B completion 路径；
3. CMO 的无 data completion 与 opcode/response 规则。

full ACE 还有 AC/CR/CD 和 RACK/WACK。AC 到 CR 的 FIFO 对应、CR 是否要求 CD、CDLAST 位置等属于
InterfaceProtocol 局部合同；哪个 request 应向哪些 cache 发 snoop、哪个节点持有最新 cache
line 则属于系统组合。

## CHI RN-I 的两个可执行边界

CHI 不只是 REQ/RSP/SNP/DAT 四个固定 schema。实施时需要区分两个都可单独运行的边界：

- **accepted-message interface**：从已经解码的 CHI message/event 开始，执行 RN-I channel profile、
  TxnID/DBID、Retry/P-Credit 和 completion correlation；
- **representation/transport slice**：检查 message→packet→flit 的 lineage，以及方向化 hop、L-Credit、
  Resource Plane 和 activation。

前者可以用于事务流例子，不必等完整 packet/flit codec；后者可以用最小 typed flit fixture 独立检查
credit epoch。当前 direct-Home read 与 sibling retry profile 已把这两个边界组合成受限纵向见证；这些 profile
固定单 Requester/Home 等条件，不据此扩张成完整 RN-I。

这两个边界分别需要：

1. **conditional field schema**：字段存在性、MBZ 与合法值由 opcode 和 interface properties 联合决定；
2. **directional shared flit schema**：RSP/DAT 格式会在两个方向复用，需要方向化 event kind 或可共享 schema；
3. **transport credit epoch**：L-Credit 按方向、channel 和 Resource Plane 管理，本周期收到的 credit
   不在同一周期被消耗；
4. **typed capability negotiation**：端点 properties 有相等条件，也有兼容矩阵；
5. **transaction/retry ledger**：Protocol Credit 与 Link Credit 不同，PCrdGrant 可先于 RetryAck，重发可换
   TxnID，但需保持其他关键字段。

Transaction 在这里是关联请求、消息、完成与状态变化的 lifecycle，不是强制包裹 message 的编码盒。当前
direct-read/retry ledger 已执行 `(Requester NodeID, TxnID)` correlation、RetryAck 与 transaction-independent
P-Credit pooling；transport session 分别执行 REQ/RSP/DAT 的 link-wide activation 与 L-Credit。family network
session 可在调用方声明的 directed topology 上执行有限 store-and-forward route；它尚未提供
NodeID/address-home authority closure 或系统缓存一致性，也不把无 monitor 的字段壳计为已实现协议。

完整 RN-I 仍可沿下列目标入口收敛：

```python
build_chi_issue_h_rn_i_basic_interface(
    ChiIssueHConfig(
        node_id_width=7,
        req_addr_width=44,
        data_width=128,
        num_req_rp=1,
        retry_support=True,
    )
)
```

它应先覆盖 RN-I 的 TXREQ/TXRSP/TXDAT 与 RXRSP/RXDAT，不含 SNP，并使用 interface protocol ledger 表达
TxnID/DBID 与 Retry/P-Credit。representation codec 和 transport monitor 是与该入口组合的独立对象，负责
message/packet/flit 与 L-Credit；这里是后续目标入口。当前源码公开的是较小的 direct ledger、participant、
REQ/RSP/DAT transport session 和受限 retry composite session，便于分别验证职责边界。

## 三张视图中的 CHI 事实

| 项目作用域或 view | ACE/CHI 中放在这里的信息 |
|---|---|
| interface-local 判定作用域 | 当前 InterfaceProtocol 可执行接口局部 schema/correlation；作用域局部不决定对象属于 CHI 的哪一规范层 |
| CHI protocol contract | transaction/message flow、TxnID/DBID、P-Credit 与 Retry lifecycle |
| network representation | message→packet、SrcID/TgtID 与 packet form；NodeID authority 由 SystemProtocol 闭合 |
| VirtualDut backend | 节点内部 cache/tag/data、真实 Home/Directory，以及 RN/HN/ICN 实际使用的 SAM、remap 和局部 route state |
| SystemProtocol / system monitor | NodeID 与 address/home 的权威分配、snoop fanout、owner/shared/dirty、response aggregation、全局 ordering/progress |
| transport contract / derived network execution view | packet→flit、方向化 TransportLink、L-Credit/link activation；显式观察 NoC 内部时，从同一 SystemProtocol topology 派生 router、Resource Plane 与 dependency 的执行/分析视图 |

一个 interface-local monitor 可以检查 response 的编码与关联，但要判定“这个 cache 确实持有所声称的 line”，
还需要 VirtualDut backend 或外部 DUT oracle。要判定多个节点之间的 owner/visibility，则需要 SystemProtocol。
NodeID/address-home 的全局分配由 SystemProtocol 声明，SAM/remap 的真实实现可位于 RN、HN 或 interconnect
VirtualDut；两者通过 typed projection 做闭合检查。

## 规范依据

- [Arm AMBA AXI and ACE Protocol Specification, IHI 0022H](https://developer.arm.com/documentation/ihi0022/latest)；
- [Arm AMBA CHI Architecture Specification, Issue H](https://developer.arm.com/documentation/ihi0050/h)；
- [Arm AMBA CHI Issue H Errata](https://developer.arm.com/documentation/aes111415/latest)。
