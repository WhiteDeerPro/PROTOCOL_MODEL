# ACE link family

本目录收纳 ACE/ACE-Lite 中可由一条接口观察和判定的语义。当前可执行实现是
`ace_lite_data`：它保留 AXI4 的五个 channel、burst、ID、outstanding 和 response ordering，并在
AR/AW 上加入 ACE-Lite 的 `domain`、`snoop`、`bar` 字段。

这个 profile 只接收普通数据事务：

- ARSNOOP=0，根据 ARDOMAIN 表示 ReadNoSnoop 或 ReadOnce；
- AWSNOOP=0/1，根据 AWDOMAIN 表示 WriteNoSnoop、WriteUnique 或 WriteLineUnique；
- AxBAR[0] 必须为 0，因此当前不接收 barrier transaction；
- cacheable transaction 不使用 System domain。

公开 API 特意命名为 `build_ace_lite_data_link()`，而不是 `build_ace_lite_link()`。完整 ACE-Lite 还需要
AW-without-W barrier completion、AR/AW barrier pair 和 cache-maintenance operation；直接复用现有
AXI4 write monitor 无法表达这些行为。

完整 ACE 的 AC/CR/CD、RACK/WACK 属于后续 LinkProtocol 实现范围。snoop fanout、cache-line owner、多个
response 的聚合以及跨 link barrier visibility 属于 SystemProtocol/coherence 组合语义。
