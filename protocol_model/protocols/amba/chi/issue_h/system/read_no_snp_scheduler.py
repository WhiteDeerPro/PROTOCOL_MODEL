"""Internal microstep scheduler for the restricted CHI read runtime."""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticFault,
    SemanticStep,
)
from protocol_model.system.topology.model import VirtualDutPortRef

from ..interface import ChiReadNoSnpComplete
from ..interface import ChiReadNoSnpDirectLedger
from ..participants import (
    ChiDirectHomeAccept,
    ChiDirectHomeNode,
    ChiDirectHomeService,
    ChiParticipantBinding,
)
from ..representation import (
    ChiChannelKind,
    ChiCompDataMessage,
    ChiNetworkPacket,
    ChiReadNoSnpMessage,
)
from .network import (
    ChiNetworkCaptureToRouter,
    ChiNetworkDrain,
    ChiNetworkEnqueue,
    ChiNetworkRouterToConnection,
    ChiNetworkTick,
    ChiTransportNetworkSession,
)
from .read_no_snp_model import (
    ChiReadNoSnpSystemEvent,
    ChiReadNoSnpSystemEventKind,
    ChiReadNoSnpSystemState,
)


class ChiReadNoSnpSchedulerMixin:
    """Commit one enabled cross-component move at a time.

    The concrete session supplies participant components, resolved connection
    names, and the transport-network runtime.  Keeping scheduling here makes
    the deterministic reference policy visible without confusing it with CHI
    link or transaction rules.
    """

    name: str
    network: ChiTransportNetworkSession
    requester: ChiReadNoSnpDirectLedger
    home: ChiDirectHomeNode
    requester_binding: ChiParticipantBinding
    home_binding: ChiParticipantBinding
    request_delivery_connection: str
    data_connection: str
    data_delivery_connection: str
    home_request_ref: VirtualDutPortRef
    requester_data_ref: VirtualDutPortRef
    route_connections: tuple[str, ...]
    route_router_duts: frozenset[str]
    _candidates: tuple[
        tuple[
            str,
            Callable[
                [ChiReadNoSnpSystemState],
                SemanticStep[
                    ChiReadNoSnpSystemState,
                    ChiReadNoSnpSystemEvent,
                ],
            ],
        ],
        ...,
    ]
    is_quiescent: Callable[[ChiReadNoSnpSystemState], bool]

    def _advance(
        self,
        state: ChiReadNoSnpSystemState,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
        if self.is_quiescent(state):
            return SemanticStep(state)
        blocked: list[ResourceDemand] = []
        count = len(self._candidates)
        for offset in range(count):
            index = (state.scheduler_cursor + offset) % count
            _, candidate = self._candidates[index]
            transition = candidate(state)
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
        primary = blocked[0] if blocked else ResourceDemand(
            f"{self.name}.enabled_move",
            ConstraintScope.SYSTEM,
            available=0,
            reason="CHI scheduler found no enabled internal move",
            location=self.name,
        )
        return SemanticStep(state, blocked=primary)

    def _network_candidate(
        self,
        state: ChiReadNoSnpSystemState,
        action: ChiNetworkCaptureToRouter | ChiNetworkRouterToConnection,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
        transition = self.network.step(state.network, action)
        failed = self._network_failure(state, transition)
        if failed is not None:
            return failed
        event = transition.emissions[0] if transition.emissions else None
        return SemanticStep(
            replace(state, network=transition.state),
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.NETWORK,
                    connection=action.connection,
                    packet=None if event is None else event.packet,
                    lineage=() if event is None else event.lineage,
                    detail=event,
                ),
            ),
        )

    def _tick_candidate(
        self,
        state: ChiReadNoSnpSystemState,
        connection: str,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
        action = ChiNetworkTick(
            connection, active=self._has_protocol_work(state)
        )
        transition = self.network.step(state.network, action)
        failed = self._network_failure(state, transition)
        if failed is not None:
            return failed
        event = transition.emissions[0] if transition.emissions else None
        return SemanticStep(
            replace(state, network=transition.state),
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.NETWORK,
                    connection=connection,
                    detail=event,
                ),
            ),
        )

    def _accept_home_delivery(
        self,
        state: ChiReadNoSnpSystemState,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
        delivery = self.network.peek_delivery(
            state.network,
            self.request_delivery_connection,
            ChiChannelKind.REQ,
        )
        if delivery is None:
            return self._blocked_candidate(
                state,
                "home_request",
                "Home has no captured REQ packet",
            )
        if (
            delivery.receiver != self.home_request_ref
            or delivery.packet.channel is not ChiChannelKind.REQ
            or delivery.packet.source_id != self.profile.requester_node_id
            or delivery.packet.target_id != self.profile.home_node_id
            or not isinstance(delivery.packet.message, ChiReadNoSnpMessage)
        ):
            return self._candidate_fault(
                state,
                "home_delivery",
                "captured packet does not match the bound Home REQ port",
            )
        home_step = self.home.step(
            state.home, ChiDirectHomeAccept(delivery.packet.message)
        )
        failed = self._participant_failure(state, home_step)
        if failed is not None:
            return failed
        drain_step = self.network.step(
            state.network,
            ChiNetworkDrain(
                self.request_delivery_connection,
                ChiChannelKind.REQ,
            ),
        )
        failed = self._network_failure(state, drain_step)
        if failed is not None:
            return failed
        lineages = dict(state.home_lineage_by_request)
        lineages[delivery.packet.message.semantic_key] = delivery.lineage
        detail = drain_step.emissions[0] if drain_step.emissions else None
        return SemanticStep(
            replace(
                state,
                network=drain_step.state,
                home=home_step.state,
                home_lineage_by_request=lineages,
            ),
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.HOME_ACCEPT,
                    participant=self.home_binding.name,
                    connection=self.request_delivery_connection,
                    packet=delivery.packet,
                    lineage=delivery.lineage,
                    detail=detail,
                ),
            ),
        )

    def _service_home(
        self,
        state: ChiReadNoSnpSystemState,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
        if not state.home.pending:
            return self._blocked_candidate(
                state, "home_service", "Home has no pending request"
            )
        request = state.home.pending[0]
        lineage = state.home_lineage_by_request.get(request.semantic_key)
        if lineage is None:
            return self._candidate_fault(
                state,
                "home_lineage",
                "Home pending request has no accepted network lineage",
            )
        data_path = self.network.paths[self.data_connection]
        data_state = state.network.paths[self.data_connection]
        if ChiChannelKind.DAT not in data_path.channels:
            return self._candidate_fault(
                state,
                "home_data_path",
                "bound Home DAT egress does not resolve to a DAT path",
            )
        data_tx = data_state.transmitters[ChiChannelKind.DAT]
        data_capacity = data_path.transmitter_capacity_for(
            ChiChannelKind.DAT
        )
        if data_tx.depth >= data_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.home_binding.name}.data_egress_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=data_capacity,
                    reason=(
                        "Home cannot service the request while its DAT "
                        "transmitter queue is full"
                    ),
                    location=self.home_binding.dut.name,
                ),
            )
        home_step = self.home.step(state.home, ChiDirectHomeService())
        failed = self._participant_failure(state, home_step)
        if failed is not None:
            return failed
        if len(home_step.emissions) != 1 or not isinstance(
            home_step.emissions[0], ChiCompDataMessage
        ):
            return self._candidate_fault(
                state,
                "home_emission",
                "direct Home did not emit exactly one CompData",
            )
        response = home_step.emissions[0]
        response_lineage = (*lineage, f"{self.home_binding.name}.service")
        packet = ChiNetworkPacket.data(
            response,
            source_id=self.profile.home_node_id,
            target_id=self.profile.requester_node_id,
        )
        network_step = self.network.step(
            state.network,
            ChiNetworkEnqueue(
                self.data_connection,
                packet,
                lineage=response_lineage,
            ),
        )
        failed = self._network_failure(state, network_step)
        if failed is not None:
            return failed
        lineages = dict(state.home_lineage_by_request)
        del lineages[request.semantic_key]
        detail = network_step.emissions[0] if network_step.emissions else None
        return SemanticStep(
            replace(
                state,
                network=network_step.state,
                home=home_step.state,
                home_lineage_by_request=lineages,
            ),
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.HOME_SERVICE,
                    participant=self.home_binding.name,
                    connection=self.data_connection,
                    packet=packet,
                    lineage=response_lineage,
                    detail=detail,
                ),
            ),
        )

    def _complete_requester_delivery(
        self,
        state: ChiReadNoSnpSystemState,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
        delivery = self.network.peek_delivery(
            state.network,
            self.data_delivery_connection,
            ChiChannelKind.DAT,
        )
        if delivery is None:
            return self._blocked_candidate(
                state,
                "requester_data",
                "Requester has no captured DAT packet",
            )
        if (
            delivery.receiver != self.requester_data_ref
            or delivery.packet.channel is not ChiChannelKind.DAT
            or delivery.packet.source_id != self.profile.home_node_id
            or delivery.packet.target_id != self.profile.requester_node_id
            or not isinstance(delivery.packet.message, ChiCompDataMessage)
        ):
            return self._candidate_fault(
                state,
                "requester_delivery",
                "captured packet does not match the bound Requester DAT port",
            )
        requester_step = self.requester.step(
            state.requester,
            ChiReadNoSnpComplete(delivery.packet.message),
        )
        failed = self._participant_failure(state, requester_step)
        if failed is not None:
            return failed
        if len(requester_step.emissions) != 1:
            return self._candidate_fault(
                state,
                "requester_completion",
                "Requester ledger did not emit exactly one read result",
            )
        drain_step = self.network.step(
            state.network,
            ChiNetworkDrain(
                self.data_delivery_connection,
                ChiChannelKind.DAT,
            ),
        )
        failed = self._network_failure(state, drain_step)
        if failed is not None:
            return failed
        result = requester_step.emissions[0]
        detail = drain_step.emissions[0] if drain_step.emissions else None
        return SemanticStep(
            replace(
                state,
                network=drain_step.state,
                requester=requester_step.state,
            ),
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.COMPLETE,
                    participant=self.requester_binding.name,
                    connection=self.data_delivery_connection,
                    packet=delivery.packet,
                    lineage=delivery.lineage,
                    result=result,
                    detail=detail,
                ),
            ),
        )

    def _has_protocol_work(self, state: ChiReadNoSnpSystemState) -> bool:
        if state.requester.outstanding or state.home.pending:
            return True
        if state.home_lineage_by_request:
            return True
        if any(
            any(item.depth for item in path.transmitters.values())
            or any(item.depth for item in path.receivers.values())
            for name, path in state.network.paths.items()
            if name in self.route_connections
        ):
            return True
        return any(
            state.network.routers[name].depth
            for name in self.route_router_duts
        )

    def _state_fault(
        self, state: ChiReadNoSnpSystemState
    ) -> SemanticFault | None:
        if not isinstance(state, ChiReadNoSnpSystemState):
            raise TypeError("CHI read system session requires its state type")
        if not 0 <= state.scheduler_cursor < len(self._candidates):
            return SemanticFault(
                f"{self.name}.scheduler_cursor",
                "CHI scheduler cursor is outside the candidate set",
                ConstraintScope.SYSTEM,
                self.name,
            )
        if state.committed_microsteps < 0:
            return SemanticFault(
                f"{self.name}.microstep_count",
                "CHI scheduler microstep count must be non-negative",
                ConstraintScope.SYSTEM,
                self.name,
            )
        pending_keys = {item.semantic_key for item in state.home.pending}
        if set(state.home_lineage_by_request) != pending_keys:
            return SemanticFault(
                f"{self.name}.home_lineage",
                "Home pending requests and network lineage keys disagree",
                ConstraintScope.SYSTEM,
                self.home_binding.name,
            )
        return None

    @staticmethod
    def _network_failure(
        state: ChiReadNoSnpSystemState,
        transition: SemanticStep,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent] | None:
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        if transition.blocked is not None:
            return SemanticStep(state, blocked=transition.blocked)
        return None

    @staticmethod
    def _participant_failure(
        state: ChiReadNoSnpSystemState,
        transition: SemanticStep,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent] | None:
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        if transition.blocked is not None:
            return SemanticStep(state, blocked=transition.blocked)
        return None

    def _blocked_candidate(
        self,
        state: ChiReadNoSnpSystemState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
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

    def _candidate_fault(
        self,
        state: ChiReadNoSnpSystemState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiReadNoSnpSystemState, ChiReadNoSnpSystemEvent]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.SYSTEM,
                self.name,
            ),
        )


__all__ = ["ChiReadNoSnpSchedulerMixin"]
