# Recipe catalog API

本目录提供 VirtualDut recipe 的机器可读索引。一个 `VirtualDutRecipe` 描述：

- 稳定 `id` 和可延迟加载的 `factory_path`；
- endpoint、initiator、bridge、fabric、control 或 fixture 角色；
- core/integration 构造层，以及 foundation/primary/profile/convenience 选择层级；
- operation form、协议适用范围、端口形状和必要输入；
- 可选 showcase 路径。

它描述 factory，不缓存构造后的 VirtualDut，也不保存某次 SystemProtocol 的连接或运行状态。

```python
from protocol_model.integrations.recipes.catalog import (
    get_virtual_dut_recipe,
    list_virtual_dut_recipes,
)

spec = get_virtual_dut_recipe("amba.bridge.serial")
factory = spec.load_factory()

for spec in list_virtual_dut_recipes(kind="fabric", layer="integration"):
    print(spec.title, spec.port_shape)
```

`load_factory()` 只解析 callable；factory 所需的实际协议、地址空间和 policy 仍由调用者显式提供。catalog
不尝试用反射调用不同签名，也不将“找到一个 bridge recipe”解释为两端协议已经兼容。

清单写在 `entries.py`。新增公共 recipe 时应同时补充一项描述；内部 helper 不进入清单。可以用以下命令
输出当前完整 Markdown 表：

```bash
python -m protocol_model.integrations.recipes.catalog
```
