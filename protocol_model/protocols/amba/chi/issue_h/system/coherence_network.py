"""Packet-network scheduler for the CHI coherence participant model.

The participant session owns coherence state.  The transport-network session
owns hops, routers, and link activation.  This module only commits moves
between those boundaries.  One participant transition can emit several
packets, so its output is saved atomically as an explicit egress batch and
admitted to the network one packet at a time.

The current feature set includes clean ReadShared/ReadUnique, clean- and
restricted shared-dirty-peer CleanUnique, the UD ReadUnique owner-transfer
path, clean Evict, the MESI no-SharedDirty downgrade path, explicit dirty
WriteBackFull, clean WriteEvictFull, and the two Home-selected
WriteEvictOrEvict outcomes.  It also schedules Home P-Credit grants and
credited requester reissue for one successful clean ReadUnique Retry cycle.
Retry cancellation and error composition, general shared-dirty ownership,
automatic victim selection, forwarding snoops, and a cycle-accurate Network
Interface remain separate extensions.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Callable

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
from protocol_model.system.topology.model import VirtualDutPortRef
from protocol_model.virtual_dut.boundary import TransportDirection

from ..participants import ChiParticipantBinding
from ..representation import ChiChannelKind, ChiNetworkPacket
from .coherence import (
    ChiCoherenceInvariantMonitor,
    ChiCoherenceSession,
    ChiCoherenceState,
    ChiDeliverCoherencePacket,
    ChiGrantCoherentHomePCredit,
    ChiRetryCoherentRequest,
    ChiSubmitCleanUnique,
    ChiSubmitCoherentRead,
    ChiSubmitEvict,
    ChiSubmitMakeUnique,
    ChiSubmitWriteEvictOrEvict,
    ChiSubmitWriteEvictFull,
    ChiSubmitWriteBackFull,
    ChiWriteUniqueCacheLine,
)
from .network import (
    ChiNetworkCaptureToRouter,
    ChiNetworkDrain,
    ChiNetworkEnqueue,
    ChiNetworkEvent,
    ChiNetworkRouterToConnection,
    ChiNetworkTick,
    ChiTransportNetworkSession,
    ChiTransportNetworkState,
)
from .progress import (
    ChiCoherenceProgress,
    ChiLineWakeup,
    _project_chi_coherence_progress,
    _project_chi_line_wakeups,
)
from .resolved import ResolvedChiSystem


@dataclass(frozen=True)
class ChiAdvanceCoherenceNetwork:
    """Commit at most one enabled internal move.

    ``candidate=None`` uses the reference round-robin policy.  A named
    candidate selects exactly one public scheduler move, which lets a
    scenario hold an unrelated hop without editing scheduler state.
    """

    candidate: str | None = None

    def __post_init__(self) -> None:
        if self.candidate is not None and not isinstance(
            self.candidate, str
        ):
            raise TypeError("CHI scheduler candidate name must be a string")
        if self.candidate == "":
            raise ValueError("CHI scheduler candidate name must be non-empty")


ChiCoherenceNetworkAction = (
    ChiSubmitCoherentRead
    | ChiSubmitCleanUnique
    | ChiSubmitMakeUnique
    | ChiSubmitEvict
    | ChiSubmitWriteBackFull
    | ChiSubmitWriteEvictFull
    | ChiSubmitWriteEvictOrEvict
    | ChiWriteUniqueCacheLine
    | ChiAdvanceCoherenceNetwork
)


@dataclass(frozen=True)
class ChiPendingCoherenceEgressBatch:
    """Output of one participant transition awaiting network admission.

    The empty value is the stable no-pending-output sentinel.  ``len(batch)``
    reports packets still awaiting admission, which keeps scheduler state
    directly inspectable without using ``None``.
    """

    participant: str = ""
    packets: tuple[ChiNetworkPacket, ...] = ()
    lineage: tuple[str, ...] = ()
    cursor: int = 0

    def __post_init__(self) -> None:
        packets = tuple(self.packets)
        lineage = tuple(self.lineage)
        if not packets:
            if (
                type(self.participant) is not str
                or self.participant
                or lineage
                or type(self.cursor) is not int
                or self.cursor
            ):
                raise ValueError("empty CHI egress batch carries no metadata")
        else:
            if not isinstance(self.participant, str) or not self.participant:
                raise ValueError("CHI egress batch requires a participant")
            if any(not isinstance(item, ChiNetworkPacket) for item in packets):
                raise TypeError("CHI egress batch requires network packets")
            if any(not isinstance(item, str) or not item for item in lineage):
                raise ValueError("CHI egress lineage entries must be non-empty")
            if (
                type(self.cursor) is not int
                or not 0 <= self.cursor < len(packets)
            ):
                raise ValueError("CHI egress cursor is outside its batch")
        object.__setattr__(self, "packets", packets)
        object.__setattr__(self, "lineage", lineage)

    def __len__(self) -> int:
        return len(self.packets) - self.cursor

    @property
    def head(self) -> ChiNetworkPacket:
        return self.packets[self.cursor]

    @property
    def remaining(self) -> tuple[ChiNetworkPacket, ...]:
        return self.packets[self.cursor :]

    def consume_head(self) -> "ChiPendingCoherenceEgressBatch":
        next_cursor = self.cursor + 1
        if next_cursor == len(self.packets):
            return ChiPendingCoherenceEgressBatch()
        return replace(self, cursor=next_cursor)


class ChiCoherenceNetworkEventKind(str, Enum):
    ISSUE = "issue"
    PROTOCOL_CREDIT = "protocol_credit"
    RETRY = "retry"
    LOCAL_WRITE = "local_write"
    EGRESS_ENQUEUE = "egress_enqueue"
    NETWORK = "network"
    ENDPOINT_ACCEPT = "endpoint_accept"


@dataclass(frozen=True)
class ChiCoherenceNetworkEvent:
    kind: ChiCoherenceNetworkEventKind
    participant: str = ""
    connection: str = ""
    packet: ChiNetworkPacket | None = None
    produced: tuple[ChiNetworkPacket, ...] = ()
    lineage: tuple[str, ...] = ()
    detail: ChiNetworkEvent | None = None


@dataclass(frozen=True)
class ChiCoherenceNetworkState:
    coherence: ChiCoherenceState
    network: ChiTransportNetworkState
    pending_egress: ChiPendingCoherenceEgressBatch = field(
        default_factory=ChiPendingCoherenceEgressBatch
    )
    scheduler_cursor: int = 0
    committed_microsteps: int = 0


_Candidate = Callable[
    [ChiCoherenceNetworkState],
    SemanticStep[
        ChiCoherenceNetworkState,
        ChiCoherenceNetworkEvent,
    ],
]


class ChiCoherenceNetworkSession(
    SemanticComponent[
        ChiCoherenceNetworkAction,
        ChiCoherenceNetworkState,
        ChiCoherenceNetworkEvent,
    ]
):
    """Join a closed coherence construction to its resolved network."""

    def __init__(
        self,
        resolved: ResolvedChiSystem,
        *,
        name: str | None = None,
        monitor: ChiCoherenceInvariantMonitor | None = None,
    ) -> None:
        if not isinstance(resolved, ResolvedChiSystem):
            raise TypeError("coherence network requires ResolvedChiSystem")
        resolved.require_closed()
        self.resolved = resolved
        self.system = resolved.system
        self.network: ChiTransportNetworkSession = resolved.network
        self.name = name or (
            f"{resolved.system.spec.name}.coherence_network"
        )
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("coherence network requires a name")
        self.coherence = ChiCoherenceSession.from_resolved(
            resolved,
            name=None if name is None else f"{name}.participants",
            monitor=monitor,
        )

        try:
            snoopee_bindings = resolved.role_bindings("snoopee")
        except KeyError:
            snoopee_bindings = ()
        bindings = (
            *resolved.role_bindings("requester"),
            resolved.role_binding("home"),
            *snoopee_bindings,
        )
        by_name = {binding.name: binding for binding in bindings}
        by_node: dict[int, ChiParticipantBinding] = {}
        for binding in by_name.values():
            if len(binding.node_ids) != 1:
                raise ValueError(
                    f"coherence participant {binding.name!r} needs one NodeID"
                )
            node_id = next(iter(binding.node_ids))
            if node_id in by_node:
                raise ValueError(
                    f"coherence participants share NodeID {node_id}"
                )
            by_node[node_id] = binding
        self.binding_by_name = MappingProxyType(by_name)
        self.binding_by_node_id = MappingProxyType(by_node)

        self.route_by_packet_key = MappingProxyType(
            self._collect_routes()
        )
        route_pairs = {
            (connection, channel)
            for (_source, _target, channel), route
            in self.route_by_packet_key.items()
            for connection in route
        }
        self.route_connection_channels = tuple(
            sorted(route_pairs, key=lambda item: (item[0], item[1].value))
        )
        self.route_connections = tuple(
            sorted({connection for connection, _ in route_pairs})
        )
        endpoint_targets: dict[
            tuple[str, ChiChannelKind], set[int]
        ] = {}
        for (_source, target, channel), route in (
            self.route_by_packet_key.items()
        ):
            endpoint_targets.setdefault((route[-1], channel), set()).add(
                target
            )
        self.endpoint_targets = MappingProxyType(
            {
                key: frozenset(targets)
                for key, targets in endpoint_targets.items()
            }
        )
        self.router_duts = frozenset(self.network.routers)
        self._candidates = self._build_candidates()
        self._scheduler_candidates = tuple(
            name for name, _candidate in self._candidates
        )
        if len(set(self._scheduler_candidates)) != len(
            self._scheduler_candidates
        ):
            raise ValueError(
                "CHI coherence scheduler candidate names must be unique"
            )
        self._candidate_by_name = MappingProxyType(
            dict(self._candidates)
        )

    @classmethod
    def from_resolved(
        cls,
        resolved: ResolvedChiSystem,
        *,
        name: str | None = None,
        monitor: ChiCoherenceInvariantMonitor | None = None,
    ) -> "ChiCoherenceNetworkSession":
        return cls(resolved, name=name, monitor=monitor)

    def _collect_routes(
        self,
    ) -> dict[tuple[int, int, ChiChannelKind], tuple[str, ...]]:
        routes: dict[
            tuple[int, int, ChiChannelKind], tuple[str, ...]
        ] = {}
        for feature in self.coherence.enabled_features:
            evidence = self.resolved.capabilities.evidence_by_feature[feature]
            for flow in evidence.flows.values():
                source = self.binding_by_name.get(flow.source)
                target = self.binding_by_name.get(flow.target)
                if source is None or target is None or not flow.connections:
                    raise ValueError(
                        "coherence feature evidence has an unbound flow"
                    )
                source_id = next(iter(source.node_ids))
                target_id = next(iter(target.node_ids))
                key = (source_id, target_id, flow.channel)
                route = tuple(flow.connections)
                previous = routes.get(key)
                if previous is not None and previous != route:
                    raise ValueError(
                        f"CHI coherence packet key {key!r} selects two routes"
                    )
                first = self.network.hops[route[0]]
                last = self.network.hops[route[-1]]
                source_refs = {
                    VirtualDutPortRef(source.dut.name, port.name)
                    for port in source.ports_for(
                        flow.channel, TransportDirection.TRANSMIT
                    )
                }
                target_refs = {
                    VirtualDutPortRef(target.dut.name, port.name)
                    for port in target.ports_for(
                        flow.channel, TransportDirection.RECEIVE
                    )
                }
                if (
                    first.transmitter not in source_refs
                    or last.receiver not in target_refs
                    or any(
                        flow.channel not in self.network.paths[name].channels
                        for name in route
                    )
                ):
                    raise ValueError(
                        f"CHI coherence flow {flow.name!r} has invalid endpoints"
                    )
                if flow.channel is ChiChannelKind.DAT:
                    for connection in route:
                        data_profile = (
                            self.network.paths[connection]
                            .link.profile.data
                        )
                        if (
                            data_profile is None
                            or data_profile.representation.data_width != 512
                        ):
                            raise ValueError(
                                "the current coherence session transports "
                                "one full 512-bit cache line per DAT packet; "
                                f"connection {connection!r} has another "
                                "DAT width"
                            )
                routes[key] = route
        return routes

    def _build_candidates(self) -> tuple[tuple[str, _Candidate], ...]:
        candidates: list[tuple[str, _Candidate]] = [
            ("egress.enqueue", self._enqueue_pending),
            ("home.pcredit_grant", self._grant_pcredit),
        ]
        for node_id in sorted(self.coherence.requester_node_ids):
            candidates.append(
                (
                    f"requester.{node_id}.retry",
                    lambda state, requester=node_id:
                    self._retry_request(state, requester),
                )
            )
        for connection, channel in sorted(
            self.endpoint_targets,
            key=lambda item: (item[0], item[1].value),
        ):
            candidates.append(
                (
                    f"endpoint.{connection}.{channel.value}",
                    lambda state, name=connection, kind=channel:
                    self._accept_endpoint(state, name, kind),
                )
            )
        for connection, channel in self.route_connection_channels:
            hop = self.network.hops[connection]
            if hop.receiver.dut in self.router_duts:
                candidates.append(
                    (
                        f"capture.{connection}.{channel.value}",
                        lambda state, name=connection, kind=channel:
                        self._network_move(
                            state, ChiNetworkCaptureToRouter(name, kind)
                        ),
                    )
                )
            if hop.transmitter.dut in self.router_duts:
                candidates.append(
                    (
                        f"forward.{connection}.{channel.value}",
                        lambda state, name=connection, kind=channel:
                        self._network_move(
                            state, ChiNetworkRouterToConnection(name, kind)
                        ),
                    )
                )
        for connection in self.route_connections:
            candidates.append(
                (
                    f"tick.{connection}",
                    lambda state, name=connection:
                    self._tick(state, name),
                )
            )
        return tuple(candidates)

    def initial_state(self) -> ChiCoherenceNetworkState:
        return ChiCoherenceNetworkState(
            self.coherence.initial_state(),
            self.network.initial_state(),
        )

    @property
    def scheduler_candidates(self) -> tuple[str, ...]:
        """Return stable public names accepted by selective advance."""

        return self._scheduler_candidates

    def is_quiescent(self, state: ChiCoherenceNetworkState) -> bool:
        return (
            isinstance(state, ChiCoherenceNetworkState)
            and not state.pending_egress
            and self.coherence.is_quiescent(state.coherence)
            and self.network.is_quiescent(state.network)
        )

    def project_progress(
        self,
        state: ChiCoherenceNetworkState,
    ) -> ChiCoherenceProgress:
        """Return read-only CHI line holder and endpoint-wait evidence."""

        fault = self._state_fault(state)
        if fault is not None:
            raise ValueError(fault.reason)
        return _project_chi_coherence_progress(self, state)

    def project_wakeups(
        self,
        before: ChiCoherenceNetworkState,
        after: ChiCoherenceNetworkState,
    ) -> tuple[ChiLineWakeup, ...]:
        """Project exact line releases that can wake retained endpoint heads."""

        return _project_chi_line_wakeups(
            self.project_progress(before),
            self.project_progress(after),
        )

    def offers(
        self, state: ChiCoherenceNetworkState
    ) -> tuple[ChiAdvanceCoherenceNetwork, ...]:
        return () if self.is_quiescent(state) else (
            ChiAdvanceCoherenceNetwork(),
        )

    def step(
        self,
        state: ChiCoherenceNetworkState,
        action: ChiCoherenceNetworkAction,
    ) -> SemanticStep[
        ChiCoherenceNetworkState,
        ChiCoherenceNetworkEvent,
    ]:
        fault = self._state_fault(state)
        if fault is not None:
            return SemanticStep(state, fault=fault)
        if isinstance(
            action,
            (
                ChiSubmitCoherentRead,
                ChiSubmitCleanUnique,
                ChiSubmitMakeUnique,
                ChiSubmitEvict,
                ChiSubmitWriteBackFull,
                ChiSubmitWriteEvictFull,
                ChiSubmitWriteEvictOrEvict,
            ),
        ):
            return self._submit(state, action)
        if isinstance(action, ChiWriteUniqueCacheLine):
            return self._write_local(state, action)
        if isinstance(action, ChiAdvanceCoherenceNetwork):
            return self.advance(state, candidate=action.candidate)
        raise TypeError("unknown coherence-network action")

    def _write_local(self, state, action):
        child = self.coherence.step(state.coherence, action)
        failed = self._child_failure(state, child)
        if failed is not None:
            return failed
        if child.emissions:
            return self._fault(
                state,
                "local_write_emission",
                "RN-local cache write unexpectedly emitted a packet",
            )
        binding = self.binding_by_node_id.get(action.request_node_id)
        if binding is None:
            return self._fault(
                state,
                "local_write_binding",
                "local-write RN has no resolved participant binding",
            )
        return SemanticStep(
            replace(state, coherence=child.state),
            (
                ChiCoherenceNetworkEvent(
                    ChiCoherenceNetworkEventKind.LOCAL_WRITE,
                    participant=binding.name,
                    lineage=(f"{binding.name}.local_write",),
                ),
            ),
        )

    def advance(
        self,
        state: ChiCoherenceNetworkState,
        *,
        candidate: str | None = None,
    ) -> SemanticStep[
        ChiCoherenceNetworkState,
        ChiCoherenceNetworkEvent,
    ]:
        """Commit one enabled move, optionally selecting an exact candidate."""

        fault = self._state_fault(state)
        if fault is not None:
            return SemanticStep(state, fault=fault)
        if candidate is not None and not isinstance(candidate, str):
            raise TypeError("CHI scheduler candidate name must be a string")
        if candidate == "":
            raise ValueError("CHI scheduler candidate name must be non-empty")
        if candidate is not None:
            try:
                selected = self._candidate_by_name[candidate]
            except KeyError as error:
                raise ValueError(
                    f"unknown CHI scheduler candidate {candidate!r}"
                ) from error
            if self.is_quiescent(state):
                return SemanticStep(
                    state,
                    blocked=ResourceDemand(
                        f"{self.name}.{candidate}",
                        ConstraintScope.SYSTEM,
                        available=0,
                        reason=(
                            "selected CHI scheduler candidate is not enabled "
                            "in a quiescent state"
                        ),
                        location=self.name,
                    ),
                )
            transition = selected(state)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            if transition.blocked is not None:
                return SemanticStep(state, blocked=transition.blocked)
            index = self.scheduler_candidates.index(candidate)
            committed = replace(
                transition.state,
                scheduler_cursor=(index + 1) % len(self._candidates),
                committed_microsteps=state.committed_microsteps + 1,
            )
            return SemanticStep(committed, transition.emissions)
        if self.is_quiescent(state):
            return SemanticStep(state)
        blocked: list[ResourceDemand] = []
        count = len(self._candidates)
        for offset in range(count):
            index = (state.scheduler_cursor + offset) % count
            transition = self._candidates[index][1](state)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            if transition.blocked is not None:
                blocked.append(transition.blocked)
                continue
            committed = replace(
                transition.state,
                scheduler_cursor=(index + 1) % count,
                committed_microsteps=state.committed_microsteps + 1,
            )
            return SemanticStep(committed, transition.emissions)
        demand = blocked[0] if blocked else ResourceDemand(
            f"{self.name}.enabled_move",
            ConstraintScope.SYSTEM,
            available=0,
            reason="clean CHI scheduler has no enabled move",
            location=self.name,
        )
        return SemanticStep(state, blocked=demand)

    def run_until_quiescent(
        self,
        state: ChiCoherenceNetworkState,
        *,
        max_steps: int = 1024,
    ) -> SemanticRun[
        ChiCoherenceNetworkAction,
        ChiCoherenceNetworkState,
        ChiCoherenceNetworkEvent,
    ]:
        """Run the bounded reference policy; budget exhaustion is inconclusive."""

        if type(max_steps) is not int or max_steps <= 0:
            raise ValueError("CHI scheduler max_steps must be positive")
        action = ChiAdvanceCoherenceNetwork()
        fault = self._state_fault(state)
        if fault is not None:
            return SemanticRun(
                Verdict.FAIL,
                state,
                (),
                violations=(TraceViolation(0, action, fault),),
                state_history=(state,),
            )
        current = state
        history = [state]
        emissions: list[ChiCoherenceNetworkEvent] = []
        for index in range(max_steps):
            if self.is_quiescent(current):
                return SemanticRun(
                    Verdict.PASS,
                    current,
                    tuple(emissions),
                    state_history=tuple(history),
                )
            transition = self.advance(current)
            current = transition.state
            history.append(current)
            emissions.extend(transition.emissions)
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
                reason="clean CHI scheduler exhausted its microstep budget",
                location=self.name,
            ),
        )

    def _submit(self, state, action):
        if state.pending_egress:
            return self._blocked(
                state,
                "pending_egress",
                "the previous participant output is not admitted",
            )
        child = self.coherence.step(state.coherence, action)
        failed = self._child_failure(state, child)
        if failed is not None:
            return failed
        binding = self.binding_by_node_id.get(action.requester_node_id)
        if binding is None:
            return self._fault(
                state, "requester_binding", "requester has no resolved binding"
            )
        lineage = (f"{binding.name}.issue",)
        batch, fault = self._make_batch(binding, child.emissions, lineage)
        if fault is not None:
            return SemanticStep(state, fault=fault)
        candidate = replace(
            state, coherence=child.state, pending_egress=batch
        )
        return SemanticStep(
            candidate,
            (
                ChiCoherenceNetworkEvent(
                    ChiCoherenceNetworkEventKind.ISSUE,
                    participant=binding.name,
                    packet=child.emissions[0] if child.emissions else None,
                    produced=child.emissions,
                    lineage=lineage,
                ),
            ),
        )

    def _grant_pcredit(self, state):
        if state.pending_egress:
            return self._blocked(
                state,
                "pending_egress",
                "Home P-Credit waits for the current egress batch",
            )
        if not state.coherence.home.request_retry.retry_debts:
            return self._blocked(
                state,
                "retry_debt",
                "Home has no RetryAck awaiting P-Credit",
            )
        return self._autonomous_participant(
            state,
            ChiGrantCoherentHomePCredit(),
            self.coherence.home.node_id,
            ChiCoherenceNetworkEventKind.PROTOCOL_CREDIT,
            "pcredit_grant",
        )

    def _retry_request(self, state, requester_node_id):
        if state.pending_egress:
            return self._blocked(
                state,
                "pending_egress",
                "credited retry waits for the current egress batch",
            )
        requester_state = state.coherence.request_nodes[requester_node_id]
        retryable = requester_state.retryable_transaction_ids()
        if not retryable:
            return self._blocked(
                state,
                f"requester.{requester_node_id}.retry",
                "requester has no RetryAck with matching P-Credit",
            )
        return self._autonomous_participant(
            state,
            ChiRetryCoherentRequest(
                requester_node_id,
                retryable[0],
            ),
            requester_node_id,
            ChiCoherenceNetworkEventKind.RETRY,
            f"retry[{retryable[0]}]",
        )

    def _autonomous_participant(
        self,
        state,
        action,
        source_node_id,
        event_kind,
        lineage_suffix,
    ):
        child = self.coherence.step(state.coherence, action)
        failed = self._child_failure(state, child)
        if failed is not None:
            return failed
        binding = self.binding_by_node_id.get(source_node_id)
        if binding is None:
            return self._fault(
                state,
                "autonomous_binding",
                "autonomous participant has no resolved binding",
            )
        lineage = (f"{binding.name}.{lineage_suffix}",)
        batch, fault = self._make_batch(
            binding,
            child.emissions,
            lineage,
        )
        if fault is not None:
            return SemanticStep(state, fault=fault)
        candidate = replace(
            state,
            coherence=child.state,
            pending_egress=batch,
        )
        return SemanticStep(
            candidate,
            (
                ChiCoherenceNetworkEvent(
                    event_kind,
                    participant=binding.name,
                    packet=child.emissions[0] if child.emissions else None,
                    produced=child.emissions,
                    lineage=lineage,
                ),
            ),
        )

    def _enqueue_pending(self, state):
        batch = state.pending_egress
        if not batch:
            return self._blocked(state, "egress_empty", "no egress is pending")
        packet = batch.head
        route = self.route_by_packet_key.get(
            (packet.source_id, packet.target_id, packet.channel)
        )
        if route is None:
            return self._fault(
                state, "egress_route", "packet has no closed clean route"
            )
        connection = route[0]
        lineage = (
            *batch.lineage,
            f"{batch.participant}.egress[{batch.cursor}]",
        )
        child = self.network.step(
            state.network,
            ChiNetworkEnqueue(connection, packet, lineage=lineage),
        )
        failed = self._child_failure(state, child)
        if failed is not None:
            return failed
        detail = child.emissions[0] if child.emissions else None
        return SemanticStep(
            replace(
                state,
                network=child.state,
                pending_egress=batch.consume_head(),
            ),
            (
                ChiCoherenceNetworkEvent(
                    ChiCoherenceNetworkEventKind.EGRESS_ENQUEUE,
                    participant=batch.participant,
                    connection=connection,
                    packet=packet,
                    lineage=lineage,
                    detail=detail,
                ),
            ),
        )

    def _accept_endpoint(self, state, connection, channel):
        delivery = self.network.peek_delivery(
            state.network, connection, channel
        )
        if delivery is None:
            return self._blocked(
                state, f"{connection}.endpoint", "endpoint has no packet"
            )
        targets = self.endpoint_targets[(connection, channel)]
        binding = self.binding_by_node_id.get(delivery.packet.target_id)
        if delivery.packet.target_id not in targets or binding is None:
            if delivery.receiver.dut in self.router_duts:
                return self._blocked(
                    state,
                    "endpoint_not_selected",
                    "packet selects forwarding at the shared node",
                )
            return self._fault(
                state,
                "endpoint_binding",
                "packet does not select the resolved endpoint",
            )
        receive_refs = {
            VirtualDutPortRef(binding.dut.name, port.name)
            for port in binding.ports_for(
                channel, TransportDirection.RECEIVE
            )
        }
        route = self.route_by_packet_key.get(
            (
                delivery.packet.source_id,
                delivery.packet.target_id,
                channel,
            )
        )
        if (
            delivery.receiver not in receive_refs
            or route is None
            or route[-1] != connection
        ):
            return self._fault(
                state, "endpoint_route", "packet arrived on another route"
            )

        participant = self.coherence.step(
            state.coherence,
            ChiDeliverCoherencePacket(delivery.packet),
        )
        failed = self._child_failure(state, participant)
        if failed is not None:
            return failed
        if state.pending_egress and participant.emissions:
            return self._blocked(
                state,
                "participant_serialization",
                "new participant output waits for the current egress batch",
            )
        drain = self.network.step(
            state.network, ChiNetworkDrain(connection, channel)
        )
        failed = self._child_failure(state, drain)
        if failed is not None:
            return failed
        lineage = (*delivery.lineage, f"{binding.name}.accept")
        batch, fault = self._make_batch(
            binding, participant.emissions, lineage
        )
        if fault is not None:
            return SemanticStep(state, fault=fault)
        return SemanticStep(
            replace(
                state,
                coherence=participant.state,
                network=drain.state,
                pending_egress=(
                    batch if batch else state.pending_egress
                ),
            ),
            (
                ChiCoherenceNetworkEvent(
                    ChiCoherenceNetworkEventKind.ENDPOINT_ACCEPT,
                    participant=binding.name,
                    connection=connection,
                    packet=delivery.packet,
                    produced=participant.emissions,
                    lineage=lineage,
                    detail=drain.emissions[0] if drain.emissions else None,
                ),
            ),
        )

    def _make_batch(self, binding, packets, lineage):
        if not packets:
            return ChiPendingCoherenceEgressBatch(), None
        node_id = next(iter(binding.node_ids))
        if any(packet.source_id != node_id for packet in packets):
            return ChiPendingCoherenceEgressBatch(), SemanticFault(
                f"{self.name}.participant_emission",
                f"participant {binding.name!r} emitted another NodeID",
                ConstraintScope.SYSTEM,
                binding.name,
            )
        if any(
            (packet.source_id, packet.target_id, packet.channel)
            not in self.route_by_packet_key
            for packet in packets
        ):
            return ChiPendingCoherenceEgressBatch(), SemanticFault(
                f"{self.name}.participant_route",
                f"participant {binding.name!r} emitted an unrouted packet",
                ConstraintScope.SYSTEM,
                binding.name,
            )
        return (
            ChiPendingCoherenceEgressBatch(
                binding.name, packets, lineage
            ),
            None,
        )

    def _network_move(self, state, action):
        if isinstance(action, ChiNetworkCaptureToRouter):
            delivery = self.network.peek_delivery(
                state.network, action.connection, action.channel
            )
            local_targets = self.endpoint_targets.get(
                (action.connection, action.channel)
            )
            if (
                delivery is not None
                and local_targets is not None
                and delivery.packet.target_id in local_targets
            ):
                return self._blocked(
                    state,
                    "router_not_selected",
                    "packet selects a participant at the shared node",
                )
        child = self.network.step(state.network, action)
        failed = self._child_failure(state, child)
        if failed is not None:
            return failed
        detail = child.emissions[0] if child.emissions else None
        return SemanticStep(
            replace(state, network=child.state),
            (
                ChiCoherenceNetworkEvent(
                    ChiCoherenceNetworkEventKind.NETWORK,
                    connection=action.connection,
                    packet=None if detail is None else detail.packet,
                    lineage=() if detail is None else detail.lineage,
                    detail=detail,
                ),
            ),
        )

    def _tick(self, state, connection):
        child = self.network.step(
            state.network,
            ChiNetworkTick(connection, active=self._has_work(state)),
        )
        failed = self._child_failure(state, child)
        if failed is not None:
            return failed
        detail = child.emissions[0] if child.emissions else None
        return SemanticStep(
            replace(state, network=child.state),
            (
                ChiCoherenceNetworkEvent(
                    ChiCoherenceNetworkEventKind.NETWORK,
                    connection=connection,
                    detail=detail,
                ),
            ),
        )

    def _has_work(self, state) -> bool:
        if state.pending_egress or not self.coherence.is_quiescent(
            state.coherence
        ):
            return True
        if any(
            any(item.depth for item in path.transmitters.values())
            or any(item.depth for item in path.receivers.values())
            for name, path in state.network.paths.items()
            if name in self.route_connections
        ):
            return True
        return any(
            state.network.routers[name].depth for name in self.router_duts
        )

    def _state_fault(self, state) -> SemanticFault | None:
        if not isinstance(state, ChiCoherenceNetworkState):
            raise TypeError("coherence network requires its state")
        if (
            type(state.scheduler_cursor) is not int
            or not 0 <= state.scheduler_cursor < len(self._candidates)
            or type(state.committed_microsteps) is not int
            or state.committed_microsteps < 0
        ):
            return SemanticFault(
                f"{self.name}.scheduler_state",
                "CHI coherence scheduler counters are invalid",
                ConstraintScope.SYSTEM,
                self.name,
            )
        if not isinstance(
            state.pending_egress, ChiPendingCoherenceEgressBatch
        ):
            return SemanticFault(
                f"{self.name}.egress_state",
                "CHI coherence pending egress has another type",
                ConstraintScope.SYSTEM,
                self.name,
            )
        network_fault = self.network._state_fault(state.network)
        if network_fault is not None:
            return network_fault
        if (
            not isinstance(state.coherence, ChiCoherenceState)
            or set(state.coherence.request_nodes)
            != set(self.coherence.request_nodes)
        ):
            return SemanticFault(
                f"{self.name}.participant_state",
                "coherence state does not cover the resolved participants",
                ConstraintScope.SYSTEM,
                self.name,
            )
        profile_fault = self.coherence._profile_state_fault(
            state.coherence
        )
        if profile_fault is not None:
            return profile_fault
        home_state = state.coherence.home
        if (
            len(home_state.pending)
            + len(home_state.pending_copybacks)
            + home_state.request_retry.reserved_count
            > self.coherence.home.transaction_capacity
        ):
            return SemanticFault(
                f"{self.name}.home_retry_capacity",
                "Home active transactions and P-Credit reservations exceed "
                "its real capacity",
                ConstraintScope.SYSTEM,
                self.coherence.home.name,
            )
        if state.pending_egress:
            binding = self.binding_by_name.get(
                state.pending_egress.participant
            )
            if binding is None:
                return SemanticFault(
                    f"{self.name}.egress_owner",
                    "pending egress names an unknown participant",
                    ConstraintScope.SYSTEM,
                    self.name,
                )
            node_id = next(iter(binding.node_ids))
            if any(
                packet.source_id != node_id
                or (
                    packet.source_id,
                    packet.target_id,
                    packet.channel,
                )
                not in self.route_by_packet_key
                for packet in state.pending_egress.remaining
            ):
                return SemanticFault(
                    f"{self.name}.egress_packet",
                    "pending egress contains an unowned or unrouted packet",
                    ConstraintScope.SYSTEM,
                    binding.name,
                )
        return None

    @staticmethod
    def _child_failure(state, transition):
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        if transition.blocked is not None:
            return SemanticStep(state, blocked=transition.blocked)
        return None

    def _blocked(self, state, suffix, reason):
        return SemanticStep(
            state,
            blocked=ResourceDemand(
                f"{self.name}.{suffix}",
                ConstraintScope.SYSTEM,
                available=0,
                reason=reason,
                location=self.name,
            ),
        )

    def _fault(self, state, suffix, reason):
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.SYSTEM,
                self.name,
            ),
        )


__all__ = [
    "ChiAdvanceCoherenceNetwork",
    "ChiCoherenceNetworkAction",
    "ChiCoherenceNetworkEvent",
    "ChiCoherenceNetworkEventKind",
    "ChiCoherenceNetworkSession",
    "ChiCoherenceNetworkState",
    "ChiPendingCoherenceEgressBatch",
]
