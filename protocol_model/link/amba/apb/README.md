# APB revision packages

APB3、APB4 和 APB5 是独立的 public LinkProtocol package，不通过公开 `revision` 开关建立一个
superset protocol：

```text
apb/
├── apb3/       Apb3Config / Apb3Signals / observer / builder
├── apb4/       APB4 API，PPROT/PSTRB 可独立配置
├── apb5/       APB5 user/wakeup/RME profile
└── _common/    私有 schema builder 与 SETUP/ACCESS phase engine
```

`apb` 根包只导出 `APB_FAMILY`。常用入口为：

```python
from protocol_model.link.amba.apb.apb3 import build_apb3_link
from protocol_model.link.amba.apb.apb4 import Apb4Config, build_apb4_link
from protocol_model.link.amba.apb.apb5 import Apb5Config, build_apb5_link
```

`Apb3/4/5Signals` 是 observation 边界的 normalized sample DTO。当可选 pin 不存在时，adapter 需要
填入规范默认值；对 APB4/APB5 中按 config 关闭的字段，observer 要求对应 normalized
值为零。

APB5 当前执行 PAUSER/PWUSER/PRUSER/PBUSER、PNSE/RME 和 sampled PWAKEUP hold。
`Apb5CheckType.NONE` 表明当前不建立 parity pin 的 schema/observer；后续 parity 应作为具体
observation profile 扩展。
