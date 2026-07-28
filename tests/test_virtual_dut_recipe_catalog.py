from __future__ import annotations

import unittest

import protocol_model.integrations.recipes as recipe_facade
import protocol_model.integrations.recipes.amba as amba_recipes
import protocol_model.integrations.recipes.control as control_recipes
import protocol_model.virtual_dut as virtual_dut_facade
import protocol_model.virtual_dut.recipes as core_recipes
from protocol_model.integrations.recipes.catalog import (
    VIRTUAL_DUT_RECIPES,
    VirtualDutRecipeKind,
    VirtualDutRecipeLayer,
    VirtualDutRecipeTier,
    get_virtual_dut_recipe,
    list_virtual_dut_recipes,
    render_virtual_dut_recipe_catalog,
)


def _public_builders(module: object) -> set[str]:
    return {name for name in module.__all__ if name.startswith("build_")}  # type: ignore[attr-defined]


class VirtualDutRecipeCatalogTests(unittest.TestCase):
    def test_catalog_covers_the_public_core_and_integration_recipes(self) -> None:
        ids = [recipe.id for recipe in VIRTUAL_DUT_RECIPES]
        paths = [recipe.factory_path for recipe in VIRTUAL_DUT_RECIPES]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(paths), len(set(paths)))

        core_catalog = {
            recipe.factory_name
            for recipe in VIRTUAL_DUT_RECIPES
            if recipe.layer is VirtualDutRecipeLayer.CORE
        }
        integration_catalog = {
            recipe.factory_name
            for recipe in VIRTUAL_DUT_RECIPES
            if recipe.layer is VirtualDutRecipeLayer.INTEGRATION
        }
        public_integration = _public_builders(amba_recipes) | _public_builders(
            control_recipes
        )

        self.assertEqual(core_catalog, _public_builders(core_recipes))
        self.assertEqual(integration_catalog, public_integration)
        self.assertLessEqual(
            public_integration,
            _public_builders(recipe_facade),
        )

    def test_every_catalog_factory_is_lazy_loadable_and_callable(self) -> None:
        for recipe in VIRTUAL_DUT_RECIPES:
            with self.subTest(recipe=recipe.id):
                self.assertEqual(
                    recipe.load_factory().__name__,
                    recipe.factory_name,
                )

    def test_catalog_queries_distinguish_primary_recipe_from_pair_presets(
        self,
    ) -> None:
        primary_bridges = list_virtual_dut_recipes(
            kind=VirtualDutRecipeKind.BRIDGE,
            layer="integration",
            tier=VirtualDutRecipeTier.PRIMARY,
        )

        self.assertEqual(
            tuple(recipe.id for recipe in primary_bridges),
            ("amba.bridge.serial",),
        )
        self.assertEqual(
            get_virtual_dut_recipe("amba.bridge.serial").port_shape,
            "1 ingress -> 1 egress",
        )
        self.assertEqual(
            get_virtual_dut_recipe(
                "amba.fabric.axi4-lite-crossbar"
            ).port_shape,
            "N ingress -> M egress",
        )

    def test_catalog_has_a_terminal_friendly_projection(self) -> None:
        rendered = render_virtual_dut_recipe_catalog(
            list_virtual_dut_recipes(kind="fabric", layer="integration")
        )

        self.assertIn("amba.fabric.axi4-lite-crossbar", rendered)
        self.assertIn("build_axi4_lite_address_crossbar_vdut", rendered)
        self.assertIn("N ingress -> M egress", rendered)

    def test_virtual_dut_facade_exposes_the_core_crossbar_recipe(self) -> None:
        self.assertIs(
            virtual_dut_facade.build_scheduled_address_crossbar_vdut,
            core_recipes.build_scheduled_address_crossbar_vdut,
        )


if __name__ == "__main__":
    unittest.main()
