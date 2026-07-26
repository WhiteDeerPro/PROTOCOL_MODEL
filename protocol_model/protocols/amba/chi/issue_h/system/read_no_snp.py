"""Topology-independent composite runtime for the first CHI read slice.

The session closes the gaps between the ReadNoSnp transaction ledger, a
finite direct-Home participant, and the existing transport-network session.
It is intentionally named after the restricted lifecycle it implements; it
does not claim to be a complete CHI node or coherence runtime.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable, Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFault,
    SemanticRun,
    SemanticStep,
    TraceViolation,
    Verdict,
)
from protocol_model.system.contracts.address import AddressWindow
from protocol_model.system.elaboration import ElaboratedSystemProtocol
from protocol_model.system.topology.model import VirtualDutPortRef
from protocol_model.virtual_dut.boundary import TransportDirection

from ..interface import (
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpIssue,
)
from ..participants import (
    ChiDirectHomeNode,
    ChiParticipantBinding,
    ChiStoreForwardRouterNode,
)
from ..representation import ChiChannelKind, ChiNetworkPacket
from .network import (
    ChiNetworkCaptureToRouter,
    ChiNetworkEnqueue,
    ChiNetworkRouterToConnection,
    ChiTransportNetworkSession,
)
from .read_no_snp_model import (
    ChiAdvanceReadNetwork,
    ChiReadNoSnpSystemAction,
    ChiReadNoSnpSystemEvent,
    ChiReadNoSnpSystemEventKind,
    ChiReadNoSnpSystemState,
    ChiSubmitRead,
)
from .read_no_snp_scheduler import ChiReadNoSnpSchedulerMixin


_Candidate = Callable[
    [ChiReadNoSnpSystemState],
    SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent],
]


class ChiReadNoSnpSystemSession(
    ChiReadNoSnpSchedulerMixin,
    SemanticComponent[
        ChiReadNoSnpSystemAction,
        ChiReadNoSnpSystemState,
        ChiReadNoSnpSystemEvent,
    ],
):
    """Execute the restricted direct-Home read over any resolved topology.

    ``direct-Home`` describes the protocol flow: the selected Home accepts the
    initial request and returns one CompData without Retry or CompAck.  It does
    not require a direct physical connection.  Router count and topology come
    entirely from ``ElaboratedSystemProtocol`` and the supplied bindings.

    Each scheduler action commits one microstep.  A blocked candidate is
    skipped so unrelated links or participants can still progress; the cursor
    rotates after every commit to avoid a fixed first-candidate preference.
    """

    def __init__(
        self,
        system: ElaboratedSystemProtocol,
        *,
        requester: ChiParticipantBinding,
        home: ChiParticipantBinding,
        routers: tuple[ChiParticipantBinding, ...] = (),
        transmitter_capacity_by_connection: Mapping[str, int] | None = None,
        network: ChiTransportNetworkSession | None = None,
        authority_window: AddressWindow | None = None,
    ) -> None:
        if not isinstance(system, ElaboratedSystemProtocol):
            raise TypeError("CHI read system session requires elaborated system")
        if system.transport_plan is None:
            raise ValueError("CHI read system session requires transport topology")
        if not isinstance(requester, ChiParticipantBinding):
            raise TypeError("CHI read requester requires participant binding")
        if not isinstance(home, ChiParticipantBinding):
            raise TypeError("CHI direct Home requires participant binding")
        if not isinstance(requester.component, ChiReadNoSnpDirectLedger):
            raise TypeError(
                "CHI read requester binding requires ChiReadNoSnpDirectLedger"
            )
        if not isinstance(home.component, ChiDirectHomeNode):
            raise TypeError("CHI Home binding requires ChiDirectHomeNode")
        if authority_window is not None and not isinstance(
            authority_window, AddressWindow
        ):
            raise TypeError("CHI Home authority requires AddressWindow")

        router_bindings = tuple(routers)
        if any(
            not isinstance(item, ChiParticipantBinding)
            for item in router_bindings
        ):
            raise TypeError("CHI routers require participant bindings")
        bindings = (requester, home, *router_bindings)
        names = tuple(item.name for item in bindings)
        if len(set(names)) != len(names):
            raise ValueError("CHI participant binding names must be unique")
        for binding in bindings:
            self._validate_system_binding(system, binding)

        requester_component = requester.component
        home_component = home.component
        if requester_component.profile != home_component.profile:
            raise ValueError("CHI requester and Home profiles must match")
        profile = requester_component.profile
        if profile.requester_node_id not in requester.node_ids:
            raise ValueError(
                "CHI requester binding does not offer its profile NodeID"
            )
        if profile.home_node_id not in home.node_ids:
            raise ValueError("CHI Home binding does not offer its profile NodeID")

        router_nodes: dict[str, ChiStoreForwardRouterNode] = {}
        for binding in router_bindings:
            component = binding.component
            if not isinstance(component, ChiStoreForwardRouterNode):
                raise TypeError(
                    "CHI router binding requires ChiStoreForwardRouterNode"
                )
            if component.name != binding.dut.name:
                raise ValueError(
                    "current CHI router component name must match its VirtualDut"
                )
            ingress = {
                item.port.name
                for item in binding.ports
                if item.port.direction is TransportDirection.RECEIVE
            }
            egress = {
                item.port.name
                for item in binding.ports
                if item.port.direction is TransportDirection.TRANSMIT
            }
            if ingress != set(component.ingress_ports) or egress != set(
                component.egress_ports
            ):
                raise ValueError(
                    f"CHI router binding {binding.name!r} does not cover its "
                    "component ingress and egress ports"
                )
            if binding.dut.name in router_nodes:
                raise ValueError(
                    f"VirtualDut {binding.dut.name!r} has two router bindings"
                )
            router_nodes[binding.dut.name] = component
        endpoint_router_overlap = {
            requester.dut.name,
            home.dut.name,
        } & set(router_nodes)
        if endpoint_router_overlap:
            raise ValueError(
                "the current CHI read session requires endpoint and router "
                "behaviors on distinct VirtualDuts: "
                f"{sorted(endpoint_router_overlap)!r}"
            )

        self.system = system
        self.name = f"{system.spec.name}.read_no_snp_system"
        self.requester_binding = requester
        self.home_binding = home
        self.router_bindings = router_bindings
        self.requester = requester_component
        self.home = home_component
        self.profile = profile
        self.authority_window = authority_window
        if network is None:
            self.network = ChiTransportNetworkSession(
                system,
                routers=router_nodes,
                transmitter_capacity_by_connection=(
                    transmitter_capacity_by_connection
                ),
            )
        else:
            if not isinstance(network, ChiTransportNetworkSession):
                raise TypeError(
                    "CHI read session network requires "
                    "ChiTransportNetworkSession"
                )
            if network.system is not system:
                raise ValueError(
                    "CHI read session network belongs to another system"
                )
            if transmitter_capacity_by_connection is not None:
                raise ValueError(
                    "a resolved CHI network already owns transmitter capacities"
                )
            if set(network.routers) != set(router_nodes) or any(
                network.routers[name] is not component
                for name, component in router_nodes.items()
            ):
                raise ValueError(
                    "CHI read session router bindings disagree with its "
                    "resolved network"
                )
            self.network = network
        self.router_duts = frozenset(router_nodes)
        for binding in bindings:
            self._validate_bound_port_channels(binding)

        self.request_connection, self.requester_request_ref = (
            self._resolve_participant_connection(
                requester, ChiChannelKind.REQ, TransportDirection.TRANSMIT
            )
        )
        self.request_delivery_connection, self.home_request_ref = (
            self._resolve_participant_connection(
                home, ChiChannelKind.REQ, TransportDirection.RECEIVE
            )
        )
        self.data_connection, self.home_data_ref = (
            self._resolve_participant_connection(
                home, ChiChannelKind.DAT, TransportDirection.TRANSMIT
            )
        )
        self.data_delivery_connection, self.requester_data_ref = (
            self._resolve_participant_connection(
                requester, ChiChannelKind.DAT, TransportDirection.RECEIVE
            )
        )
        request_route = self._resolve_routed_path(
            self.requester_request_ref,
            self.home_request_ref,
            ChiChannelKind.REQ,
            profile.home_node_id,
            router_nodes,
        )
        data_route = self._resolve_routed_path(
            self.home_data_ref,
            self.requester_data_ref,
            ChiChannelKind.DAT,
            profile.requester_node_id,
            router_nodes,
        )
        if (
            request_route[0] != self.request_connection
            or request_route[-1] != self.request_delivery_connection
            or data_route[0] != self.data_connection
            or data_route[-1] != self.data_delivery_connection
        ):
            raise ValueError(
                "CHI participant endpoint connections disagree with routed paths"
            )
        self.request_route_connections = request_route
        self.data_route_connections = data_route
        self.route_channel_pairs = tuple(
            dict.fromkeys(
                (
                    *((name, ChiChannelKind.REQ) for name in request_route),
                    *((name, ChiChannelKind.DAT) for name in data_route),
                )
            )
        )
        self.route_connections = tuple(
            dict.fromkeys(name for name, _ in self.route_channel_pairs)
        )
        self.route_router_duts = frozenset(
            endpoint.dut
            for name in self.route_connections
            for endpoint in (
                self.network.hops[name].transmitter,
                self.network.hops[name].receiver,
            )
            if endpoint.dut in self.router_duts
        )

        self._candidates = self._build_scheduler_candidates(
            (
                ("home.accept", self._accept_home_delivery),
                ("requester.complete", self._complete_requester_delivery),
                ("home.service", self._service_home),
            )
        )

    @classmethod
    def from_resolved(
        cls,
        resolved: "ResolvedChiSystem",
    ) -> "ChiReadNoSnpSystemSession":
        """Open the read runtime only after CHI system closure succeeds."""

        from .capability import CHI_FEATURE_READ_NO_SNP
        from .resolved import ResolvedChiSystem

        if not isinstance(resolved, ResolvedChiSystem):
            raise TypeError(
                "CHI resolved session construction requires ResolvedChiSystem"
            )
        resolved.require_closed()
        resolved.capabilities.require(CHI_FEATURE_READ_NO_SNP)
        routers = tuple(
            binding
            for binding in resolved.forwarding_bindings
            if isinstance(binding.component, ChiStoreForwardRouterNode)
        )
        return cls(
            resolved.system,
            requester=resolved.role_binding("requester"),
            home=resolved.role_binding("home"),
            routers=routers,
            network=resolved.network,
            authority_window=(
                resolved.feature_authority.address_claim.window
            ),
        )

    def _build_scheduler_candidates(
        self,
        participant_candidates: tuple[tuple[str, _Candidate], ...],
    ) -> tuple[tuple[str, _Candidate], ...]:
        """Append route-local router moves and link ticks to node actions."""

        candidates = list(participant_candidates)
        for connection, channel in self.route_channel_pairs:
            hop = self.network.hops[connection]
            if hop.receiver.dut in self.router_duts:
                candidates.append(
                    (
                        f"router.capture.{connection}.{channel.value}",
                        lambda state, name=connection, kind=channel:
                        self._network_candidate(
                            state, ChiNetworkCaptureToRouter(name, kind)
                        ),
                    )
                )
            if hop.transmitter.dut in self.router_duts:
                candidates.append(
                    (
                        f"router.forward.{connection}.{channel.value}",
                        lambda state, name=connection, kind=channel:
                        self._network_candidate(
                            state, ChiNetworkRouterToConnection(name, kind)
                        ),
                    )
                )
        for connection in self.route_connections:
            candidates.append(
                (
                    f"link.tick.{connection}",
                    lambda state, name=connection: self._tick_candidate(
                        state, name
                    ),
                )
            )
        return tuple(candidates)

    @staticmethod
    def _validate_system_binding(
        system: ElaboratedSystemProtocol,
        binding: ChiParticipantBinding,
    ) -> None:
        actual = system.spec.virtual_duts.get(binding.dut.name)
        if actual is None:
            raise ValueError(
                f"CHI participant VirtualDut {binding.dut.name!r} is not in "
                "the system"
            )
        if actual is not binding.dut:
            raise ValueError(
                f"CHI participant {binding.name!r} is bound to a different "
                f"VirtualDut object named {binding.dut.name!r}"
            )

    def _resolve_participant_connection(
        self,
        binding: ChiParticipantBinding,
        channel: ChiChannelKind,
        direction: TransportDirection,
    ) -> tuple[str, VirtualDutPortRef]:
        port = binding.require_one_port(channel, direction)
        reference = VirtualDutPortRef(binding.dut.name, port.name)
        plan = self.system.transport_plan
        assert plan is not None
        if direction is TransportDirection.TRANSMIT:
            matches = plan.outgoing_by_port.get(reference, ())
        else:
            matches = plan.incoming_by_port.get(reference, ())
        if len(matches) != 1:
            raise ValueError(
                f"CHI participant port {reference.qualified_name!r} must "
                f"resolve to exactly one {direction.value} connection"
            )
        connection = matches[0].name
        path = self.network.paths[connection]
        if channel not in path.channels:
            raise ValueError(
                f"CHI participant port {reference.qualified_name!r} is not "
                f"connected to a {channel.value.upper()} path"
            )
        return connection, reference

    def _resolve_routed_path(
        self,
        source: VirtualDutPortRef,
        destination: VirtualDutPortRef,
        channel: ChiChannelKind,
        target_id: int,
        routers: Mapping[str, ChiStoreForwardRouterNode],
    ) -> tuple[str, ...]:
        """Close one required participant path through exact-NodeID routers."""

        plan = self.system.transport_plan
        assert plan is not None
        current = source
        visited: set[VirtualDutPortRef] = set()
        route_connections: list[str] = []
        while True:
            if current in visited:
                raise ValueError(
                    f"CHI {channel.value.upper()} route contains a cycle before "
                    f"reaching {destination.qualified_name}"
                )
            visited.add(current)
            outgoing = plan.outgoing_by_port.get(current, ())
            if len(outgoing) != 1:
                raise ValueError(
                    f"CHI routed port {current.qualified_name!r} must have "
                    "exactly one outgoing connection"
            )
            hop = outgoing[0]
            path = self.network.paths[hop.name]
            if channel not in path.channels:
                raise ValueError(
                    f"CHI routed connection {hop.name!r} does not carry "
                    f"{channel.value.upper()} traffic"
                )
            link_profile = path.link.profile
            if channel is ChiChannelKind.REQ:
                request_profile = link_profile.request
                assert request_profile is not None
                node_id_width = request_profile.representation.node_id_width
                data_width = None
            elif channel is ChiChannelKind.RSP:
                response_profile = link_profile.response
                assert response_profile is not None
                node_id_width = response_profile.representation.node_id_width
                data_width = None
            else:
                data_profile = link_profile.data
                assert data_profile is not None
                node_id_width = data_profile.representation.node_id_width
                data_width = data_profile.representation.data_width
            node_limit = 1 << node_id_width
            node_ids = (
                self.profile.requester_node_id,
                self.profile.home_node_id,
            )
            if any(node_id >= node_limit for node_id in node_ids):
                raise ValueError(
                    f"CHI routed connection {hop.name!r} cannot represent "
                    "the participant NodeIDs"
                )
            if data_width is not None and data_width != self.profile.data_width:
                raise ValueError(
                    f"CHI DAT connection {hop.name!r} has data width "
                    f"{data_width}, expected "
                    f"{self.profile.data_width}"
                )
            route_connections.append(hop.name)
            if hop.receiver == destination:
                return tuple(route_connections)
            router = routers.get(hop.receiver.dut)
            if router is None:
                raise ValueError(
                    f"CHI {channel.value.upper()} path terminates at "
                    f"{hop.receiver.qualified_name!r} before the bound "
                    "participant"
                )
            matches = tuple(
                item
                for item in router.routes
                if item.target_id == target_id and channel in item.channels
            )
            if len(matches) != 1:
                raise ValueError(
                    f"CHI router {router.name!r} does not resolve exactly one "
                    f"{channel.value.upper()} route for NodeID {target_id}"
                )
            current = VirtualDutPortRef(
                hop.receiver.dut, matches[0].egress_port
            )

    def _validate_bound_port_channels(
        self, binding: ChiParticipantBinding
    ) -> None:
        """Close the binding against the currently implemented hop profile."""

        plan = self.system.transport_plan
        assert plan is not None
        for item in binding.ports:
            reference = VirtualDutPortRef(binding.dut.name, item.port.name)
            connections = (
                plan.outgoing_by_port.get(reference, ())
                if item.port.direction is TransportDirection.TRANSMIT
                else plan.incoming_by_port.get(reference, ())
            )
            if len(connections) != 1:
                raise ValueError(
                    f"CHI participant port {reference.qualified_name!r} must "
                    "belong to exactly one directed connection"
                )
            path = self.network.paths[connections[0].name]
            if item.channels != path.channels:
                labels = sorted(value.value for value in item.channels)
                path_labels = "/".join(
                    value.value.upper()
                    for value in sorted(
                        path.channels, key=lambda value: value.value
                    )
                )
                raise ValueError(
                    f"CHI participant port {reference.qualified_name!r} "
                    f"declares channels {labels!r}, but the current hop is "
                    f"{path_labels}"
                )

    def initial_state(self) -> ChiReadNoSnpSystemState:
        return ChiReadNoSnpSystemState(
            self.network.initial_state(),
            self.requester.initial_state(),
            self.home.initial_state(),
        )

    def is_quiescent(self, state: ChiReadNoSnpSystemState) -> bool:
        return (
            isinstance(state, ChiReadNoSnpSystemState)
            and self.requester.is_quiescent(state.requester)
            and self.home.is_quiescent(state.home)
            and not state.home_lineage_by_request
            and self.network.is_quiescent(state.network)
        )

    def offers(
        self, state: ChiReadNoSnpSystemState
    ) -> tuple[ChiAdvanceReadNetwork, ...]:
        if self.is_quiescent(state):
            return ()
        return (ChiAdvanceReadNetwork(),)

    def step(
        self,
        state: ChiReadNoSnpSystemState,
        action: ChiReadNoSnpSystemAction,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
        fault = self._state_fault(state)
        if fault is not None:
            return SemanticStep(state, fault=fault)
        if isinstance(action, ChiSubmitRead):
            return self._submit(state, action)
        if isinstance(action, ChiAdvanceReadNetwork):
            return self._advance(state)
        raise TypeError("unknown CHI ReadNoSnp system action")

    def run_until_quiescent(
        self,
        state: ChiReadNoSnpSystemState,
        *,
        max_steps: int = 256,
    ) -> SemanticRun[
        ChiReadNoSnpSystemAction,
        ChiReadNoSnpSystemState,
        ChiReadNoSnpSystemEvent,
    ]:
        """Run the bounded reference scheduler until every component is quiet.

        Exhausting the bound is inconclusive.  Link ticks represent time
        advancing, so this helper is not a deadlock proof and does not turn a
        lack of completed protocol work into PASS.
        """

        if (
            not isinstance(max_steps, int)
            or isinstance(max_steps, bool)
            or max_steps <= 0
        ):
            raise ValueError("CHI scheduler max_steps must be positive")
        action = ChiAdvanceReadNetwork()
        initial_fault = self._state_fault(state)
        if initial_fault is not None:
            return SemanticRun(
                Verdict.FAIL,
                state,
                (),
                violations=(TraceViolation(0, action, initial_fault),),
                state_history=(state,),
            )
        current = state
        history = [state]
        emissions: list[ChiReadNoSnpSystemEvent] = []
        for index in range(max_steps):
            if self.is_quiescent(current):
                return SemanticRun(
                    Verdict.PASS,
                    current,
                    tuple(emissions),
                    state_history=tuple(history),
                )
            transition = self.step(current, action)
            history.append(transition.state)
            emissions.extend(transition.emissions)
            current = transition.state
            if transition.fault is not None:
                return SemanticRun(
                    Verdict.FAIL,
                    current,
                    tuple(emissions),
                    violations=(
                        TraceViolation(index, action, transition.fault),
                    ),
                    state_history=tuple(history),
                )
            if transition.blocked is not None:
                return SemanticRun(
                    Verdict.INCONCLUSIVE,
                    current,
                    tuple(emissions),
                    state_history=tuple(history),
                    blocked=transition.blocked,
                )
        return SemanticRun(
            Verdict.INCONCLUSIVE,
            current,
            tuple(emissions),
            state_history=tuple(history),
            blocked=ResourceDemand(
                f"{self.name}.scheduler_budget",
                ConstraintScope.SYSTEM,
                available=0,
                capacity=max_steps,
                reason="CHI reference scheduler exhausted its microstep budget",
                location=self.name,
            ),
        )

    def _submit(
        self,
        state: ChiReadNoSnpSystemState,
        action: ChiSubmitRead,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
        if action.requester != self.requester_binding.name:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.unknown_requester",
                    f"unknown CHI requester {action.requester!r}",
                    ConstraintScope.SYSTEM,
                    action.requester,
                ),
            )
        if self.authority_window is not None:
            transfer = AddressWindow(
                action.request.address,
                1 << action.request.size,
            )
            if not self.authority_window.contains(transfer):
                return SemanticStep(
                    state,
                    fault=SemanticFault(
                        f"{self.name}.address_authority",
                        (
                            f"address range {action.request.address:#x}+"
                            f"{transfer.size_bytes:#x} is outside the Home "
                            "authority selected for this construction"
                        ),
                        ConstraintScope.SYSTEM,
                        self.requester_binding.name,
                    ),
                )
        representation_reasons: list[str] = []
        for connection in self.request_route_connections:
            path = self.network.paths[connection]
            request_profile = path.link.profile.request
            assert request_profile is not None
            for reason in request_profile.representation.explain(action.request):
                representation_reasons.append(f"{connection}: {reason}")
        if representation_reasons:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.request_route_representation",
                    "; ".join(representation_reasons),
                    ConstraintScope.EVENT,
                    self.requester_binding.name,
                ),
            )
        requester_step = self.requester.step(
            state.requester, ChiReadNoSnpIssue(action.request)
        )
        failed = self._participant_failure(state, requester_step)
        if failed is not None:
            return failed
        lineage = (f"{self.requester_binding.name}.issue",)
        packet = ChiNetworkPacket.request(
            action.request,
            source_id=self.profile.requester_node_id,
            target_id=self.profile.home_node_id,
        )
        network_step = self.network.step(
            state.network,
            ChiNetworkEnqueue(
                self.request_connection,
                packet,
                lineage=lineage,
            ),
        )
        failed = self._network_failure(state, network_step)
        if failed is not None:
            return failed
        detail = network_step.emissions[0] if network_step.emissions else None
        candidate = replace(
            state,
            network=network_step.state,
            requester=requester_step.state,
        )
        return SemanticStep(
            candidate,
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.ISSUE,
                    participant=self.requester_binding.name,
                    connection=self.request_connection,
                    packet=packet,
                    lineage=lineage,
                    detail=detail,
                ),
            ),
        )


__all__ = [
    "ChiAdvanceReadNetwork",
    "ChiReadNoSnpSystemAction",
    "ChiReadNoSnpSystemEvent",
    "ChiReadNoSnpSystemEventKind",
    "ChiReadNoSnpSystemSession",
    "ChiReadNoSnpSystemState",
    "ChiSubmitRead",
]
