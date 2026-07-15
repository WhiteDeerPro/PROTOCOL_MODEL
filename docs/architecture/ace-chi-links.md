# ACE 与 CHI 的 LinkProtocol 边界

ACE 和 CHI 常被与 AXI/AHB/APB 并列为 AMBA 协议，但它们的“一条线上怎么通信”与“整个系统
是否保持一致”需要分开建模。本工程先建立可由单个 port/link 判定的部分，再由
SystemProtocol 组合跨 link 事实。

## 当前实现表

| 名称 | 代码状态 | 它能声明什么 | 它尚未声明什么 |
|---|---|---|---|
| ACE-Lite ordinary-data profile | 可执行 | AXI4 五通道事务，AR/AW 的 domain/snoop/bar 字段及当前允许组合 | barrier、CMO、完整 ACE-Lite |
| full ACE | 已审计边界 | 后续 AC/CR/CD、RACK/WACK 的单接口关系 | 当前没有 `build_ace_link()` |
| CHI Issue H | 已审计边界 | 后续 flit、link credit、TxnID/DBID 与 retry | 当前没有可执行 CHI builder |

## ACE-Lite ordinary-data profile

`build_ace_lite_data_link()` 建立原生 ACE-Lite address schema，同时复用 AXI4 已有的 burst、ID、
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
LinkProtocol；哪个 request 应向哪些 cache 发 snoop、哪个节点持有最新 cache line 则属于系统组合。

## CHI executable profile 的前置契约

CHI 不只是 REQ/RSP/SNP/DAT 四个固定 schema。一个可执行的 basic profile 需要先解决下列前置：

1. **conditional field schema**：字段存在性、MBZ 与合法值由 opcode 和 interface properties 联合决定；
2. **directional shared flit schema**：RSP/DAT 格式会在两个方向复用，需要方向化 event kind 或可共享 schema；
3. **AtomicFrame credit epoch**：link credit 按方向、channel 和 Resource Plane 管理，本周期收到的 credit
   不在同一周期被消耗；
4. **typed capability negotiation**：端点 properties 有相等条件，也有兼容矩阵；
5. **transaction/retry ledger**：Protocol Credit 与 Link Credit 不同，PCrdGrant 可先于 RetryAck，重发可换
   TxnID，但需保持其他关键字段。

只有 schema、credit epoch、capability 和 retry ledger 同时闭合后，一组 flit DTO 才构成可执行
LinkProtocol profile。当前 `chi/` 因此只保存包边界和审计结论，不把无 monitor 的字段壳计为已实现协议。
建议的首个可执行入口是：

```python
build_chi_issue_h_rn_i_basic_link(
    ChiIssueHConfig(
        node_id_width=7,
        req_addr_width=44,
        data_width=128,
        num_req_rp=1,
        retry_support=True,
    )
)
```

它应先覆盖 RN-I 的 TXREQ/TXRSP/TXDAT 与 RXRSP/RXDAT，不含 SNP，并用三个专用 monitor 表达
Link Credit、TxnID/DBID correlation 和 Retry lifecycle。

## 三个层级的事实

| 层级 | ACE/CHI 中放在这里的信息 |
|---|---|
| LinkProtocol | 线上字段、opcode、credit/retry、单接口 transaction correlation |
| VirtualDut backend | 节点内部 cache/tag/data 状态，以及这些状态是否支持它声称的 snoop response |
| SystemProtocol | NodeID/SAM/实际路由、snoop fanout、owner/shared/dirty、response aggregation、全局 ordering/progress |

一条 link monitor 可以检查 response 的编码与关联，但要判定“这个 cache 确实持有所声称的 line”，
还需要 VirtualDut backend 或外部 DUT oracle。要判定多个节点之间的 owner/visibility，则需要 SystemProtocol。

## 规范依据

- [Arm AMBA AXI and ACE Protocol Specification, IHI 0022H](https://developer.arm.com/documentation/ihi0022/latest)；
- [Arm AMBA CHI Architecture Specification, Issue H](https://developer.arm.com/documentation/ihi0050/h)；
- [Arm AMBA CHI Issue H Errata](https://developer.arm.com/documentation/aes111415/latest)。
