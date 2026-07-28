"""Immutable execution projection of directed transport connections."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, TYPE_CHECKING

from ..topology.model import VirtualDutPortRef
from ..topology.transport import DirectedTransportConnection

if TYPE_CHECKING:
    from ..protocol import SystemProtocol


@dataclass(frozen=True)
class ResolvedTransportHop:
    """One validated transmitter-to-receiver hop in a resolved system."""

    name: str
    transport_family: str
    transmitter: VirtualDutPortRef
    receiver: VirtualDutPortRef
    profile: object | None = None


@dataclass(frozen=True)
class ResolvedTransportPlan:
    """Read-only transport graph derived from the canonical topology."""

    hops: tuple[ResolvedTransportHop, ...]
    hops_by_name: Mapping[str, ResolvedTransportHop]
    outgoing_by_port: Mapping[
        VirtualDutPortRef, tuple[ResolvedTransportHop, ...]
    ]
    incoming_by_port: Mapping[
        VirtualDutPortRef, tuple[ResolvedTransportHop, ...]
    ]

    def __post_init__(self) -> None:
        hops = tuple(self.hops)
        by_name = dict(self.hops_by_name)
        if set(by_name) != {hop.name for hop in hops}:
            raise ValueError(
                "transport plan names must cover exactly the resolved hops"
            )
        object.__setattr__(self, "hops", hops)
        object.__setattr__(self, "hops_by_name", MappingProxyType(by_name))
        object.__setattr__(
            self,
            "outgoing_by_port",
            MappingProxyType(
                {
                    port: tuple(port_hops)
                    for port, port_hops in self.outgoing_by_port.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "incoming_by_port",
            MappingProxyType(
                {
                    port: tuple(port_hops)
                    for port, port_hops in self.incoming_by_port.items()
                }
            ),
        )


def resolve_transport_connections(
    system: "SystemProtocol",
) -> ResolvedTransportPlan | None:
    """Project directed transport edges without creating a second topology."""

    connections = system.transport_connections
    if not connections:
        return None
    hops = tuple(
        _resolved_hop(connection) for connection in connections.values()
    )
    outgoing: dict[VirtualDutPortRef, list[ResolvedTransportHop]] = {}
    incoming: dict[VirtualDutPortRef, list[ResolvedTransportHop]] = {}
    for hop in hops:
        outgoing.setdefault(hop.transmitter, []).append(hop)
        incoming.setdefault(hop.receiver, []).append(hop)
    return ResolvedTransportPlan(
        hops,
        {hop.name: hop for hop in hops},
        {port: tuple(port_hops) for port, port_hops in outgoing.items()},
        {port: tuple(port_hops) for port, port_hops in incoming.items()},
    )


def _resolved_hop(
    connection: DirectedTransportConnection,
) -> ResolvedTransportHop:
    return ResolvedTransportHop(
        connection.name,
        connection.transport_family,
        connection.transmitter,
        connection.receiver,
        connection.profile,
    )


__all__ = [
    "ResolvedTransportHop",
    "ResolvedTransportPlan",
    "resolve_transport_connections",
]
