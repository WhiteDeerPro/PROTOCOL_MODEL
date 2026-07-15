"""Concrete virtual modules placed in a communication system."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping, TYPE_CHECKING

from protocol_model.semantics import SemanticFragment

from ..backend.base import VirtualDutModel
from .port import ProtocolPort

if TYPE_CHECKING:
    from ..binding.port import PortAttachmentBinding


class DutFacet(str, Enum):
    """Provisional display metadata, not device categories."""

    ADDRESSABLE = "addressable"
    INITIATING = "initiating"
    STORING = "storing"
    TRANSFORMING = "transforming"
    ROUTING = "routing"
    SIGNALING = "signaling"
    COMPOSITE = "composite"


@dataclass(frozen=True)
class VirtualDut:
    """One concrete named module, described only to protocol-visible depth."""

    name: str
    ports: Mapping[str, ProtocolPort]
    facets: frozenset[DutFacet] = frozenset()
    model: VirtualDutModel | None = field(default=None, repr=False, compare=False)
    semantics: SemanticFragment | None = None
    subsystem: object | None = field(default=None, repr=False, compare=False)
    description: str = ""
    bindings: Mapping[str, "PortAttachmentBinding"] = field(
        default_factory=dict, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("VirtualDut requires a name")
        if self.model is not None and not isinstance(self.model, VirtualDutModel):
            raise TypeError("VirtualDut model must implement VirtualDutModel")
        ports = dict(self.ports)
        if set(ports) != {item.name for item in ports.values()}:
            raise ValueError("VirtualDut port mapping keys must match port names")
        facets = frozenset(
            item if isinstance(item, DutFacet) else DutFacet(item)
            for item in self.facets
        )
        bindings = dict(self.bindings)
        from ..binding.port import PortAttachmentBinding

        if any(
            not isinstance(item, PortAttachmentBinding)
            for item in bindings.values()
        ):
            raise TypeError("VirtualDut bindings require PortAttachmentBinding values")
        if set(bindings) != {item.name for item in bindings.values()}:
            raise ValueError("VirtualDut binding mapping keys must match port names")
        unknown_bindings = set(bindings) - set(ports)
        if unknown_bindings:
            raise ValueError(
                f"VirtualDut bindings reference unknown ports: "
                f"{sorted(unknown_bindings)!r}"
            )
        for name, binding in bindings.items():
            if binding.port != ports[name]:
                raise ValueError(
                    f"VirtualDut binding for {name!r} disagrees with its port"
                )
        if self.model is not None:
            backend_bindings = self.model.local_attachment_bindings()
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
        object.__setattr__(self, "facets", facets)
        object.__setattr__(self, "bindings", MappingProxyType(bindings))

    def port(self, name: str) -> ProtocolPort:
        return self.ports[name]

    @property
    def model_name(self) -> str:
        if self.model is not None:
            return type(self.model).__name__
        if DutFacet.COMPOSITE in self.facets and self.subsystem is not None:
            return "SystemProtocol"
        return "declaration"
