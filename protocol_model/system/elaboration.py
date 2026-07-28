"""Topology and ownership elaboration for SystemProtocol."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import SemanticFragment, compose_fragments
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.boundary.transport import (
    TransportDirection,
    TransportPort,
)

from .protocol import SystemProtocol
from .resolution.address import ResolvedAddressPlan, resolve_address_map
from .resolution.transport import (
    ResolvedTransportPlan,
    resolve_transport_connections,
)
from .topology.model import InterfaceConnection, VirtualDutPortRef
from .topology.ownership import PortOwnerRef
from .topology.transport import DirectedTransportConnection


@dataclass(frozen=True)
class ElaboratedSystemProtocol:
    spec: SystemProtocol
    semantics: SemanticFragment
    owner_by_port: Mapping[VirtualDutPortRef, PortOwnerRef]
    address_plan: ResolvedAddressPlan | None = None
    transport_plan: ResolvedTransportPlan | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "owner_by_port", MappingProxyType(dict(self.owner_by_port))
        )


def _resolve_port(
    system: SystemProtocol, reference: VirtualDutPortRef
) -> InterfacePort | TransportPort:
    try:
        dut = system.virtual_duts[reference.dut]
    except KeyError as exc:
        raise ValueError(f"unknown VirtualDut {reference.dut!r}") from exc
    try:
        return dut.port(reference.port)
    except KeyError as exc:
        raise ValueError(
            f"unknown port {reference.port!r} on VirtualDut {reference.dut!r}"
        ) from exc


def elaborate_system_protocol(system: SystemProtocol) -> ElaboratedSystemProtocol:
    owners: dict[VirtualDutPortRef, PortOwnerRef] = {}
    fragments: list[SemanticFragment] = []

    for dut_name, dut in system.virtual_duts.items():
        if dut.semantics is not None:
            fragments.append(dut.semantics.namespaced(f"dut.{dut_name}"))

    for connection_name, connection in system.connections.items():
        if isinstance(connection, InterfaceConnection):
            for role, reference in connection.endpoints.items():
                port = _resolve_port(system, reference)
                if not isinstance(port, InterfacePort):
                    raise ValueError(
                        f"{reference.qualified_name} is a transport port, "
                        "not an InterfacePort"
                    )
                if port.role != role:
                    raise ValueError(
                        f"{reference.qualified_name} has role {port.role!r}, "
                        f"not bound role {role!r}"
                    )
                if port.protocol != connection.protocol:
                    raise ValueError(
                        f"{reference.qualified_name} uses "
                        f"{port.protocol.name!r}, not interface protocol "
                        f"{connection.protocol.name!r}"
                    )
                _claim_owner(
                    owners,
                    reference,
                    PortOwnerRef.interface_connection(connection_name),
                )
            fragments.append(
                connection.protocol.semantics.namespaced(
                    f"interface.{connection_name}"
                )
            )
            continue
        if not isinstance(connection, DirectedTransportConnection):
            raise TypeError("system contains an unsupported connection type")
        for reference, expected_direction in (
            (connection.transmitter, TransportDirection.TRANSMIT),
            (connection.receiver, TransportDirection.RECEIVE),
        ):
            port = _resolve_port(system, reference)
            if not isinstance(port, TransportPort):
                raise ValueError(
                    f"{reference.qualified_name} is an interface protocol "
                    "port, not a transport port"
                )
            if port.direction is not expected_direction:
                raise ValueError(
                    f"{reference.qualified_name} has transport direction "
                    f"{port.direction.value!r}, expected "
                    f"{expected_direction.value!r}"
                )
            if port.transport_family != connection.transport_family:
                raise ValueError(
                    f"{reference.qualified_name} uses transport family "
                    f"{port.transport_family!r}, not "
                    f"{connection.transport_family!r}"
                )
            _claim_owner(
                owners,
                reference,
                PortOwnerRef.transport_connection(connection_name),
            )

    for boundary_name, reference in system.boundary.items():
        _resolve_port(system, reference)
        if reference in owners:
            raise ValueError(
                f"boundary port {reference.qualified_name!r} is already connected"
            )
        if reference in system.boundary.values() and any(
            other_name != boundary_name and other_ref == reference
            for other_name, other_ref in system.boundary.items()
        ):
            raise ValueError(
                f"VirtualDut port {reference.qualified_name!r} has multiple boundary names"
            )
        owners[reference] = PortOwnerRef.boundary(boundary_name)

    declared = {
        VirtualDutPortRef(dut_name, port_name)
        for dut_name, dut in system.virtual_duts.items()
        for port_name in dut.ports
    }
    unowned = declared - set(owners)
    if unowned:
        names = sorted(item.qualified_name for item in unowned)
        raise ValueError(f"unconnected VirtualDut ports: {names!r}")

    if system.semantics is not None:
        fragments.append(system.semantics.namespaced(f"system.{system.name}"))

    return ElaboratedSystemProtocol(
        spec=system,
        semantics=compose_fragments(f"{system.name}.elaborated", *fragments),
        owner_by_port=owners,
        address_plan=resolve_address_map(system, owners),
        transport_plan=resolve_transport_connections(system),
    )


def _claim_owner(
    owners: dict[VirtualDutPortRef, PortOwnerRef],
    reference: VirtualDutPortRef,
    owner: PortOwnerRef,
) -> None:
    if reference in owners:
        raise ValueError(
            f"VirtualDut port {reference.qualified_name!r} is multiply owned"
        )
    owners[reference] = owner
