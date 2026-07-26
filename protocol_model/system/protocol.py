"""Global protocols composed from VirtualDuts and interface contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TYPE_CHECKING

from protocol_model.interface import InterfaceProtocol
from protocol_model.semantics import SemanticFragment
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.boundary.transport import TransportPort

from .contracts.address import AddressMapContract
from .topology.model import InterfaceConnection, VirtualDutPortRef
from .topology.transport import DirectedTransportConnection

if TYPE_CHECKING:
    from .elaboration import ElaboratedSystemProtocol


SystemConnection = InterfaceConnection | DirectedTransportConnection


@dataclass(frozen=True)
class SystemProtocol:
    """A globally constrained user communication protocol.

    It owns concrete VirtualDuts, connection declarations, boundary ports,
    and constraints whose truth can only be decided over the composed system.
    Complete logical interfaces and directed transport hops share this one
    topology registry but retain different execution contracts.
    """

    name: str
    virtual_duts: Mapping[str, VirtualDut]
    connections: Mapping[str, SystemConnection]
    boundary: Mapping[str, VirtualDutPortRef] = field(default_factory=dict)
    semantics: SemanticFragment | None = None
    address_map: AddressMapContract | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("system protocol requires a name")
        duts = dict(self.virtual_duts)
        connections = dict(self.connections)
        boundary = dict(self.boundary)
        if set(duts) != {item.name for item in duts.values()}:
            raise ValueError("VirtualDut mapping keys must match DUT names")
        if set(connections) != {item.name for item in connections.values()}:
            raise ValueError(
                "connection mapping keys must match connection names"
            )
        if any(
            not isinstance(
                item, (InterfaceConnection, DirectedTransportConnection)
            )
            for item in connections.values()
        ):
            raise TypeError(
                "system connections require InterfaceConnection or "
                "DirectedTransportConnection values"
            )
        if any(not name for name in boundary):
            raise ValueError("system boundary names must not be empty")
        if self.address_map is not None and not isinstance(
            self.address_map, AddressMapContract
        ):
            raise TypeError(
                "SystemProtocol address_map requires AddressMapContract"
            )
        object.__setattr__(self, "virtual_duts", MappingProxyType(duts))
        object.__setattr__(
            self, "connections", MappingProxyType(connections)
        )
        object.__setattr__(self, "boundary", MappingProxyType(boundary))

    def elaborate(self) -> "ElaboratedSystemProtocol":
        from .elaboration import elaborate_system_protocol

        return elaborate_system_protocol(self)

    @property
    def interface_connections(self) -> Mapping[str, InterfaceConnection]:
        return MappingProxyType(
            {
                name: connection
                for name, connection in self.connections.items()
                if isinstance(connection, InterfaceConnection)
            }
        )

    @property
    def transport_connections(
        self,
    ) -> Mapping[str, DirectedTransportConnection]:
        return MappingProxyType(
            {
                name: connection
                for name, connection in self.connections.items()
                if isinstance(connection, DirectedTransportConnection)
            }
        )

    @classmethod
    def from_interface(
        cls,
        name: str,
        *,
        connection_name: str,
        protocol: InterfaceProtocol,
        endpoints: Mapping[str, tuple[VirtualDut, str]],
        boundary: Mapping[str, VirtualDutPortRef] | None = None,
        semantics: SemanticFragment | None = None,
    ) -> "SystemProtocol":
        """Lift one interface use into a point-to-point SystemProtocol."""

        duts: dict[str, VirtualDut] = {}
        references: dict[str, VirtualDutPortRef] = {}
        for role, (dut, port_name) in endpoints.items():
            existing = duts.get(dut.name)
            if existing is not None and existing is not dut:
                raise ValueError(f"different VirtualDuts share name {dut.name!r}")
            duts[dut.name] = dut
            references[role] = VirtualDutPortRef(dut.name, port_name)
        connection = InterfaceConnection(
            connection_name, protocol, references
        )
        return cls(
            name,
            duts,
            {connection.name: connection},
            boundary or {},
            semantics,
        )

    def open_session(self, *, max_internal_steps: int = 1024):
        from .session import SystemSession

        if self.transport_connections:
            raise ValueError(
                "SystemSession currently executes InterfaceConnection only; "
                "open a transport-family session from the elaborated "
                "transport plan"
            )
        return SystemSession(
            self.elaborate(), max_internal_steps=max_internal_steps
        )

    def as_virtual_dut(self, name: str) -> VirtualDut:
        """Encapsulate this system for recursive chip/package/board composition."""

        elaborated = self.elaborate()
        ports: dict[str, InterfacePort | TransportPort] = {}
        for boundary_name, reference in self.boundary.items():
            inner = self.virtual_duts[reference.dut].port(reference.port)
            if isinstance(inner, InterfacePort):
                ports[boundary_name] = InterfacePort(
                    name=boundary_name,
                    protocol=inner.protocol,
                    role=inner.role,
                    capability=inner.capability,
                    clock_domain=inner.clock_domain,
                    reset_domain=inner.reset_domain,
                )
            else:
                ports[boundary_name] = TransportPort(
                    name=boundary_name,
                    transport_family=inner.transport_family,
                    direction=inner.direction,
                    capability=inner.capability,
                    clock_domain=inner.clock_domain,
                    reset_domain=inner.reset_domain,
                )
        return VirtualDut(
            name=name,
            ports=ports,
            semantics=elaborated.semantics,
            subsystem=self,
            description=f"SystemProtocol[{self.name}]",
        )
