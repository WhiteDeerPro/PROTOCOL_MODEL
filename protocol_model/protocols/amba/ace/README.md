# ACE family 源码导航

本目录保存 ACE/ACE-Lite 的 interface-local 合同。当前可执行 profile 在 AXI4 五个 channel、burst、ID、
outstanding 和 response ordering 上加入 AR/AW 的 `domain`、`snoop` 与 `bar` 字段。

## 当前入口

[`ace_lite/`](ace_lite/) 公开 `AceLiteDataConfig`、`AceLiteDataObservationSession` 和
`build_ace_lite_data_interface()`。API 名称中的 `data` 表示 ordinary-data profile。

## Profile 范围

| 字段 | 当前接纳范围 |
|---|---|
| ARSNOOP / ARDOMAIN | `ARSNOOP=0`；Non-shareable/System domain 表示 ReadNoSnoop，Inner/Outer Shareable domain 表示 ReadOnce |
| AWSNOOP / AWDOMAIN | `AWSNOOP=0` 表示 WriteNoSnoop 或 WriteUnique；`AWSNOOP=1` 在 shareable domain 表示 WriteLineUnique |
| AxBAR | `AxBAR[0]=0` |
| AxCACHE / AxDOMAIN | cacheable encoding 使用 `AxDOMAIN∈{00,01,10}`；System domain `11` 与 non-cacheable encoding 配对 |

AxBAR 与 cacheable-domain 两项是当前 admission 的真实协议限制。Barrier transaction、cache-maintenance
operation、AC/CR/CD 和 RACK/WACK 在相应 executable profile 建立后进入公开接口。

## 相邻 owner

AW-without-W barrier completion、AR/AW barrier pair 与完整 ACE channel correlation 属于 interface
contract。Snoop fanout、cache-line ownership、response aggregation 和跨 interface barrier visibility
由 SystemProtocol/coherence composition 闭合。
