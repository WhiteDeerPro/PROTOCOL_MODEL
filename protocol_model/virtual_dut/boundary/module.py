"""Concrete virtual modules placed in a communication system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, TYPE_CHECKING

from protocol_model.semantics import SemanticFragment

from ..backend.base import VirtualDutBackend
from .port import InterfacePort
from .transport import TransportPort

if TYPE_CHECKING:
    from ..binding.port import InterfaceAttachmentBinding


class DutBehaviorTag(str, Enum):
    """Non-authoritative behavior metadata for discovery and display."""

    ADDRESSABLE = "addressable"
    INITIATING = "initiating"
    TRANSFORMING = "transforming"
    ROUTING = "routing"
    SIGNALING = "signaling"


@dataclass(frozen=True)
class VirtualDut:
    """One concrete named module, described only to protocol-visible depth."""

    name: str
    ports: Mapping[str, InterfacePort | TransportPort]
    behavior_tags: frozenset[DutBehaviorTag] = frozenset()
    backend: VirtualDutBackend | None = field(
        default=None, repr=False, compare=False
    )
    semantics: SemanticFragment | None = None
    subsystem: object | None = field(default=None, repr=False, compare=False)
    description: str = ""
    bindings: Mapping[str, "InterfaceAttachmentBinding"] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("VirtualDut requires a name")
        if self.backend is not None and not isinstance(
            self.backend, VirtualDutBackend
        ):
            raise TypeError("VirtualDut backend must implement VirtualDutBackend")
        ports = dict(self.ports)
        if any(
            not isinstance(item, (InterfacePort, TransportPort))
            for item in ports.values()
        ):
            raise TypeError(
                "VirtualDut ports require InterfacePort or TransportPort values"
            )
        if set(ports) != {item.name for item in ports.values()}:
            raise ValueError("VirtualDut port mapping keys must match port names")
        behavior_tags = frozenset(
            item if isinstance(item, DutBehaviorTag) else DutBehaviorTag(item)
            for item in self.behavior_tags
        )
        bindings = dict(self.bindings)
        from ..binding.port import InterfaceAttachmentBinding

        if any(
            not isinstance(item, InterfaceAttachmentBinding)
            for item in bindings.values()
        ):
            raise TypeError("VirtualDut bindings require InterfaceAttachmentBinding values")
        if set(bindings) != {item.name for item in bindings.values()}:
            raise ValueError("VirtualDut binding mapping keys must match port names")
        unknown_bindings = set(bindings) - set(ports)
        if unknown_bindings:
            raise ValueError(
                f"VirtualDut bindings reference unknown ports: "
                f"{sorted(unknown_bindings)!r}"
            )
        for name, binding in bindings.items():
            if not isinstance(ports[name], InterfacePort):
                raise ValueError(
                    f"transport port {name!r} cannot own an interface attachment"
                )
            if binding.port != ports[name]:
                raise ValueError(
                    f"VirtualDut binding for {name!r} disagrees with its port"
                )
        if self.backend is not None:
            backend_bindings = self.backend.local_attachment_bindings()
            if backend_bindings is not None:
                backend_bindings = dict(backend_bindings)
                if set(backend_bindings) != set(bindings):
                    raise ValueError(
                        "VirtualDut bindings do not cover the attachment-aware "
                        "backend bindings"
                    )
                for name, backend_binding in backend_bindings.items():
                    if backend_binding is not bindings[name]:
                        raise ValueError(
                            f"VirtualDut binding {name!r} is not the binding "
                            "used by its backend"
                        )
        object.__setattr__(self, "ports", MappingProxyType(ports))
        object.__setattr__(self, "behavior_tags", behavior_tags)
        object.__setattr__(self, "bindings", MappingProxyType(bindings))

    def port(self, name: str) -> InterfacePort | TransportPort:
        return self.ports[name]

    @property
    def realization_name(self) -> str:
        if self.backend is not None:
            return type(self.backend).__name__
        if self.subsystem is not None:
            return "SystemProtocol"
        return "declaration"
