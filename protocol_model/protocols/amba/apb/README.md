# APB family 源码导航

本目录保存 APB3、APB4 与 APB5 的独立 public interface profile。各 revision 公开自己的 config、normalized
signal DTO、observer 和 builder；根包公开 `APB_FAMILY`。

## 当前入口

```text
apb/
├── apb3/       Apb3Config / Apb3Signals / observer / builder
├── apb4/       APB4 API，PPROT/PSTRB 可独立配置
├── apb5/       APB5 user/wakeup/RME profile
└── _common/    私有 schema builder 与 SETUP/ACCESS phase engine
```

```python
from protocol_model.protocols.amba.apb.apb3 import build_apb3_interface
from protocol_model.protocols.amba.apb.apb4 import Apb4Config, build_apb4_interface
from protocol_model.protocols.amba.apb.apb5 import Apb5Config, build_apb5_interface
```

## Profile 范围

| Profile | 当前覆盖 |
|---|---|
| [`apb3/`](apb3/) | 基础 SETUP/ACCESS phase、wait、response 与 sampled-cycle observation |
| [`apb4/`](apb4/) | 可独立配置的 PPROT/PSTRB |
| [`apb5/`](apb5/) | PAUSER/PWUSER/PRUSER/PBUSER、sampled PWAKEUP hold、PNSE/RME |

`Apb3/4/5Signals` 是 observation 边界的 normalized sample DTO。Adapter 对省略的 optional pin 填入规范
默认值；APB4/APB5 observer 要求 config-disabled 字段为零，并要求 read transfer 的 PSTRB 为零。

APB5 当前选择 `Apb5CheckType.NONE`，对应 non-parity pin schema/observer。新的 check type 以具体 parity
pin schema、adapter 与 observation profile 为启用条件。

## 相邻 owner

`_common/` 维护 revision 共享的 phase engine。APB decoder、mux 和 peripheral selection 属于
interconnect VirtualDut；跨 module topology 与 address authority 属于 SystemProtocol。
