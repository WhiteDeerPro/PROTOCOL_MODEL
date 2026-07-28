"""Topology-independent execution of the current CHI transport slice."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.system.elaboration import ElaboratedSystemProtocol
from protocol_model.system.topology.model import VirtualDutPortRef
from protocol_model.virtual_dut.boundary.transport import (
    TransportDirection,
    TransportPort,
)

from ..participants import (
    ChiRoutedPacket,
    ChiRouterReceive,
    ChiRouterService,
    ChiStoreForwardRouterNode,
    ChiStoreForwardRouterState,
)
from ..representation import (
    ChiChannelKind,
    ChiNetworkPacket,
)
from ..transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiPathState,
    ChiTransportConnectionRuntime,
    ChiTransportLink,
    ChiTransportLinkProfile,
    open_transport_connection_runtime,
)

ChiNetworkPath = ChiTransportConnectionRuntime
ChiNetworkPathState = ChiPathState


def _require_name(value: str, subject: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{subject} requires a non-empty name")


@dataclass(frozen=True)
class ChiNetworkEnqueue:
    """Offer one protocol packet to a named transport connection."""

    connection: str
    packet: ChiNetworkPacket
    resource_plane: int = 0
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_name(self.connection, "CHI network enqueue")
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError("CHI network enqueue requires ChiNetworkPacket")
        if (
            not isinstance(self.resource_plane, int)
            or isinstance(self.resource_plane, bool)
            or not 0 <= self.resource_plane < 8
        ):
            raise ValueError("CHI network Resource Plane must be in 0..7")
        if self.packet.channel is not ChiChannelKind.REQ and (
            self.resource_plane != 0
        ):
            raise ValueError("only REQ traffic uses a Resource Plane")
        lineage = tuple(self.lineage)
        if any(not isinstance(item, str) or not item for item in lineage):
            raise ValueError("CHI network lineage entries must be non-empty")
        object.__setattr__(self, "lineage", lineage)


@dataclass(frozen=True)
class ChiNetworkTick:
    """Advance one named directed hop by one reference sampling frame."""

    connection: str
    active: bool = True

    def __post_init__(self) -> None:
        _require_name(self.connection, "CHI network tick")
        if type(self.active) is not bool:
            raise TypeError("CHI network tick active must be bool")


@dataclass(frozen=True)
class ChiNetworkCaptureToRouter:
    """Atomically transfer one captured flit into the receiving router."""

    connection: str
    channel: ChiChannelKind | None = None

    def __post_init__(self) -> None:
        _require_name(self.connection, "CHI network router capture")
        if self.channel is not None:
            object.__setattr__(
                self, "channel", ChiChannelKind(self.channel)
            )


@dataclass(frozen=True)
class ChiNetworkRouterToConnection:
    """Atomically service a router queue into a downstream TX FIFO."""

    connection: str
    channel: ChiChannelKind | None = None

    def __post_init__(self) -> None:
        _require_name(self.connection, "CHI network router forward")
        if self.channel is not None:
            object.__setattr__(
                self, "channel", ChiChannelKind(self.channel)
            )


@dataclass(frozen=True)
class ChiNetworkDrain:
    """Commit consumption of one captured endpoint delivery."""

    connection: str
    channel: ChiChannelKind | None = None

    def __post_init__(self) -> None:
        _require_name(self.connection, "CHI network drain")
        if self.channel is not None:
            object.__setattr__(
                self, "channel", ChiChannelKind(self.channel)
            )


ChiTransportNetworkAction = (
    ChiNetworkEnqueue
    | ChiNetworkTick
    | ChiNetworkCaptureToRouter
    | ChiNetworkRouterToConnection
    | ChiNetworkDrain
)


@dataclass(frozen=True)
class ChiNetworkDelivery:
    """One packet currently owned by a connection receiver."""

    connection: str
    transmitter: VirtualDutPortRef
    receiver: VirtualDutPortRef
    packet: ChiNetworkPacket
    resource_plane: int = 0
    lineage: tuple[str, ...] = ()


class ChiNetworkEventKind(str, Enum):
    ENQUEUE = "enqueue"
    LINK_TICK = "link_tick"
    ROUTER_ACCEPT = "router_accept"
    ROUTER_FORWARD = "router_forward"
    ENDPOINT_DELIVERY = "endpoint_delivery"


@dataclass(frozen=True)
class ChiNetworkEvent:
    kind: ChiNetworkEventKind
    connection: str
    node: str = ""
    packet: ChiNetworkPacket | None = None
    resource_plane: int = 0
    lineage: tuple[str, ...] = ()
    detail: object | None = None


@dataclass(frozen=True)
class ChiTransportNetworkState:
    """All dynamic state owned by one resolved CHI transport graph.

    ``lineage_by_connection`` is FIFO-aligned per channel.  It is sufficient
    for the current ordered channel FIFOs, including several channels sharing
    one Link.  A later lane or within-channel reordering model must bind
    evidence to packet identity instead of extending this positional sidecar.
    """

    paths: Mapping[str, ChiNetworkPathState]
    routers: Mapping[str, ChiStoreForwardRouterState]
    lineage_by_connection: Mapping[
        str,
        Mapping[ChiChannelKind, tuple[tuple[str, ...], ...]],
    ]

    def __post_init__(self) -> None:
        object.__setattr__(self, "paths", MappingProxyType(dict(self.paths)))
        object.__setattr__(
            self, "routers", MappingProxyType(dict(self.routers))
        )
        object.__setattr__(
            self,
            "lineage_by_connection",
            MappingProxyType(
                {
                    name: MappingProxyType(
                        {
                            ChiChannelKind(channel): tuple(
                                tuple(item) for item in entries
                            )
                            for channel, entries in channels.items()
                        }
                    )
                    for name, channels in
                    self.lineage_by_connection.items()
                }
            ),
        )


class ChiTransportNetworkSession(
    SemanticComponent[
        ChiTransportNetworkAction,
        ChiTransportNetworkState,
        ChiNetworkEvent,
    ]
):
    """Execute any resolved graph made from the current CHI hop subset.

    The session receives topology from ``ElaboratedSystemProtocol``; it does
    not contain a built-in line, ring, or mesh.  It owns hop and router state,
    while Home behavior, transaction ledgers, Retry, and coherence stay in
    their respective participants or system contracts.
    """

    def __init__(
        self,
        system: ElaboratedSystemProtocol,
        *,
        routers: Mapping[str, ChiStoreForwardRouterNode] | None = None,
        transmitter_capacity_by_connection: Mapping[str, int] | None = None,
    ) -> None:
        if not isinstance(system, ElaboratedSystemProtocol):
            raise TypeError("CHI network session requires an elaborated system")
        if system.transport_plan is None:
            raise ValueError("CHI network session requires transport connections")
        self.system = system
        self.name = f"{system.spec.name}.chi_transport_network"
        self.routers = MappingProxyType(dict(routers or {}))
        capacities = dict(transmitter_capacity_by_connection or {})
        unknown_capacities = set(capacities) - set(
            system.transport_plan.hops_by_name
        )
        if unknown_capacities:
            raise ValueError(
                "CHI TX capacities reference unknown connections: "
                f"{sorted(unknown_capacities)!r}"
            )
        paths: dict[str, ChiNetworkPath] = {}
        self.hops = system.transport_plan.hops_by_name
        for hop in system.transport_plan.hops:
            if hop.transport_family != CHI_ISSUE_H_TRANSPORT_FAMILY:
                raise ValueError(
                    f"transport connection {hop.name!r} belongs to "
                    f"{hop.transport_family!r}, not CHI Issue H"
                )
            if not isinstance(hop.profile, ChiTransportLinkProfile):
                raise TypeError(
                    f"transport connection {hop.name!r} requires "
                    "ChiTransportLinkProfile"
                )
            capacity = capacities.get(hop.name, 1)
            if (
                not isinstance(capacity, int)
                or isinstance(capacity, bool)
                or capacity <= 0
            ):
                raise ValueError("CHI path transmitter capacity must be positive")
            link = ChiTransportLink(
                hop.name,
                hop.transmitter,
                hop.receiver,
                hop.profile,
            )
            paths[hop.name] = open_transport_connection_runtime(
                link,
                transmitter_capacity=capacity,
            )
        self.paths: Mapping[str, ChiNetworkPath] = MappingProxyType(paths)
        self._validate_router_bindings()

    def _validate_router_bindings(self) -> None:
        for name, router in self.routers.items():
            if not isinstance(router, ChiStoreForwardRouterNode):
                raise TypeError("CHI router registry requires router nodes")
            if name != router.name:
                raise ValueError("CHI router registry key must match router name")
            dut = self.system.spec.virtual_duts.get(name)
            if dut is None:
                raise ValueError(f"CHI router {name!r} is not a system DUT")
            for port_name, direction in (
                *(
                    (item, TransportDirection.RECEIVE)
                    for item in router.ingress_ports
                ),
                *(
                    (item, TransportDirection.TRANSMIT)
                    for item in router.egress_ports
                ),
            ):
                port = dut.ports.get(port_name)
                if not isinstance(port, TransportPort):
                    raise ValueError(
                        f"CHI router port {name}.{port_name} is not a "
                        "TransportPort"
                    )
                if port.transport_family != CHI_ISSUE_H_TRANSPORT_FAMILY:
                    raise ValueError(
                        f"CHI router port {name}.{port_name} has another family"
                    )
                if port.direction is not direction:
                    raise ValueError(
                        f"CHI router port {name}.{port_name} has direction "
                        f"{port.direction.value!r}, expected "
                        f"{direction.value!r}"
                    )
        for hop in self.hops.values():
            receiver = self.routers.get(hop.receiver.dut)
            if (
                receiver is not None
                and hop.receiver.port not in receiver.ingress_ports
            ):
                raise ValueError(
                    f"connection {hop.name!r} terminates on undeclared router "
                    f"ingress {hop.receiver.qualified_name!r}"
                )
            transmitter = self.routers.get(hop.transmitter.dut)
            if (
                transmitter is not None
                and hop.transmitter.port not in transmitter.egress_ports
            ):
                raise ValueError(
                    f"connection {hop.name!r} starts on undeclared router "
                    f"egress {hop.transmitter.qualified_name!r}"
                )
        for name, router in self.routers.items():
            outgoing = {
                hop.transmitter.port: self.paths[hop.name]
                for hop in self.hops.values()
                if hop.transmitter.dut == name
            }
            for route in router.routes:
                path = outgoing.get(route.egress_port)
                if path is None:
                    raise ValueError(
                        f"CHI router route via {name}.{route.egress_port} has "
                        "no outgoing transport connection in this session"
                    )
                unsupported = route.channels - path.channels
                if unsupported:
                    labels = sorted(channel.value for channel in unsupported)
                    raise ValueError(
                        f"CHI router route via {name}.{route.egress_port} "
                        f"allows channels unavailable on its transport "
                        f"connection: {labels!r}"
                    )

    def initial_state(self) -> ChiTransportNetworkState:
        return ChiTransportNetworkState(
            {
                name: path.initial_state()
                for name, path in self.paths.items()
            },
            {
                name: router.initial_state()
                for name, router in self.routers.items()
            },
            {
                name: {channel: () for channel in path.channels}
                for name, path in self.paths.items()
            },
        )

    def is_quiescent(self, state: ChiTransportNetworkState) -> bool:
        if not isinstance(state, ChiTransportNetworkState):
            return False
        return (
            all(
                self.paths[name].is_quiescent(state.paths[name])
                for name in self.paths
            )
            and all(
                self.routers[name].is_quiescent(state.routers[name])
                for name in self.routers
            )
            and all(
                not entries
                for channels in state.lineage_by_connection.values()
                for entries in channels.values()
            )
        )

    def step(
        self,
        state: ChiTransportNetworkState,
        action: ChiTransportNetworkAction,
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        fault = self._state_fault(state)
        if fault is not None:
            return SemanticStep(state, fault=fault)
        if isinstance(action, ChiNetworkEnqueue):
            return self._enqueue(state, action)
        if isinstance(action, ChiNetworkTick):
            return self._tick(state, action)
        if isinstance(action, ChiNetworkCaptureToRouter):
            return self._capture_to_router(state, action)
        if isinstance(action, ChiNetworkRouterToConnection):
            return self._router_to_connection(state, action)
        if isinstance(action, ChiNetworkDrain):
            return self._drain(state, action)
        raise TypeError("unknown CHI transport-network action")

    def peek_delivery(
        self,
        state: ChiTransportNetworkState,
        connection: str,
        channel: ChiChannelKind | None = None,
    ) -> ChiNetworkDelivery | None:
        fault = self._state_fault(state)
        if fault is not None:
            raise ValueError(fault.reason)
        path = self.paths.get(connection)
        if path is None:
            raise KeyError(connection)
        path_state = state.paths[connection]
        captured = path.peek_capture(path_state, channel)
        if captured is None:
            return None
        transfer = captured.transfer
        hop = self.hops[connection]
        lineage = state.lineage_by_connection[connection][
            captured.packet.channel
        ][0]
        evidence = (*lineage, f"{transfer.link}@{transfer.tick}")
        return ChiNetworkDelivery(
            connection,
            hop.transmitter,
            hop.receiver,
            captured.packet,
            captured.resource_plane,
            evidence,
        )

    def _enqueue(
        self,
        state: ChiTransportNetworkState,
        action: ChiNetworkEnqueue,
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        path = self.paths.get(action.connection)
        if path is None:
            return self._unknown_connection(state, action.connection)
        if not path.accepts(action.packet):
            return self._channel_fault(
                state,
                action.connection,
                "/".join(
                    channel.value.upper()
                    for channel in sorted(
                        path.channels, key=lambda item: item.value
                    )
                ),
            )
        child = path.enqueue(
            state.paths[action.connection],
            action.packet,
            resource_plane=action.resource_plane,
        )
        failed = self._child_failure(state, child)
        if failed is not None:
            return failed
        candidate = self._replace_path(
            state,
            action.connection,
            child.state,
            channel=action.packet.channel,
            append_lineage=action.lineage,
        )
        event = ChiNetworkEvent(
            ChiNetworkEventKind.ENQUEUE,
            action.connection,
            packet=action.packet,
            resource_plane=action.resource_plane,
            lineage=action.lineage,
        )
        return SemanticStep(candidate, (event,))

    def _tick(
        self,
        state: ChiTransportNetworkState,
        action: ChiNetworkTick,
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        path = self.paths.get(action.connection)
        if path is None:
            return self._unknown_connection(state, action.connection)
        child = path.tick(
            state.paths[action.connection],
            active=action.active,
        )
        failed = self._child_failure(state, child)
        if failed is not None:
            return failed
        candidate = self._replace_path(
            state, action.connection, child.state
        )
        detail = None if not child.emissions else child.emissions[0]
        return SemanticStep(
            candidate,
            (
                ChiNetworkEvent(
                    ChiNetworkEventKind.LINK_TICK,
                    action.connection,
                    detail=detail,
                ),
            ),
        )

    def _capture_to_router(
        self,
        state: ChiTransportNetworkState,
        action: ChiNetworkCaptureToRouter,
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        if action.connection not in self.paths:
            return self._unknown_connection(state, action.connection)
        delivery = self.peek_delivery(
            state, action.connection, action.channel
        )
        if delivery is None:
            return self._empty_capture(state, action.connection)
        router_name = delivery.receiver.dut
        router = self.routers.get(router_name)
        if router is None:
            return self._fault(
                state,
                "router_binding",
                f"connection {action.connection!r} does not terminate at "
                "a registered router",
            )
        router_child = router.step(
            state.routers[router_name],
            ChiRouterReceive(
                delivery.receiver.port,
                delivery.packet,
                delivery.resource_plane,
                delivery.lineage,
            ),
        )
        failed = self._child_failure(state, router_child)
        if failed is not None:
            return failed
        path = self.paths[action.connection]
        path_child = path.drain(
            state.paths[action.connection],
            channel=delivery.packet.channel,
        )
        failed = self._child_failure(state, path_child)
        if failed is not None:
            return failed
        candidate = self._replace_path_and_router(
            state,
            action.connection,
            path_child.state,
            router_name,
            router_child.state,
            channel=delivery.packet.channel,
            pop_lineage=True,
        )
        return SemanticStep(
            candidate,
            (
                ChiNetworkEvent(
                    ChiNetworkEventKind.ROUTER_ACCEPT,
                    action.connection,
                    node=router_name,
                    packet=delivery.packet,
                    resource_plane=delivery.resource_plane,
                    lineage=delivery.lineage,
                ),
            ),
        )

    def _router_to_connection(
        self,
        state: ChiTransportNetworkState,
        action: ChiNetworkRouterToConnection,
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        path = self.paths.get(action.connection)
        if path is None:
            return self._unknown_connection(state, action.connection)
        hop = self.hops[action.connection]
        router_name = hop.transmitter.dut
        router = self.routers.get(router_name)
        if router is None:
            return self._fault(
                state,
                "router_binding",
                f"connection {action.connection!r} does not start at a "
                "registered router",
            )
        if action.channel is None:
            if len(path.channels) != 1:
                return self._fault(
                    state,
                    "channel_selection",
                    f"multi-channel connection {action.connection!r} "
                    "requires an explicit router-service channel",
                    scope=ConstraintScope.TRANSPORT,
                    location=action.connection,
                )
            channel = next(iter(path.channels))
        else:
            channel = action.channel
            if channel not in path.channels:
                return self._channel_fault(
                    state,
                    action.connection,
                    "/".join(
                        item.value.upper()
                        for item in sorted(
                            path.channels, key=lambda value: value.value
                        )
                    ),
                )
        router_child = router.step(
            state.routers[router_name],
            ChiRouterService(channel, hop.transmitter.port),
        )
        failed = self._child_failure(state, router_child)
        if failed is not None:
            return failed
        if not router_child.emissions:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{router_name}.{channel.value}."
                    f"{hop.transmitter.port}.fifo",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=router.queue_capacity,
                    reason="router has no packet for this connection",
                    location=router_name,
                ),
            )
        routed = router_child.emissions[0]
        if not isinstance(routed, ChiRoutedPacket):
            return self._fault(
                state, "router_emission", "router emitted an invalid packet"
            )
        if not path.accepts(routed.packet):
            return self._channel_fault(
                state,
                action.connection,
                channel.value.upper(),
            )
        path_child = path.enqueue(
            state.paths[action.connection],
            routed.packet,
            resource_plane=routed.resource_plane,
        )
        failed = self._child_failure(state, path_child)
        if failed is not None:
            return failed
        candidate = self._replace_path_and_router(
            state,
            action.connection,
            path_child.state,
            router_name,
            router_child.state,
            channel=channel,
            append_lineage=routed.lineage,
        )
        return SemanticStep(
            candidate,
            (
                ChiNetworkEvent(
                    ChiNetworkEventKind.ROUTER_FORWARD,
                    action.connection,
                    node=router_name,
                    packet=routed.packet,
                    resource_plane=routed.resource_plane,
                    lineage=routed.lineage,
                ),
            ),
        )

    def _drain(
        self,
        state: ChiTransportNetworkState,
        action: ChiNetworkDrain,
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        if action.connection not in self.paths:
            return self._unknown_connection(state, action.connection)
        delivery = self.peek_delivery(
            state, action.connection, action.channel
        )
        if delivery is None:
            return self._empty_capture(state, action.connection)
        path = self.paths[action.connection]
        child = path.drain(
            state.paths[action.connection],
            channel=delivery.packet.channel,
        )
        failed = self._child_failure(state, child)
        if failed is not None:
            return failed
        candidate = self._replace_path(
            state,
            action.connection,
            child.state,
            channel=delivery.packet.channel,
            pop_lineage=True,
        )
        return SemanticStep(
            candidate,
            (
                ChiNetworkEvent(
                    ChiNetworkEventKind.ENDPOINT_DELIVERY,
                    action.connection,
                    node=delivery.receiver.dut,
                    packet=delivery.packet,
                    resource_plane=delivery.resource_plane,
                    lineage=delivery.lineage,
                    detail=delivery,
                ),
            ),
        )

    def _replace_path(
        self,
        state: ChiTransportNetworkState,
        connection: str,
        path_state: ChiNetworkPathState,
        *,
        channel: ChiChannelKind | None = None,
        append_lineage: tuple[str, ...] | None = None,
        pop_lineage: bool = False,
    ) -> ChiTransportNetworkState:
        paths = dict(state.paths)
        paths[connection] = path_state
        lineages = {
            name: dict(channels)
            for name, channels in state.lineage_by_connection.items()
        }
        if (append_lineage is not None or pop_lineage) and channel is None:
            raise ValueError(
                "lineage mutation requires an explicit CHI channel"
            )
        if channel is None:
            return ChiTransportNetworkState(
                paths, state.routers, lineages
            )
        channel = ChiChannelKind(channel)
        entries = lineages[connection][channel]
        if pop_lineage:
            entries = entries[1:]
        if append_lineage is not None:
            entries = (*entries, tuple(append_lineage))
        lineages[connection][channel] = entries
        return ChiTransportNetworkState(paths, state.routers, lineages)

    def _replace_path_and_router(
        self,
        state: ChiTransportNetworkState,
        connection: str,
        path_state: ChiNetworkPathState,
        router: str,
        router_state: ChiStoreForwardRouterState,
        *,
        channel: ChiChannelKind | None = None,
        append_lineage: tuple[str, ...] | None = None,
        pop_lineage: bool = False,
    ) -> ChiTransportNetworkState:
        candidate = self._replace_path(
            state,
            connection,
            path_state,
            channel=channel,
            append_lineage=append_lineage,
            pop_lineage=pop_lineage,
        )
        routers = dict(candidate.routers)
        routers[router] = router_state
        return ChiTransportNetworkState(
            candidate.paths,
            routers,
            candidate.lineage_by_connection,
        )

    def _state_fault(
        self, state: ChiTransportNetworkState
    ) -> SemanticFault | None:
        if not isinstance(state, ChiTransportNetworkState):
            raise TypeError("CHI network requires ChiTransportNetworkState")
        if set(state.paths) != set(self.paths):
            return SemanticFault(
                f"{self.name}.path_state",
                "network state does not cover the resolved connections",
                ConstraintScope.SYSTEM,
                self.name,
            )
        if set(state.routers) != set(self.routers):
            return SemanticFault(
                f"{self.name}.router_state",
                "network state does not cover the registered routers",
                ConstraintScope.SYSTEM,
                self.name,
            )
        if set(state.lineage_by_connection) != set(self.paths):
            return SemanticFault(
                f"{self.name}.lineage_state",
                "network lineage does not cover the resolved connections",
                ConstraintScope.SYSTEM,
                self.name,
            )
        for name, path in self.paths.items():
            path_state = state.paths[name]
            if not isinstance(path_state, path.state_type):
                return SemanticFault(
                    f"{self.name}.{name}.path_state_type",
                    "connection state does not match its transport profile",
                    ConstraintScope.SYSTEM,
                    name,
                )
            lineages = state.lineage_by_connection[name]
            if set(lineages) != path.channels:
                return SemanticFault(
                    f"{self.name}.{name}.lineage_channels",
                    "connection lineage does not cover its enabled channels",
                    ConstraintScope.SYSTEM,
                    name,
                )
            if any(
                any(
                    not isinstance(item, str) or not item
                    for item in lineage
                )
                for entries in lineages.values()
                for lineage in entries
            ):
                return SemanticFault(
                    f"{self.name}.{name}.lineage_value",
                    "connection lineage contains an invalid evidence label",
                    ConstraintScope.SYSTEM,
                    name,
                )
            counts = path.live_packet_counts(path_state)
            for channel in path.channels:
                expected = counts[channel]
                observed = len(lineages[channel])
                if observed != expected:
                    return SemanticFault(
                        f"{self.name}.{name}."
                        f"{channel.value}.lineage_depth",
                        "connection channel lineage count does not match "
                        "live packets",
                        ConstraintScope.SYSTEM,
                        name,
                    )
        for name, router_state in state.routers.items():
            if not isinstance(router_state, ChiStoreForwardRouterState):
                return SemanticFault(
                    f"{self.name}.{name}.router_state_type",
                    "router state does not match the registered router",
                    ConstraintScope.SYSTEM,
                    name,
                )
        return None

    @staticmethod
    def _child_failure(state, child):
        if child.blocked is not None:
            return SemanticStep(state, blocked=child.blocked)
        if child.fault is not None:
            return SemanticStep(state, fault=child.fault)
        return None

    def _unknown_connection(
        self, state: ChiTransportNetworkState, connection: str
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        return self._fault(
            state,
            "unknown_connection",
            f"unknown CHI transport connection {connection!r}",
        )

    def _channel_fault(
        self,
        state: ChiTransportNetworkState,
        connection: str,
        expected: str,
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        return self._fault(
            state,
            "channel",
            f"connection {connection!r} requires {expected} traffic",
            scope=ConstraintScope.TRANSPORT,
            location=connection,
        )

    @staticmethod
    def _empty_capture(
        state: ChiTransportNetworkState,
        connection: str,
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        return SemanticStep(
            state,
            blocked=ResourceDemand(
                f"{connection}.receiver_capture",
                ConstraintScope.TRANSPORT,
                available=0,
                reason="transport receiver has no captured protocol flit",
                location=connection,
            ),
        )

    def _fault(
        self,
        state: ChiTransportNetworkState,
        suffix: str,
        reason: str,
        *,
        scope: ConstraintScope = ConstraintScope.SYSTEM,
        location: str = "",
    ) -> SemanticStep[ChiTransportNetworkState, ChiNetworkEvent]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                scope,
                location or self.name,
            ),
        )


__all__ = [
    "ChiNetworkCaptureToRouter",
    "ChiNetworkDelivery",
    "ChiNetworkDrain",
    "ChiNetworkEnqueue",
    "ChiNetworkEvent",
    "ChiNetworkEventKind",
    "ChiNetworkRouterToConnection",
    "ChiNetworkTick",
    "ChiTransportNetworkAction",
    "ChiTransportNetworkSession",
    "ChiTransportNetworkState",
]
