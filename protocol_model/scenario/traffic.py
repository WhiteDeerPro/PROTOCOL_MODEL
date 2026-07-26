"""Reproducible protocol-legal canonical-event traffic for scenarios.

The controller owns a private :class:`InterfaceSession` state and a caller-supplied
random-number generator.  It only samples offers whose event kind is sourced by
the configured role, then lets the protocol's :class:`EventSchema` complete
and validate the event. Peer events must also be observed so monitor state
continues to describe the complete interface history.

``TrafficSourceHarness`` deliberately combines the controller with an idle
source ``VirtualDut``.  The DUT contributes a concrete module/port boundary;
the scenario controller contributes stimulus.  Random scheduling therefore
does not become hidden backend behavior.  This module produces canonical
events and system actions, not raw RTL pin waveforms; a later observation or
driver adapter may project the same trace onto pins and cycles.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Iterable

from protocol_model.interface import (
    InterfaceProtocol,
    InterfaceSession,
    InterfaceSessionState,
    InterfaceTrace,
)
from protocol_model.semantics import (
    CanonicalEvent,
    EventOffer,
    SemanticStep,
)
from protocol_model.system import (
    SystemAction,
    SystemEvent,
    SystemSession,
    SystemSessionState,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.recipes.empty import build_idle_source_vdut


class NoEnabledTraffic(RuntimeError):
    """The configured source role currently has no legal outgoing event."""


@dataclass(frozen=True)
class TrafficDrive:
    """One controller-selected action and its complete system transition."""

    action: SystemAction
    transition: SemanticStep[SystemSessionState, SystemEvent]


class RandomTrafficController:
    """Sample reproducible events for one role of one interface connection.

    Reproducibility follows the owned ``random.Random`` state.  ``next_event``
    and ``next_action`` commit the selected source event to the
    controller's private interface state. A caller using ``next_action`` directly
    should subsequently pass peer emissions to ``observe_system_events``.
    ``drive`` is the safer system-level convenience: it applies the action and
    rebuilds the controller state from the events the ``SystemSession``
    actually accepted, including a partially accepted faulting transition.
    """

    def __init__(
        self,
        protocol: InterfaceProtocol,
        role: str,
        rng: Random,
        *,
        origin: VirtualDutPortRef | None = None,
        connection_name: str | None = None,
    ) -> None:
        if not isinstance(protocol, InterfaceProtocol):
            raise TypeError("traffic controller requires an InterfaceProtocol")
        if role not in protocol.roles:
            raise ValueError(
                f"traffic controller role {role!r} is not in protocol "
                f"{protocol.name!r}"
            )
        if not isinstance(rng, Random):
            raise TypeError("traffic controller requires random.Random")
        if origin is not None and not isinstance(origin, VirtualDutPortRef):
            raise TypeError("traffic controller origin must be a VirtualDutPortRef")
        if connection_name is not None and (
            not isinstance(connection_name, str) or not connection_name
        ):
            raise ValueError(
                "traffic controller connection name must be non-empty"
            )

        outgoing = frozenset(
            event_kind.schema.name
            for event_kind in protocol.event_kinds.values()
            if event_kind.source_role == role
        )
        if not outgoing:
            raise ValueError(
                f"protocol role {role!r} has no outgoing event kinds"
            )

        self.protocol = protocol
        self.role = role
        self.rng = rng
        self.origin = origin
        self.connection_name = connection_name
        self.outgoing_event_kinds = outgoing
        self.interface_session: InterfaceSession = protocol.open_session()
        self._state = self.interface_session.initial_state()
        self._events: list[CanonicalEvent] = []

    @property
    def state(self) -> InterfaceSessionState:
        return self._state

    def enabled_offers(
        self,
        *,
        kind: str | None = None,
        offer: EventOffer | None = None,
    ) -> tuple[EventOffer, ...]:
        """Return enabled offers sourced by this controller's protocol role."""

        if kind is not None and offer is not None and kind != offer.kind:
            raise ValueError("kind and offer select different event kinds")
        selected_kind = offer.kind if offer is not None else kind
        if selected_kind is not None:
            try:
                event_kind = self.protocol.event_kind_for(selected_kind)
            except KeyError as error:
                raise ValueError(
                    f"unknown protocol event kind {selected_kind!r}"
                ) from error
            if event_kind.source_role != self.role:
                return ()

        candidates: list[EventOffer] = []
        for candidate in self.interface_session.event_offers(self._state):
            event_kind = self.protocol.event_kind_for(candidate.kind)
            if event_kind.source_role != self.role:
                continue
            if selected_kind is not None and candidate.kind != selected_kind:
                continue
            merged = candidate if offer is None else candidate.merge(offer)
            if merged is not None:
                candidates.append(merged)
        return tuple(candidates)

    def next_event(
        self,
        *,
        kind: str | None = None,
        offer: EventOffer | None = None,
    ) -> CanonicalEvent:
        """Generate and commit one currently enabled source-role event."""

        candidates = self.enabled_offers(kind=kind, offer=offer)
        if not candidates:
            requested = offer.kind if offer is not None else kind
            subject = "any event" if requested is None else requested
            raise NoEnabledTraffic(
                f"role {self.role!r} has no enabled outgoing offer for "
                f"{subject!r}"
            )
        selected = self.rng.choice(candidates)
        event = self.protocol.generate_event(selected, self.rng)
        self.observe(event)
        return event

    def next_action(
        self,
        *,
        kind: str | None = None,
        offer: EventOffer | None = None,
        origin: VirtualDutPortRef | None = None,
    ) -> SystemAction:
        """Generate one event and wrap it as a concrete ``SystemAction``."""

        selected_origin = self.origin if origin is None else origin
        if selected_origin is None:
            raise ValueError(
                "traffic controller requires an origin for SystemAction"
            )
        if not isinstance(selected_origin, VirtualDutPortRef):
            raise TypeError("traffic action origin must be a VirtualDutPortRef")
        return SystemAction(
            selected_origin,
            self.next_event(kind=kind, offer=offer),
        )

    def observe(self, event: CanonicalEvent) -> CanonicalEvent:
        """Commit one source or peer event to the private interface session."""

        if not isinstance(event, CanonicalEvent):
            raise TypeError("traffic controller can only observe CanonicalEvent")
        transition = self.interface_session.step(self._state, event)
        if transition.fault is not None:
            raise ValueError(
                f"traffic controller rejected {event.kind!r}: "
                f"{transition.fault.rule}: {transition.fault.reason}"
            )
        if len(transition.emissions) != 1:
            raise RuntimeError(
                "InterfaceSession accepted an event without one normalized emission"
            )
        accepted = transition.emissions[0]
        self._state = transition.state
        self._events.append(accepted)
        return accepted

    def observe_system_events(
        self,
        events: Iterable[SystemEvent],
        *,
        connection_name: str | None = None,
        include_local: bool = False,
    ) -> tuple[CanonicalEvent, ...]:
        """Observe accepted events from one bound system connection.

        The default skips events emitted by ``origin`` because
        ``next_action`` already committed that source event.  Set
        ``include_local=True`` when rebuilding from a pre-action state.
        """

        selected_connection = self._selected_connection_name(connection_name)
        accepted: list[CanonicalEvent] = []
        for located in events:
            if not isinstance(located, SystemEvent):
                raise TypeError(
                    "traffic controller requires SystemEvent observations"
                )
            if located.connection != selected_connection:
                continue
            if (
                not include_local
                and self.origin is not None
                and located.source == self.origin
            ):
                continue
            accepted.append(self.observe(located.event))
        return tuple(accepted)

    def drive(
        self,
        system_session: SystemSession,
        state: SystemSessionState,
        *,
        kind: str | None = None,
        offer: EventOffer | None = None,
        connection_name: str | None = None,
    ) -> TrafficDrive:
        """Select one source action and execute it against a ``SystemSession``.

        The controller must initially agree with the selected connection.
        After execution, its private state is reconstructed from the events
        the system actually accepted.  This also handles a system fault after
        a valid prefix without pretending that the whole prefix rolled back.
        """

        if not isinstance(system_session, SystemSession):
            raise TypeError("traffic drive requires a SystemSession")
        if not isinstance(state, SystemSessionState):
            raise TypeError("traffic drive requires a SystemSessionState")
        selected_connection = self._selected_connection_name(connection_name)
        self._require_system_binding(
            system_session, state, selected_connection
        )

        before_state = self._state
        before_event_count = len(self._events)
        action = self.next_action(kind=kind, offer=offer)
        transition = system_session.step(state, action)

        self._state = before_state
        del self._events[before_event_count:]
        self.observe_system_events(
            transition.emissions,
            connection_name=selected_connection,
            include_local=True,
        )
        system_connection_state = transition.state.connection_states[
            selected_connection
        ]
        if self._state != system_connection_state:
            raise RuntimeError(
                "traffic controller and SystemSession interface states diverged"
            )
        return TrafficDrive(action, transition)

    def trace(self) -> InterfaceTrace:
        """Return the complete source-and-peer history observed so far."""

        return InterfaceTrace(tuple(self._events), self._state.causal_edges)

    def is_quiescent(self) -> bool:
        return self.interface_session.is_quiescent(self._state)

    def _selected_connection_name(self, override: str | None) -> str:
        selected = self.connection_name if override is None else override
        if selected is None:
            raise ValueError(
                "traffic controller requires a connection name for "
                "system observation"
            )
        if not isinstance(selected, str) or not selected:
            raise ValueError(
                "traffic controller connection name must be non-empty"
            )
        return selected

    def _require_system_binding(
        self,
        system_session: SystemSession,
        state: SystemSessionState,
        connection_name: str,
    ) -> None:
        if self.origin is None:
            raise ValueError("traffic controller requires an origin for drive")
        connections = system_session.system.spec.connections
        if connection_name not in connections:
            raise ValueError(
                f"system has no connection {connection_name!r}"
            )
        connection = connections[connection_name]
        if connection.protocol is not self.protocol:
            raise ValueError(
                "traffic controller and system connection must share one "
                "InterfaceProtocol instance"
            )
        if connection.endpoints.get(self.role) != self.origin:
            raise ValueError(
                f"traffic controller origin {self.origin.qualified_name!r} "
                f"is not role {self.role!r} on connection "
                f"{connection_name!r}"
            )
        if connection_name not in state.connection_states:
            raise ValueError(
                f"system state has no connection {connection_name!r}"
            )
        if state.connection_states[connection_name] != self._state:
            raise ValueError(
                "traffic controller is not synchronized with the system "
                "connection"
            )


@dataclass(frozen=True)
class TrafficSourceHarness:
    """An idle source module paired with its scenario-owned controller."""

    virtual_dut: VirtualDut
    controller: RandomTrafficController

    @property
    def origin(self) -> VirtualDutPortRef:
        assert self.controller.origin is not None
        return self.controller.origin


def assemble_random_traffic_source(
    name: str,
    protocol: InterfaceProtocol,
    role: str,
    rng: Random,
    *,
    port_name: str = "link",
    connection_name: str | None = None,
    capability: object | None = None,
) -> TrafficSourceHarness:
    """Pair an idle source ``VirtualDut`` with an external random controller."""

    virtual_dut = build_idle_source_vdut(
        name,
        protocol,
        role,
        port_name=port_name,
        capability=capability,
    )
    origin = VirtualDutPortRef(name, port_name)
    controller = RandomTrafficController(
        protocol,
        role,
        rng,
        origin=origin,
        connection_name=connection_name,
    )
    return TrafficSourceHarness(virtual_dut, controller)


__all__ = [
    "NoEnabledTraffic",
    "RandomTrafficController",
    "TrafficDrive",
    "TrafficSourceHarness",
    "assemble_random_traffic_source",
]
