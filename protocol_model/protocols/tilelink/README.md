# TileLink family 源码导航

本目录预留 TileLink 的具体协议族边界，并提供稳定 family identity。

## 当前入口

[`__init__.py`](__init__.py) 公开 `TILELINK_FAMILY`。当前阶段尚无 executable interface builder 或
observer；可执行覆盖止于 family namespace。

## Profile 范围

计划中的 conformance profile 为 `tl_ul/`、`tl_uh/` 与 `tl_c/`。首个 executable
`InterfaceProtocol` 将建立 A/D channel vocabulary、typed events、observer 和 conformance evidence，
随后再提取跨 profile 的共同设施。

## 相邻 owner

TileLink agent 由逻辑 protocol participant 表达，具名硬件 module 由 VirtualDut 表达。TL-C permission、
coherence authority 和跨 agent progress 由 participant state 与 SystemProtocol contract 组合。

TileLink 规范中的 *link* 保持 family-local 含义；通用 API 用 `InterfaceProtocol` 表示完整 role/channel
bundle，用 `InterfaceConnection` 表示一次具体 topology binding。
