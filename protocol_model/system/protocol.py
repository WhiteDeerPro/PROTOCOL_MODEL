"""Global protocols composed from VirtualDuts and local LinkProtocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TYPE_CHECKING

from protocol_model.link import LinkProtocol
from protocol_model.semantics import SemanticFragment
from protocol_model.virtual_dut.boundary.module import DutFacet, VirtualDut
from protocol_model.virtual_dut.boundary.port import ProtocolPort

if TYPE_CHECKING:
    from .elaboration import ElaboratedSystemProtocol


@dataclass(frozen=True, order=True)
class VirtualDutPortRef:
    dut: str
    port: str

    @property
    def qualified_name(self) -> str:
        return f"{self.dut}.{self.port}"


@dataclass(frozen=True)
class ProtocolLink:
    """One concrete link binding every protocol role to a VirtualDut port."""

    name: str
    protocol: LinkProtocol
    endpoints: Mapping[str, VirtualDutPortRef]
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("protocol link requires a name")
        endpoints = dict(self.endpoints)
        if set(endpoints) != set(self.protocol.roles):
            raise ValueError(
                f"link {self.name!r} must bind roles {sorted(self.protocol.roles)!r}"
            )
        unknown = set(self.parameters) - set(self.protocol.parameters)
        if unknown:
            raise ValueError(f"unknown link parameters: {sorted(unknown)!r}")
        object.__setattr__(self, "endpoints", MappingProxyType(endpoints))
        object.__setattr__(self, "parameters", MappingProxyType(dict(self.parameters)))


@dataclass(frozen=True)
class SystemProtocol:
    """A globally constrained user communication protocol.

    It owns concrete VirtualDuts, link bindings, exposed boundary ports, and
    constraints whose truth can only be decided over the composed system.
    """

    name: str
    virtual_duts: Mapping[str, VirtualDut]
    links: Mapping[str, ProtocolLink]
    boundary: Mapping[str, VirtualDutPortRef] = field(default_factory=dict)
    semantics: SemanticFragment | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("system protocol requires a name")
        duts = dict(self.virtual_duts)
        links = dict(self.links)
        boundary = dict(self.boundary)
        if set(duts) != {item.name for item in duts.values()}:
            raise ValueError("VirtualDut mapping keys must match DUT names")
        if set(links) != {item.name for item in links.values()}:
            raise ValueError("link mapping keys must match link names")
        if any(not name for name in boundary):
            raise ValueError("system boundary names must not be empty")
        object.__setattr__(self, "virtual_duts", MappingProxyType(duts))
        object.__setattr__(self, "links", MappingProxyType(links))
        object.__setattr__(self, "boundary", MappingProxyType(boundary))

    def elaborate(self) -> "ElaboratedSystemProtocol":
        from .elaboration import elaborate_system_protocol

        return elaborate_system_protocol(self)

    @classmethod
    def from_link(
        cls,
        name: str,
        *,
        link_name: str,
        protocol: LinkProtocol,
        endpoints: Mapping[str, tuple[VirtualDut, str]],
        boundary: Mapping[str, VirtualDutPortRef] | None = None,
        semantics: SemanticFragment | None = None,
    ) -> "SystemProtocol":
        """Lift even one point-to-point LinkProtocol use into a SystemProtocol."""

        duts: dict[str, VirtualDut] = {}
        references: dict[str, VirtualDutPortRef] = {}
        for role, (dut, port_name) in endpoints.items():
            existing = duts.get(dut.name)
            if existing is not None and existing is not dut:
                raise ValueError(f"different VirtualDuts share name {dut.name!r}")
            duts[dut.name] = dut
            references[role] = VirtualDutPortRef(dut.name, port_name)
        link = ProtocolLink(link_name, protocol, references)
        return cls(
            name,
            duts,
            {link.name: link},
            boundary or {},
            semantics,
        )

    def open_session(self, *, max_internal_steps: int = 1024):
        from .session import SystemSession

        return SystemSession(
            self.elaborate(), max_internal_steps=max_internal_steps
        )

    def as_virtual_dut(self, name: str) -> VirtualDut:
        """Encapsulate this system for recursive chip/package/board composition."""

        elaborated = self.elaborate()
        ports: dict[str, ProtocolPort] = {}
        for boundary_name, reference in self.boundary.items():
            inner = self.virtual_duts[reference.dut].port(reference.port)
            ports[boundary_name] = ProtocolPort(
                name=boundary_name,
                protocol=inner.protocol,
                role=inner.role,
                capability=inner.capability,
                clock_domain=inner.clock_domain,
                reset_domain=inner.reset_domain,
            )
        return VirtualDut(
            name=name,
            ports=ports,
            facets=frozenset((DutFacet.COMPOSITE,)),
            semantics=elaborated.semantics,
            subsystem=self,
            description=f"SystemProtocol[{self.name}]",
        )
