# Recipe catalog API

## 定位

本目录提供 VirtualDut recipe 的机器可读索引。`VirtualDutRecipe` 是不可变 factory 描述，包含：

- 稳定 `id` 和可延迟加载的 `factory_path`；
- endpoint、initiator、bridge、fabric、control 或 fixture 角色；
- core/integration 构造层，以及 foundation/primary/profile/convenience 选择层级；
- operation form、协议适用范围、端口形状和必要输入；
- 可选 showcase 路径。

Catalog 持有描述记录、筛选规则和 factory import path。加载后的 callable 由其定义模块持有，constructed
`VirtualDut` 的局部状态由 module/backend 持有，连接与系统运行状态由调用方的 `SystemProtocol` 持有。

## 公共入口

| API | 产出 |
|---|---|
| `VIRTUAL_DUT_RECIPES` | 当前公共 recipe 描述的不可变清单 |
| `get_virtual_dut_recipe(id)` | 一个稳定 id 对应的描述 |
| `list_virtual_dut_recipes(...)` | 按 kind、layer、tier 筛选后的描述 |
| `render_virtual_dut_recipe_catalog(...)` | 面向终端和文档工具的 Markdown 表 |
| `VirtualDutRecipe` 及三个 enum | typed metadata model |

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

## 构造交接与准入

`load_factory()` 解析描述中的 callable。调用者随后显式提供 factory 所需的协议、地址空间、route 和 policy；
factory 的参数校验与 capability/policy guard 判定具体组合的兼容性。Catalog 查询负责发现候选 recipe。

清单写在 [`entries.py`](entries.py)。新增公共 recipe 时同步补充一项描述，内部 helper 保持在所属实现包。
上层职责与构造流程见 [`recipes/README.md`](../README.md)。以下命令输出当前完整 Markdown 表：

```bash
python -m protocol_model.integrations.recipes.catalog
```
