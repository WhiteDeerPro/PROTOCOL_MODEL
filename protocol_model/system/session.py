"""Automatic routing and VirtualDut execution for an elaborated SystemProtocol."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any, Mapping

from protocol_model.interface import InterfaceSession, InterfaceSessionState
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.virtual_dut.backend.transition import PortInput
from protocol_model.virtual_dut.backend.advance import ExplicitlyAdvanceableBackend

from .elaboration import ElaboratedSystemProtocol
from .topology.model import VirtualDutPortRef
from .topology.ownership import PortOwnerKind


@dataclass(frozen=True)
class SystemAction:
    """One event emitted by a concrete VirtualDut port into the system."""

    origin: VirtualDutPortRef
    event: CanonicalEvent


@dataclass(frozen=True)
class DutAdvanceAction:
    """Explicitly request progress from one advanceable VirtualDut backend.

    One step has no built-in clock or time unit.  A scenario may interpret it
    as a service opportunity, while a future scheduler can map clock-domain
    progress onto the same backend contract.
    """

    dut: str
    steps: int = 1

    def __post_init__(self) -> None:
        if not self.dut:
            raise ValueError("DUT advance action requires a DUT name")
        if (
            not isinstance(self.steps, int)
            or isinstance(self.steps, bool)
            or self.steps <= 0
        ):
            raise ValueError("DUT advance steps must be positive")


@dataclass(frozen=True)
class SystemEvent:
    index: int
    connection: str
    event_kind: str
    source: VirtualDutPortRef
    destination: VirtualDutPortRef
    event: CanonicalEvent

    def short(self) -> str:
        return (
            f"{self.connection}:{self.source.qualified_name}"
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
    connection_states: Mapping[str, InterfaceSessionState]
    dut_states: Mapping[str, Any]
    connection_event_globals: Mapping[str, tuple[int, ...]]
    events: tuple[SystemEvent, ...] = ()
    causal_edges: tuple[tuple[int, int], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connection_states",
            MappingProxyType(dict(self.connection_states)),
        )
        object.__setattr__(self, "dut_states", MappingProxyType(dict(self.dut_states)))
        object.__setattr__(
            self,
            "connection_event_globals",
            MappingProxyType(dict(self.connection_event_globals)),
        )


class SystemSession(
    SemanticComponent[
        SystemAction | DutAdvanceAction,
        SystemSessionState,
        SystemEvent,
    ]
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
        self.connection_sessions = {
            name: InterfaceSession(connection.protocol)
            for name, connection in system.spec.interface_connections.items()
        }

    def initial_state(self) -> SystemSessionState:
        return SystemSessionState(
            {
                name: session.initial_state()
                for name, session in self.connection_sessions.items()
            },
            {
                name: (
                    dut.backend.initial_state()
                    if dut.backend is not None
                    else None
                )
                for name, dut in self.system.spec.virtual_duts.items()
            },
            {name: () for name in self.system.spec.interface_connections},
        )

    def is_quiescent(self, state: SystemSessionState) -> bool:
        connections_quiescent = all(
            session.is_quiescent(state.connection_states[name])
            for name, session in self.connection_sessions.items()
        )
        duts_quiescent = all(
            dut.backend is None
            or dut.backend.is_quiescent(state.dut_states[name])
            for name, dut in self.system.spec.virtual_duts.items()
        )
        return connections_quiescent and duts_quiescent

    def trace(self, state: SystemSessionState) -> SystemTrace:
        return SystemTrace(state.events, state.causal_edges)

    def step(
        self,
        state: SystemSessionState,
        action: SystemAction | DutAdvanceAction,
    ) -> SemanticStep[SystemSessionState, SystemEvent]:
        connection_states = dict(state.connection_states)
        dut_states = dict(state.dut_states)
        connection_event_globals = dict(state.connection_event_globals)
        events = list(state.events)
        edges = list(state.causal_edges)
        step_events: list[SystemEvent] = []
        queue = deque()

        def snapshot() -> SystemSessionState:
            return SystemSessionState(
                connection_states,
                dut_states,
                connection_event_globals,
                tuple(events),
                tuple(edges),
            )

        def fail(fault: SemanticFault) -> SemanticStep[SystemSessionState, SystemEvent]:
            return SemanticStep(snapshot(), tuple(step_events), fault=fault)

        def block(
            demand: ResourceDemand,
            dut_name: str,
        ) -> SemanticStep[SystemSessionState, SystemEvent]:
            """Reject the entire external step without committing its prefix."""

            location = (
                dut_name
                if not demand.location
                else f"{dut_name}.{demand.location}"
            )
            located = replace(
                demand,
                resource=f"{dut_name}.{demand.resource}",
                location=location,
            )
            return SemanticStep(state, blocked=located)

        def block_connection(
            demand: ResourceDemand,
            connection_name: str,
        ) -> SemanticStep[SystemSessionState, SystemEvent]:
            """Reject an action when an interface monitor cannot admit it."""

            location = (
                connection_name
                if not demand.location
                else f"{connection_name}.{demand.location}"
            )
            located = replace(
                demand,
                resource=f"interface.{connection_name}.{demand.resource}",
                location=location,
            )
            return SemanticStep(state, blocked=located)

        def enqueue_emissions(
            dut_name: str,
            emissions,
            trigger_parents: tuple[int, ...],
        ) -> SemanticFault | None:
            dut = self.system.spec.virtual_duts[dut_name]
            for emission in emissions:
                if emission.port not in dut.ports:
                    return SemanticFault(
                        f"{self.name}.{dut_name}.unknown_output_port",
                        f"VirtualDut emitted through unknown port "
                        f"{emission.port!r}",
                        ConstraintScope.VIRTUAL_DUT,
                        dut_name,
                    )
                queue.append(
                    (
                        VirtualDutPortRef(dut_name, emission.port),
                        replace(emission.event, source=dut_name),
                        trigger_parents,
                    )
                )
            return None

        if isinstance(action, SystemAction):
            queue.append((action.origin, action.event, ()))
        elif isinstance(action, DutAdvanceAction):
            dut = self.system.spec.virtual_duts.get(action.dut)
            if dut is None:
                return fail(
                    SemanticFault(
                        f"{self.name}.unknown_dut",
                        f"unknown VirtualDut {action.dut!r}",
                        ConstraintScope.SYSTEM,
                        action.dut,
                    )
                )
            backend = dut.backend
            if backend is None or not isinstance(
                backend, ExplicitlyAdvanceableBackend
            ):
                return fail(
                    SemanticFault(
                        f"{self.name}.{action.dut}.not_advanceable",
                        f"VirtualDut {action.dut!r} has no explicit "
                        "advance contract",
                        ConstraintScope.VIRTUAL_DUT,
                        action.dut,
                    )
                )
            dut_step = backend.advance(
                dut_states[action.dut], steps=action.steps
            )
            if dut_step.blocked is not None:
                return block(dut_step.blocked, action.dut)
            dut_states[action.dut] = dut_step.state
            if dut_step.fault is not None:
                fault = dut_step.fault
                if not fault.location:
                    fault = replace(fault, location=action.dut)
                return fail(fault)
            emission_fault = enqueue_emissions(
                action.dut, dut_step.emissions, ()
            )
            if emission_fault is not None:
                return fail(emission_fault)
        else:
            raise TypeError(
                "SystemSession requires SystemAction or DutAdvanceAction"
            )

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
            if owner.kind is not PortOwnerKind.INTERFACE_CONNECTION:
                return fail(
                    SemanticFault(
                        f"{self.name}.connection_kind",
                        f"{origin.qualified_name!r} is owned by "
                        f"{owner.qualified_name!r}, not an executable "
                        "InterfaceConnection",
                        ConstraintScope.SYSTEM,
                    )
                )
            connection_name = owner.name
            connection = self.system.spec.interface_connections[
                connection_name
            ]
            origin_port = self.system.spec.virtual_duts[origin.dut].port(origin.port)
            try:
                event_kind = connection.protocol.event_kind_for(event.kind)
            except KeyError:
                return fail(
                    SemanticFault(
                        f"{self.name}.{connection_name}.alphabet",
                        f"event {event.kind!r} is not carried by connection "
                        f"{connection_name!r}",
                        ConstraintScope.INTERFACE,
                        connection_name,
                    )
                )
            if origin_port.role != event_kind.source_role:
                return fail(
                    SemanticFault(
                        f"{self.name}.{connection_name}.direction",
                        f"{origin.qualified_name} has role {origin_port.role!r}; "
                        f"event {event.kind!r} requires source role "
                        f"{event_kind.source_role!r}",
                        ConstraintScope.SYSTEM,
                        origin.qualified_name,
                    )
                )
            destination = connection.endpoints[event_kind.destination_role]

            connection_state = connection_states[connection_name]
            local_index = connection_state.next_index
            transition = self.connection_sessions[connection_name].step(
                connection_state, event
            )
            if transition.blocked is not None:
                return block_connection(transition.blocked, connection_name)
            if transition.fault is not None:
                fault = transition.fault
                if not fault.location:
                    fault = replace(fault, location=connection_name)
                return fail(fault)
            connection_states[connection_name] = transition.state

            globals_for_connection = connection_event_globals[connection_name]
            try:
                local_parents = tuple(
                    globals_for_connection[index]
                    for index in transition.causal_predecessors
                )
            except IndexError:
                return fail(
                    SemanticFault(
                        f"{self.name}.{connection_name}.causal_index",
                        "interface monitor referenced an unavailable predecessor",
                        ConstraintScope.SYSTEM,
                        connection_name,
                    )
                )
            global_index = len(events)
            accepted = replace(
                transition.emissions[0], trace_index=global_index
            )
            located = SystemEvent(
                global_index,
                connection_name,
                event_kind.name,
                origin,
                destination,
                accepted,
            )
            events.append(located)
            step_events.append(located)
            connection_event_globals[connection_name] = (
                globals_for_connection + (global_index,)
            )
            parents = tuple(dict.fromkeys((*local_parents, *trigger_parents)))
            edges.extend((parent, global_index) for parent in parents)

            destination_dut = self.system.spec.virtual_duts[destination.dut]
            backend = destination_dut.backend
            if backend is None:
                continue
            dut_step = backend.accept(
                dut_states[destination.dut],
                PortInput(destination.port, accepted),
            )
            if dut_step.blocked is not None:
                return block(dut_step.blocked, destination.dut)
            dut_states[destination.dut] = dut_step.state
            if dut_step.fault is not None:
                fault = dut_step.fault
                if not fault.location:
                    fault = replace(fault, location=destination.dut)
                return fail(fault)
            emission_fault = enqueue_emissions(
                destination.dut,
                dut_step.emissions,
                (global_index,),
            )
            if emission_fault is not None:
                return fail(emission_fault)

        return SemanticStep(snapshot(), tuple(step_events))
