"""Print the discoverable VirtualDut recipe inventory."""

from . import render_virtual_dut_recipe_catalog


if __name__ == "__main__":
    print(render_virtual_dut_recipe_catalog())
