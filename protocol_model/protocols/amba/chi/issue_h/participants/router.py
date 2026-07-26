"""Finite, field-transparent CHI store-and-forward router behavior."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintKind,
    ConstraintScope,
    ResourceDecl,
    ResourceDemand,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)

from ..representation import ChiChannelKind, ChiNetworkPacket


@dataclass(frozen=True)
class ChiExactNodeRoute:
    """Route selected by an exact target NodeID and protocol channel."""

    target_id: int
    egress_port: str
    channels: frozenset[ChiChannelKind] = frozenset(ChiChannelKind)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.target_id, int)
            or isinstance(self.target_id, bool)
            or self.target_id < 0
        ):
            raise ValueError("CHI route target NodeID must be non-negative")
        if not isinstance(self.egress_port, str) or not self.egress_port:
            raise ValueError("CHI route requires an egress port")
        channels = frozenset(ChiChannelKind(item) for item in self.channels)
        if not channels:
            raise ValueError("CHI route requires at least one channel")
        object.__setattr__(self, "channels", channels)

    def matches(self, packet: ChiNetworkPacket) -> bool:
        return (
            packet.target_id == self.target_id
            and packet.channel in self.channels
        )


@dataclass(frozen=True)
class ChiRouterReceive:
    ingress_port: str
    packet: ChiNetworkPacket
    resource_plane: int = 0
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.ingress_port, str) or not self.ingress_port:
            raise ValueError("CHI router receive requires an ingress port")
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError("CHI router receives ChiNetworkPacket")
        if (
            not isinstance(self.resource_plane, int)
            or isinstance(self.resource_plane, bool)
            or not 0 <= self.resource_plane < 8
        ):
            raise ValueError("CHI router Resource Plane must be in 0..7")
        if (
            self.packet.channel is not ChiChannelKind.REQ
            and self.resource_plane != 0
        ):
            raise ValueError(
                "only REQ traffic can select a Resource Plane"
            )
        lineage = tuple(self.lineage)
        if any(not isinstance(item, str) or not item for item in lineage):
            raise ValueError(
                "CHI router lineage entries must be non-empty strings"
            )
        object.__setattr__(self, "lineage", lineage)


@dataclass(frozen=True)
class ChiRouterService:
    channel: ChiChannelKind
    egress_port: str

    def __post_init__(self) -> None:
        try:
            channel = ChiChannelKind(self.channel)
        except (TypeError, ValueError) as error:
            raise ValueError("CHI router service requires a known channel") from error
        if not isinstance(self.egress_port, str) or not self.egress_port:
            raise ValueError("CHI router service requires an egress port")
        object.__setattr__(self, "channel", channel)


ChiRouterAction = ChiRouterReceive | ChiRouterService
ChiRouterQueueKey = tuple[ChiChannelKind, str]


@dataclass(frozen=True)
class ChiRoutedPacket:
    """One buffered packet with router-private ingress/egress ownership."""

    serial: int
    ingress_port: str
    egress_port: str
    packet: ChiNetworkPacket
    resource_plane: int = 0
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.serial, int)
            or isinstance(self.serial, bool)
            or self.serial < 0
        ):
            raise ValueError("CHI routed packet serial must be non-negative")
        for value, subject in (
            (self.ingress_port, "ingress"),
            (self.egress_port, "egress"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"CHI routed packet requires a non-empty {subject} port"
                )
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError("CHI routed packet requires ChiNetworkPacket")
        if (
            not isinstance(self.resource_plane, int)
            or isinstance(self.resource_plane, bool)
            or not 0 <= self.resource_plane < 8
        ):
            raise ValueError("CHI routed packet Resource Plane must be in 0..7")
        if (
            self.packet.channel is not ChiChannelKind.REQ
            and self.resource_plane != 0
        ):
            raise ValueError(
                "only REQ traffic can select a Resource Plane"
            )
        lineage = tuple(self.lineage)
        if any(not isinstance(item, str) or not item for item in lineage):
            raise ValueError(
                "CHI routed packet lineage entries must be non-empty strings"
            )
        object.__setattr__(self, "lineage", lineage)


@dataclass(frozen=True)
class ChiStoreForwardRouterState:
    queues: Mapping[ChiRouterQueueKey, tuple[ChiRoutedPacket, ...]]
    next_serial: int = 0
    accepted_count: int = 0
    forwarded_count: int = 0

    def __post_init__(self) -> None:
        queues = {
            (ChiChannelKind(channel), egress): tuple(entries)
            for (channel, egress), entries in self.queues.items()
        }
        if any(
            not isinstance(entry, ChiRoutedPacket)
            for entries in queues.values()
            for entry in entries
        ):
            raise TypeError("CHI router queue contains an invalid entry")
        if any(
            entry.packet.channel is not channel
            or entry.egress_port != egress
            for (channel, egress), entries in queues.items()
            for entry in entries
        ):
            raise ValueError(
                "CHI router queue key must match entry channel and egress"
            )
        live_serials = tuple(
            entry.serial for entries in queues.values() for entry in entries
        )
        if len(set(live_serials)) != len(live_serials):
            raise ValueError("CHI router live packet serials must be unique")
        for value, name in (
            (self.next_serial, "next serial"),
            (self.accepted_count, "accepted count"),
            (self.forwarded_count, "forwarded count"),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"CHI router {name} must be non-negative")
        if live_serials and self.next_serial <= max(live_serials):
            raise ValueError("CHI router next serial must exceed live packets")
        if self.next_serial != self.accepted_count:
            raise ValueError("CHI router next serial must match accepted count")
        if self.accepted_count - self.forwarded_count != len(live_serials):
            raise ValueError(
                "CHI router accepted/forwarded counters must match live depth"
            )
        object.__setattr__(self, "queues", MappingProxyType(queues))

    @property
    def depth(self) -> int:
        return sum(len(entries) for entries in self.queues.values())

    def queue_depth(
        self, channel: ChiChannelKind, egress_port: str
    ) -> int:
        return len(self.queues[(ChiChannelKind(channel), egress_port)])


class ChiStoreForwardRouterNode(
    SemanticComponent[
        ChiRouterAction,
        ChiStoreForwardRouterState,
        ChiRoutedPacket,
    ]
):
    """Terminate one hop, buffer a packet, then start a later hop.

    The router resolves only ``channel + TgtID`` and forwards the same packet
    object.  It neither correlates transactions nor creates RetryAck.  A
    caller must commit a service transition only when the downstream TX queue
    accepts its emission. ``ChiTransportNetworkSession`` owns that atomic
    commit boundary when the router is installed in a resolved transport graph.
    """

    def __init__(
        self,
        name: str,
        *,
        ingress_ports: tuple[str, ...],
        egress_ports: tuple[str, ...],
        routes: tuple[ChiExactNodeRoute, ...],
        queue_capacity: int = 1,
    ) -> None:
        if not name:
            raise ValueError("CHI router requires a name")
        ingresses = tuple(ingress_ports)
        egresses = tuple(egress_ports)
        for ports, subject in (
            (ingresses, "ingress"),
            (egresses, "egress"),
        ):
            if not ports:
                raise ValueError(f"CHI router requires an {subject} port")
            if len(set(ports)) != len(ports) or any(
                not isinstance(port, str) or not port for port in ports
            ):
                raise ValueError(
                    f"CHI router {subject} ports must be unique names"
                )
        if set(ingresses) & set(egresses):
            raise ValueError("CHI router ingress and egress ports must differ")
        normalized_routes = tuple(routes)
        if not normalized_routes or any(
            not isinstance(route, ChiExactNodeRoute)
            for route in normalized_routes
        ):
            raise TypeError("CHI router requires exact NodeID routes")
        unknown_egresses = {
            route.egress_port for route in normalized_routes
        } - set(egresses)
        if unknown_egresses:
            raise ValueError(
                "CHI routes reference unknown egress ports: "
                f"{sorted(unknown_egresses)!r}"
            )
        for index, left in enumerate(normalized_routes):
            for right in normalized_routes[index + 1 :]:
                if (
                    left.target_id == right.target_id
                    and left.channels & right.channels
                ):
                    raise ValueError(
                        "CHI routes overlap for target NodeID "
                        f"{left.target_id}"
                    )
        if (
            not isinstance(queue_capacity, int)
            or isinstance(queue_capacity, bool)
            or queue_capacity <= 0
        ):
            raise ValueError("CHI router queue capacity must be positive")
        self.name = name
        self.ingress_ports = ingresses
        self.egress_ports = egresses
        self.routes = normalized_routes
        self.queue_capacity = queue_capacity
        self.semantics = self._build_semantics()

    def _build_semantics(self) -> SemanticFragment:
        resources = tuple(
            ResourceDecl(
                f"{self.name}.{channel.value}.{egress}.fifo",
                ConstraintScope.VIRTUAL_DUT,
                capacity=self.queue_capacity,
                description="accepted CHI packets awaiting explicit service",
                acquired_by=("receive",),
                released_by=("service",),
            )
            for channel in ChiChannelKind
            for egress in self.egress_ports
        )
        return SemanticFragment(
            f"{self.name}.semantics",
            constraints=(
                SemanticConstraint(
                    f"{self.name}.target_route",
                    "each protocol packet selects exactly one egress from "
                    "its channel and target NodeID",
                    ConstraintScope.VIRTUAL_DUT,
                    kind=ConstraintKind.RELATION,
                ),
                SemanticConstraint(
                    f"{self.name}.field_transparency",
                    "ordinary routing preserves the typed protocol payload",
                    ConstraintScope.VIRTUAL_DUT,
                    kind=ConstraintKind.RELATION,
                ),
            ),
            resources=resources,
            sources=("Arm IHI 0050 Issue H B3 Network Layer",),
        )

    def initial_state(self) -> ChiStoreForwardRouterState:
        return ChiStoreForwardRouterState(
            {
                (channel, egress): ()
                for channel in ChiChannelKind
                for egress in self.egress_ports
            }
        )

    def is_quiescent(self, state: ChiStoreForwardRouterState) -> bool:
        return (
            isinstance(state, ChiStoreForwardRouterState)
            and state.depth == 0
        )

    def step(
        self,
        state: ChiStoreForwardRouterState,
        action: ChiRouterAction,
    ) -> SemanticStep[ChiStoreForwardRouterState, ChiRoutedPacket]:
        if not isinstance(state, ChiStoreForwardRouterState):
            raise TypeError("CHI router requires ChiStoreForwardRouterState")
        if isinstance(action, ChiRouterReceive):
            return self._receive(state, action)
        if isinstance(action, ChiRouterService):
            return self._service(state, action)
        raise TypeError("unknown CHI router action")

    def _receive(
        self,
        state: ChiStoreForwardRouterState,
        action: ChiRouterReceive,
    ) -> SemanticStep[ChiStoreForwardRouterState, ChiRoutedPacket]:
        if action.ingress_port not in self.ingress_ports:
            return self._fault(
                state,
                "ingress",
                f"unknown ingress port {action.ingress_port!r}",
            )
        matches = tuple(
            route for route in self.routes if route.matches(action.packet)
        )
        if len(matches) != 1:
            return self._fault(
                state,
                "route",
                "packet does not resolve to exactly one local egress",
            )
        egress = matches[0].egress_port
        key = (action.packet.channel, egress)
        queue = state.queues[key]
        if len(queue) >= self.queue_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.{action.packet.channel.value}."
                    f"{egress}.fifo",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.queue_capacity,
                    reason=(
                        f"router queue for {action.packet.channel.value} "
                        f"toward {egress!r} is full"
                    ),
                    location=self.name,
                ),
            )
        entry = ChiRoutedPacket(
            state.next_serial,
            action.ingress_port,
            egress,
            action.packet,
            action.resource_plane,
            action.lineage,
        )
        queues = dict(state.queues)
        queues[key] = (*queue, entry)
        return SemanticStep(
            ChiStoreForwardRouterState(
                queues,
                state.next_serial + 1,
                state.accepted_count + 1,
                state.forwarded_count,
            )
        )

    def _service(
        self,
        state: ChiStoreForwardRouterState,
        action: ChiRouterService,
    ) -> SemanticStep[ChiStoreForwardRouterState, ChiRoutedPacket]:
        if action.egress_port not in self.egress_ports:
            return self._fault(
                state,
                "egress",
                f"unknown egress port {action.egress_port!r}",
            )
        key = (action.channel, action.egress_port)
        queue = state.queues[key]
        if not queue:
            return SemanticStep(state)
        entry = queue[0]
        queues = dict(state.queues)
        queues[key] = queue[1:]
        return SemanticStep(
            ChiStoreForwardRouterState(
                queues,
                state.next_serial,
                state.accepted_count,
                state.forwarded_count + 1,
            ),
            (entry,),
        )

    def _fault(
        self,
        state: ChiStoreForwardRouterState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiStoreForwardRouterState, ChiRoutedPacket]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.name,
            ),
        )


__all__ = [
    "ChiExactNodeRoute",
    "ChiRoutedPacket",
    "ChiRouterAction",
    "ChiRouterReceive",
    "ChiRouterService",
    "ChiStoreForwardRouterNode",
    "ChiStoreForwardRouterState",
]
