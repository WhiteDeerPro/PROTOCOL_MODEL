"""Typed inventory records for discoverable VirtualDut construction recipes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from typing import Callable


class VirtualDutRecipeKind(str, Enum):
    """The module role produced by a recipe."""

    ENDPOINT = "endpoint"
    INITIATOR = "initiator"
    BRIDGE = "bridge"
    FABRIC = "fabric"
    CONTROL = "control"
    FIXTURE = "fixture"


class VirtualDutRecipeLayer(str, Enum):
    """Where protocol knowledge first enters the construction."""

    CORE = "core"
    INTEGRATION = "integration"


class VirtualDutRecipeTier(str, Enum):
    """How a recipe is intended to be selected by callers and tools."""

    FOUNDATION = "foundation"
    PRIMARY = "primary"
    PROFILE = "profile"
    CONVENIENCE = "convenience"


@dataclass(frozen=True)
class VirtualDutRecipe:
    """A discoverable factory description, not a persistent VirtualDut instance.

    ``factory_path`` deliberately uses an import path instead of registering a
    callable at module-import time.  The inventory can therefore be inspected by
    documentation and GUI code without eagerly constructing protocols or modules.
    """

    id: str
    title: str
    kind: VirtualDutRecipeKind
    layer: VirtualDutRecipeLayer
    tier: VirtualDutRecipeTier
    factory_path: str
    operation_form: str
    protocol_scope: tuple[str, ...]
    port_shape: str
    summary: str
    required_inputs: tuple[str, ...] = ()
    example: str | None = None

    def __post_init__(self) -> None:
        if not self.id or any(part == "" for part in self.id.split(".")):
            raise ValueError("a VirtualDut recipe id must contain non-empty segments")
        module_name, separator, factory_name = self.factory_path.partition(":")
        if not separator or not module_name or not factory_name:
            raise ValueError(
                "factory_path must use the 'python.module:factory_name' form"
            )
        if not self.protocol_scope:
            raise ValueError("a VirtualDut recipe must state its protocol scope")

    @property
    def factory_name(self) -> str:
        """Return the public factory name without importing its module."""

        return self.factory_path.partition(":")[2]

    @property
    def module_path(self) -> str:
        """Return the public module containing the factory."""

        return self.factory_path.partition(":")[0]

    def load_factory(self) -> Callable[..., object]:
        """Resolve the described factory when a caller elects to construct it."""

        factory = getattr(import_module(self.module_path), self.factory_name)
        if not callable(factory):
            raise TypeError(f"recipe factory is not callable: {self.factory_path}")
        return factory
