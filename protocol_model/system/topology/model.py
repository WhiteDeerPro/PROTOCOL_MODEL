"""Weak structural topology values shared by SystemProtocol phases."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from protocol_model.interface import InterfaceProtocol


@dataclass(frozen=True, order=True)
class VirtualDutPortRef:
    """Stable reference to one named port on one named VirtualDut."""

    dut: str
    port: str

    def __post_init__(self) -> None:
        if not isinstance(self.dut, str) or not self.dut:
            raise ValueError("VirtualDut port reference requires a DUT name")
        if not isinstance(self.port, str) or not self.port:
            raise ValueError("VirtualDut port reference requires a port name")

    @property
    def qualified_name(self) -> str:
        return f"{self.dut}.{self.port}"


@dataclass(frozen=True)
class InterfaceConnection:
    """One concrete connection binding every interface role to a DUT port."""

    name: str
    protocol: InterfaceProtocol
    endpoints: Mapping[str, VirtualDutPortRef]
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("interface connection requires a name")
        endpoints = dict(self.endpoints)
        if set(endpoints) != set(self.protocol.roles):
            raise ValueError(
                f"connection {self.name!r} must bind roles "
                f"{sorted(self.protocol.roles)!r}"
            )
        unknown = set(self.parameters) - set(self.protocol.parameters)
        if unknown:
            raise ValueError(
                f"unknown interface parameters: {sorted(unknown)!r}"
            )
        object.__setattr__(self, "endpoints", MappingProxyType(endpoints))
        object.__setattr__(
            self,
            "parameters",
            MappingProxyType(dict(self.parameters)),
        )


__all__ = ["InterfaceConnection", "VirtualDutPortRef"]
