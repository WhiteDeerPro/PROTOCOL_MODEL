"""Automatic routing and VirtualDut execution for an elaborated SystemProtocol."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping

from protocol_model.link import LinkSession, LinkSessionState
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.virtual_dut.backend.transition import PortInput

from .elaboration import ElaboratedSystemProtocol
from .protocol import VirtualDutPortRef


@dataclass(frozen=True)
class SystemAction:
    """One event emitted by a concrete VirtualDut port into the system."""

    origin: VirtualDutPortRef
    event: CanonicalEvent


@dataclass(frozen=True)
class SystemEvent:
    index: int
    link: str
    channel: str
    source: VirtualDutPortRef
    destination: VirtualDutPortRef
    event: CanonicalEvent

    def short(self) -> str:
        return (
            f"{self.link}:{self.source.qualified_name}"
            f"->{self.destination.qualified_name}:{self.event.short()}"
        )


@dataclass(frozen=True)
class SystemTrace:
    events: tuple[SystemEvent, ...]
    causal_edges: tuple[tuple[int, int], ...]

    def predecessors(self, index: int) -> tuple[int, ...]:
        return tuple(before for before, after in self.causal_edges if after == index)

    def causal_graph(self):
        from protocol_model.semantics import CausalGraph

        return CausalGraph.from_edges(range(len(self.events)), self.causal_edges)


@dataclass(frozen=True)
class SystemSessionState:
    link_states: Mapping[str, LinkSessionState]
    dut_states: Mapping[str, Any]
    link_event_globals: Mapping[str, tuple[int, ...]]
    events: tuple[SystemEvent, ...] = ()
    causal_edges: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "link_states", MappingProxyType(dict(self.link_states)))
        object.__setattr__(self, "dut_states", MappingProxyType(dict(self.dut_states)))
        object.__setattr__(
            self,
            "link_event_globals",
            MappingProxyType(dict(self.link_event_globals)),
        )


class SystemSession(
    SemanticComponent[SystemAction, SystemSessionState, SystemEvent]
):
    """Execute a top-level DUT emission and all causally triggered DUT emissions."""

    def __init__(
        self,
        system: ElaboratedSystemProtocol,
        *,
        max_internal_steps: int = 1024,
    ) -> None:
        if max_internal_steps <= 0:
            raise ValueError("max_internal_steps must be positive")
        self.system = system
        self.name = f"{system.spec.name}.system_session"
        self.max_internal_steps = max_internal_steps
        self.link_sessions = {
            name: LinkSession(link.protocol)
            for name, link in system.spec.links.items()
        }

    def initial_state(self) -> SystemSessionState:
        return SystemSessionState(
            {
                name: session.initial_state()
                for name, session in self.link_sessions.items()
            },
            {
                name: (
                    dut.model.initial_state()
                    if dut.model is not None
                    else None
                )
                for name, dut in self.system.spec.virtual_duts.items()
            },
            {name: () for name in self.system.spec.links},
        )

    def is_quiescent(self, state: SystemSessionState) -> bool:
        links_quiescent = all(
            session.is_quiescent(state.link_states[name])
            for name, session in self.link_sessions.items()
        )
        duts_quiescent = all(
            dut.model is None
            or dut.model.is_quiescent(state.dut_states[name])
            for name, dut in self.system.spec.virtual_duts.items()
        )
        return links_quiescent and duts_quiescent

    def trace(self, state: SystemSessionState) -> SystemTrace:
        return SystemTrace(state.events, state.causal_edges)

    def step(
        self, state: SystemSessionState, action: SystemAction
    ) -> SemanticStep[SystemSessionState, SystemEvent]:
        link_states = dict(state.link_states)
        dut_states = dict(state.dut_states)
        link_event_globals = dict(state.link_event_globals)
        events = list(state.events)
        edges = list(state.causal_edges)
        step_events: list[SystemEvent] = []
        queue = deque(((action.origin, action.event, ()),))

        def snapshot() -> SystemSessionState:
            return SystemSessionState(
                link_states,
                dut_states,
                link_event_globals,
                tuple(events),
                tuple(edges),
            )

        def fail(fault: SemanticFault) -> SemanticStep[SystemSessionState, SystemEvent]:
            return SemanticStep(snapshot(), tuple(step_events), fault=fault)

        internal_steps = 0
        while queue:
            internal_steps += 1
            if internal_steps > self.max_internal_steps:
                return fail(
                    SemanticFault(
                        f"{self.name}.internal_step_limit",
                        "VirtualDut emissions did not reach a fixed point",
                        ConstraintScope.SYSTEM,
                    )
                )

            origin, event, trigger_parents = queue.popleft()
            owner = self.system.owner_by_port.get(origin)
            if owner is None:
                return fail(
                    SemanticFault(
                        f"{self.name}.unknown_port",
                        f"unknown VirtualDut port {origin.qualified_name!r}",
                        ConstraintScope.SYSTEM,
                    )
                )
            if not owner.startswith("link:"):
                return fail(
                    SemanticFault(
                        f"{self.name}.boundary_direction",
                        f"{origin.qualified_name!r} is a boundary receive port, not an internal link origin",
                        ConstraintScope.SYSTEM,
                    )
                )
            link_name = owner.split(":", 1)[1]
            link = self.system.spec.links[link_name]
            origin_port = self.system.spec.virtual_duts[origin.dut].port(origin.port)
            try:
                channel = link.protocol.channel_for_event(event.kind)
            except KeyError:
                return fail(
                    SemanticFault(
                        f"{self.name}.{link_name}.alphabet",
                        f"event {event.kind!r} is not carried by link {link_name!r}",
                        ConstraintScope.LINK,
                        link_name,
                    )
                )
            if origin_port.role != channel.source_role:
                return fail(
                    SemanticFault(
                        f"{self.name}.{link_name}.direction",
                        f"{origin.qualified_name} has role {origin_port.role!r}; "
                        f"event {event.kind!r} requires source role {channel.source_role!r}",
                        ConstraintScope.SYSTEM,
                        origin.qualified_name,
                    )
                )
            destination = link.endpoints[channel.destination_role]

            link_state = link_states[link_name]
            local_index = link_state.next_index
            transition = self.link_sessions[link_name].step(link_state, event)
            if transition.fault is not None:
                fault = transition.fault
                if not fault.location:
                    fault = replace(fault, location=link_name)
                return fail(fault)
            link_states[link_name] = transition.state

            globals_for_link = link_event_globals[link_name]
            try:
                local_parents = tuple(
                    globals_for_link[index]
                    for index in transition.causal_predecessors
                )
            except IndexError:
                return fail(
                    SemanticFault(
                        f"{self.name}.{link_name}.causal_index",
                        "link monitor referenced an unavailable predecessor",
                        ConstraintScope.SYSTEM,
                        link_name,
                    )
                )
            global_index = len(events)
            accepted = replace(
                transition.emissions[0], trace_index=global_index
            )
            located = SystemEvent(
                global_index,
                link_name,
                channel.name,
                origin,
                destination,
                accepted,
            )
            events.append(located)
            step_events.append(located)
            link_event_globals[link_name] = globals_for_link + (global_index,)
            parents = tuple(dict.fromkeys((*local_parents, *trigger_parents)))
            edges.extend((parent, global_index) for parent in parents)

            destination_dut = self.system.spec.virtual_duts[destination.dut]
            model = destination_dut.model
            if model is None:
                continue
            dut_step = model.accept(
                dut_states[destination.dut],
                PortInput(destination.port, accepted),
            )
            dut_states[destination.dut] = dut_step.state
            if dut_step.fault is not None:
                fault = dut_step.fault
                if not fault.location:
                    fault = replace(fault, location=destination.dut)
                return fail(fault)
            for emission in dut_step.emissions:
                if emission.port not in destination_dut.ports:
                    return fail(
                        SemanticFault(
                            f"{self.name}.{destination.dut}.unknown_output_port",
                            f"VirtualDut emitted through unknown port {emission.port!r}",
                            ConstraintScope.VIRTUAL_DUT,
                            destination.dut,
                        )
                    )
                queue.append(
                    (
                        VirtualDutPortRef(destination.dut, emission.port),
                        replace(emission.event, source=destination.dut),
                        (global_index,),
                    )
                )

        return SemanticStep(snapshot(), tuple(step_events))
