"""Conceptual entry points for the Protocol Model package.

The package root is an orientation facade, not the ownership location of the
full API.  Import detailed declarations, policies, state, and construction
recipes from their named packages.  The four concepts below remain available
as lazy anchors so that importing :mod:`protocol_model` does not load every
protocol family and integration recipe.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any


__version__ = "0.4.0"


_PUBLIC_ANCHORS = {
    "CanonicalEvent": (".semantics", "CanonicalEvent"),
    "InterfaceProtocol": (".interface", "InterfaceProtocol"),
    "VirtualDut": (".virtual_dut.boundary", "VirtualDut"),
    "SystemProtocol": (".system", "SystemProtocol"),
}


if TYPE_CHECKING:
    from .interface import InterfaceProtocol
    from .semantics import CanonicalEvent
    from .system import SystemProtocol
    from .virtual_dut.boundary import VirtualDut


def __getattr__(name: str) -> Any:
    """Resolve a conceptual anchor on first use and cache it locally."""

    try:
        module_name, attribute_name = _PUBLIC_ANCHORS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error

    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """Expose lazy anchors to interactive discovery tools."""

    return sorted(set(globals()) | set(_PUBLIC_ANCHORS))


__all__ = [
    "CanonicalEvent",
    "InterfaceProtocol",
    "SystemProtocol",
    "VirtualDut",
    "__version__",
]
