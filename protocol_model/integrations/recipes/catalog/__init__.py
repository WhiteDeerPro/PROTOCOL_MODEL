"""Browse the supported VirtualDut construction surface by module role."""

from __future__ import annotations

from .entries import VIRTUAL_DUT_RECIPES
from .model import (
    VirtualDutRecipe,
    VirtualDutRecipeKind,
    VirtualDutRecipeLayer,
    VirtualDutRecipeTier,
)


def list_virtual_dut_recipes(
    *,
    kind: VirtualDutRecipeKind | str | None = None,
    layer: VirtualDutRecipeLayer | str | None = None,
    tier: VirtualDutRecipeTier | str | None = None,
) -> tuple[VirtualDutRecipe, ...]:
    """Return recipes matching the supplied role and construction filters."""

    kind_filter = VirtualDutRecipeKind(kind) if kind is not None else None
    layer_filter = VirtualDutRecipeLayer(layer) if layer is not None else None
    tier_filter = VirtualDutRecipeTier(tier) if tier is not None else None
    return tuple(
        recipe
        for recipe in VIRTUAL_DUT_RECIPES
        if (kind_filter is None or recipe.kind is kind_filter)
        and (layer_filter is None or recipe.layer is layer_filter)
        and (tier_filter is None or recipe.tier is tier_filter)
    )


def get_virtual_dut_recipe(recipe_id: str) -> VirtualDutRecipe:
    """Return one recipe by stable id, with a useful error for unknown ids."""

    for recipe in VIRTUAL_DUT_RECIPES:
        if recipe.id == recipe_id:
            return recipe
    known = ", ".join(recipe.id for recipe in VIRTUAL_DUT_RECIPES)
    raise KeyError(f"unknown VirtualDut recipe {recipe_id!r}; known ids: {known}")


def render_virtual_dut_recipe_catalog(
    recipes: tuple[VirtualDutRecipe, ...] | None = None,
) -> str:
    """Render a compact Markdown inventory for terminals and documentation tools."""

    selected = VIRTUAL_DUT_RECIPES if recipes is None else recipes
    lines = [
        "| id | role | layer/tier | ports | protocol scope | factory |",
        "|---|---|---|---|---|---|",
    ]
    for recipe in selected:
        protocols = ", ".join(recipe.protocol_scope)
        lines.append(
            f"| `{recipe.id}` | {recipe.kind.value} | "
            f"{recipe.layer.value}/{recipe.tier.value} | {recipe.port_shape} | "
            f"{protocols} | `{recipe.factory_name}` |"
        )
    return "\n".join(lines)


__all__ = [
    "VIRTUAL_DUT_RECIPES",
    "VirtualDutRecipe",
    "VirtualDutRecipeKind",
    "VirtualDutRecipeLayer",
    "VirtualDutRecipeTier",
    "get_virtual_dut_recipe",
    "list_virtual_dut_recipes",
    "render_virtual_dut_recipe_catalog",
]
