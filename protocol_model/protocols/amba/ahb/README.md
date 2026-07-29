# AHB family 源码导航

本目录保存 AHB 的 interface-local transaction、property 与 sampled-cycle observation 合同。

## 当前入口

| Profile | Public entry | 当前覆盖 |
|---|---|---|
| [`ahb_lite/`](ahb_lite/) | `AhbLiteConfig`、`build_ahb_lite_interface()`、`AhbObservationSession` | single-Manager address/data pipeline、burst、write-data relation 与 in-order completion |
| [`ahb5/`](ahb5/) | `Ahb5Config`、`build_ahb5_interface()` | 从 AHB-Lite transaction core 派生 extended HPROT、security、sparse-write strobe、Exclusive 与 User property |

## Profile 范围

`Ahb5Config` 允许各项 interface property 独立选择。当前 canonical builder 以 transaction payload 为边界；
AHB5 parity 保持为待建立的 raw-pin observation profile，启用 parity 的 gate 是 check-signal schema、sample
adapter 与 observer 合同。

## 相邻 owner

Decoder/multiplexor 和 multi-Manager arbitration 由 interconnect VirtualDut 保存局部 route、owner 与
arbiter state；跨连接 topology、authority 和 progress 由 SystemProtocol 闭合。
