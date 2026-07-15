# CHI link family boundary

这里预留 CHI 的 LinkProtocol 归属。规范审计后的首个建议实现范围是
`CHI Issue H RN-I basic link profile`，而不是一组无执行 monitor 的 REQ/RSP/SNP/DAT DTO。

计划中的 public API 为 `ChiIssueHConfig` 和 `build_chi_issue_h_rn_i_basic_link()`。进入代码前先补足：

- opcode/property 驱动的 conditional fields；
- 按方向、channel 和 Resource Plane 管理的 AtomicFrame link-credit epoch；
- endpoint property 的 typed capability negotiation；
- TxnID/DBID correlation 及 PCrdGrant/RetryAck/reissue ledger。

当前没有可导入的 CHI 协议实现。node identity、home/target routing、跨 link cache-line ownership 与全局
coherence progress 由更大作用域的系统语义组合。详细边界见 `docs/architecture/ace-chi-links.md`。
