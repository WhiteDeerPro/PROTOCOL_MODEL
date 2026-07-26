"""Typed ownership values for ports in an elaborated system topology."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PortOwnerKind(str, Enum):
    """Kinds of topology object that may exclusively own a DUT port."""

    INTERFACE_CONNECTION = "interface_connection"
    TRANSPORT_CONNECTION = "transport_connection"
    BOUNDARY = "boundary"


@dataclass(frozen=True)
class PortOwnerRef:
    """Stable typed reference to the topology object owning one DUT port.

    The owner name is interpreted together with ``kind`` so diagnostics and
    resolvers do not parse string prefixes to discover the owner type.
    """

    kind: PortOwnerKind
    name: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, PortOwnerKind):
            raise TypeError("port owner kind requires PortOwnerKind")
        if not isinstance(self.name, str):
            raise TypeError("port owner name requires str")
        if not self.name.strip():
            raise ValueError("port owner requires a non-empty name")

    @classmethod
    def interface_connection(cls, name: str) -> "PortOwnerRef":
        """Reference an InterfaceConnection owning a port."""

        return cls(PortOwnerKind.INTERFACE_CONNECTION, name)

    @classmethod
    def transport_connection(cls, name: str) -> "PortOwnerRef":
        """Reference a directed transport connection owning a port."""

        return cls(PortOwnerKind.TRANSPORT_CONNECTION, name)

    @classmethod
    def boundary(cls, name: str) -> "PortOwnerRef":
        """Reference a named exposed system boundary owning a port."""

        return cls(PortOwnerKind.BOUNDARY, name)

    @property
    def is_connection(self) -> bool:
        """Whether this owner is either supported connection kind."""

        return self.kind in (
            PortOwnerKind.INTERFACE_CONNECTION,
            PortOwnerKind.TRANSPORT_CONNECTION,
        )

    @property
    def is_boundary(self) -> bool:
        """Whether this owner is a named system boundary."""

        return self.kind is PortOwnerKind.BOUNDARY

    @property
    def qualified_name(self) -> str:
        """Return an unambiguous label suitable for diagnostics."""

        return f"{self.kind.value}:{self.name}"


__all__ = ["PortOwnerKind", "PortOwnerRef"]
