"""Composite direct-Home ReadNoSnp lifecycle with Request Retry."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticFault,
    SemanticStep,
)
from protocol_model.system.contracts.address import AddressWindow
from protocol_model.system.elaboration import ElaboratedSystemProtocol
from protocol_model.virtual_dut.boundary import TransportDirection

from ..interface import (
    ChiReadNoSnpCancel,
    ChiReadNoSnpObservePCrdGrant,
    ChiReadNoSnpObserveRetryAck,
    ChiReadNoSnpRetry,
    ChiReadNoSnpRetryLedger,
    ChiReadNoSnpRetryLedgerState,
    ChiReadNoSnpRetryPhase,
)
from ..participants import (
    ChiDirectHomeAccept,
    ChiParticipantBinding,
    ChiRetryHomeGrant,
    ChiRetryHomeNode,
    ChiRetryHomeReturn,
    ChiRetryHomeState,
)
from ..representation import (
    ChiChannelKind,
    ChiNetworkPacket,
    ChiPCrdReturnMessage,
    ChiPCrdGrantMessage,
    ChiReadNoSnpMessage,
    ChiRetryAckMessage,
)
from .network import (
    ChiNetworkDrain,
    ChiNetworkEnqueue,
    ChiTransportNetworkSession,
)
from .read_no_snp import ChiReadNoSnpSystemSession, _Candidate
from .read_no_snp_model import (
    ChiReadNoSnpSystemEvent,
    ChiReadNoSnpSystemEventKind,
    ChiReadNoSnpSystemState,
)


@dataclass(frozen=True)
class ChiCancelRead:
    """Cancel one retriable read after its matching P-Credit is available."""

    requester: str
    request_key: int

    def __post_init__(self) -> None:
        if not isinstance(self.requester, str) or not self.requester:
            raise ValueError("CHI cancel action requires a requester name")
        if (
            not isinstance(self.request_key, int)
            or isinstance(self.request_key, bool)
            or self.request_key < 0
        ):
            raise ValueError("CHI cancel action requires a transaction ID")


@dataclass(frozen=True)
class ChiReadNoSnpRetrySystemState(ChiReadNoSnpSystemState):
    """Retry-specific causal evidence beside participant resource state."""

    home_retry_lineages: tuple[tuple[str, ...], ...] = ()
    retry_ack_lineage_by_request: Mapping[
        int, tuple[str, ...]
    ] = field(default_factory=dict)
    pcredit_lineages_by_key: Mapping[
        int, tuple[tuple[str, ...], ...]
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        home_lineages = tuple(
            tuple(lineage) for lineage in self.home_retry_lineages
        )
        retry_ack_lineages = {
            key: tuple(lineage)
            for key, lineage in self.retry_ack_lineage_by_request.items()
        }
        pcredit_lineages = {
            key: tuple(tuple(lineage) for lineage in entries)
            for key, entries in self.pcredit_lineages_by_key.items()
        }
        for lineage in (
            *home_lineages,
            *retry_ack_lineages.values(),
            *(
                item
                for entries in pcredit_lineages.values()
                for item in entries
            ),
        ):
            if any(not isinstance(item, str) or not item for item in lineage):
                raise ValueError("retry lineage labels must be non-empty strings")
        object.__setattr__(self, "home_retry_lineages", home_lineages)
        object.__setattr__(
            self,
            "retry_ack_lineage_by_request",
            MappingProxyType(retry_ack_lineages),
        )
        object.__setattr__(
            self,
            "pcredit_lineages_by_key",
            MappingProxyType(pcredit_lineages),
        )


class ChiReadNoSnpRetrySystemSession(ChiReadNoSnpSystemSession):
    """Close RetryAck, P-Credit, retry/cancel, and completion over topology.

    The profile keeps one Requester and one Home, reuses the original TxnID,
    and uses REQ Resource Plane zero.  Once RetryAck and a matching P-Credit
    are both present, the caller can either let the scheduler reissue the
    request or explicitly cancel it with ``ChiCancelRead``.  Cancellation
    sends PCrdReturn through the ordinary Requester-to-Home REQ route.
    """

    requester: ChiReadNoSnpRetryLedger
    home: ChiRetryHomeNode

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
        if not isinstance(requester.component, ChiReadNoSnpRetryLedger):
            raise TypeError("retry session requires ChiReadNoSnpRetryLedger")
        if not isinstance(home.component, ChiRetryHomeNode):
            raise TypeError("retry session requires ChiRetryHomeNode")
        super().__init__(
            system,
            requester=requester,
            home=home,
            routers=routers,
            transmitter_capacity_by_connection=(
                transmitter_capacity_by_connection
            ),
            network=network,
            authority_window=authority_window,
        )
        self.name = f"{system.spec.name}.read_no_snp_retry_system"
        self.requester = requester.component
        self.home = home.component
        self.response_connection, self.home_response_ref = (
            self._resolve_participant_connection(
                home, ChiChannelKind.RSP, TransportDirection.TRANSMIT
            )
        )
        self.response_delivery_connection, self.requester_response_ref = (
            self._resolve_participant_connection(
                requester, ChiChannelKind.RSP, TransportDirection.RECEIVE
            )
        )
        response_route = self._resolve_routed_path(
            self.home_response_ref,
            self.requester_response_ref,
            ChiChannelKind.RSP,
            self.profile.requester_node_id,
            {
                binding.dut.name: binding.component
                for binding in self.router_bindings
            },
        )
        if (
            response_route[0] != self.response_connection
            or response_route[-1] != self.response_delivery_connection
        ):
            raise ValueError(
                "CHI retry participant RSP connections disagree with route"
            )
        self.response_route_connections = response_route
        self.route_channel_pairs = tuple(
            dict.fromkeys(
                (
                    *self.route_channel_pairs,
                    *((name, ChiChannelKind.RSP) for name in response_route),
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
        participant_candidates: tuple[tuple[str, _Candidate], ...] = (
            ("home.accept", self._accept_home_delivery),
            ("requester.response", self._consume_requester_response),
            ("requester.retry", self._retry_requester),
            ("requester.complete", self._complete_requester_delivery),
            ("home.service", self._service_home),
            ("home.grant", self._grant_home_credit),
        )
        self._candidates = self._build_scheduler_candidates(
            participant_candidates
        )

    @classmethod
    def from_resolved(
        cls,
        resolved: "ResolvedChiSystem",
    ) -> "ChiReadNoSnpRetrySystemSession":
        """Open Retry only from identity/flow/capability-closed evidence."""

        from ..participants import ChiStoreForwardRouterNode
        from .capability import CHI_FEATURE_REQUEST_RETRY
        from .resolved import ResolvedChiSystem

        if not isinstance(resolved, ResolvedChiSystem):
            raise TypeError(
                "CHI resolved session construction requires ResolvedChiSystem"
            )
        resolved.require_closed()
        resolved.capabilities.require(CHI_FEATURE_REQUEST_RETRY)
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

    def initial_state(self) -> ChiReadNoSnpRetrySystemState:
        return ChiReadNoSnpRetrySystemState(
            self.network.initial_state(),
            self.requester.initial_state(),
            self.home.initial_state(),
        )

    def is_quiescent(self, state: ChiReadNoSnpRetrySystemState) -> bool:
        return (
            isinstance(state, ChiReadNoSnpRetrySystemState)
            and self.requester.is_quiescent(state.requester)
            and self.home.is_quiescent(state.home)
            and not state.home_lineage_by_request
            and not state.home_retry_lineages
            and not state.retry_ack_lineage_by_request
            and not state.pcredit_lineages_by_key
            and self.network.is_quiescent(state.network)
        )

    def step(self, state, action):
        fault = self._state_fault(state)
        if fault is not None:
            return SemanticStep(state, fault=fault)
        if isinstance(action, ChiCancelRead):
            return self._cancel_requester(state, action)
        return super().step(state, action)

    def _accept_home_delivery(
        self,
        state: ChiReadNoSnpRetrySystemState,
    ) -> SemanticStep[ChiReadNoSnpRetrySystemState, ChiReadNoSnpSystemEvent]:
        delivery = self.network.peek_delivery(
            state.network,
            self.request_delivery_connection,
            ChiChannelKind.REQ,
        )
        if delivery is None:
            return self._blocked_candidate(
                state, "home_request", "Home has no captured REQ packet"
            )
        message = delivery.packet.message
        if (
            delivery.receiver != self.home_request_ref
            or delivery.packet.channel is not ChiChannelKind.REQ
            or delivery.packet.source_id != self.profile.requester_node_id
            or delivery.packet.target_id != self.profile.home_node_id
            or not isinstance(
                message, (ChiReadNoSnpMessage, ChiPCrdReturnMessage)
            )
            or delivery.resource_plane != 0
        ):
            return self._candidate_fault(
                state,
                "home_delivery",
                "captured packet does not match the retry Home RP0 REQ port",
            )
        home_action = (
            ChiDirectHomeAccept(message)
            if isinstance(message, ChiReadNoSnpMessage)
            else ChiRetryHomeReturn(message)
        )
        home_step = self.home.step(state.home, home_action)
        failed = self._participant_failure(state, home_step)
        if failed is not None:
            return failed

        network_state = state.network
        event_kind = ChiReadNoSnpSystemEventKind.HOME_ACCEPT
        event_packet = delivery.packet
        event_lineage = delivery.lineage
        home_retry_lineages = state.home_retry_lineages
        pending_lineages = dict(state.home_lineage_by_request)
        if isinstance(message, ChiPCrdReturnMessage):
            if home_step.emissions:
                return self._candidate_fault(
                    state,
                    "home_pcredit_return_emission",
                    "PCrdReturn must not produce a protocol response",
                )
            event_kind = ChiReadNoSnpSystemEventKind.HOME_PCREDIT_RETURN
        elif home_step.emissions:
            if len(home_step.emissions) != 1 or not isinstance(
                home_step.emissions[0], ChiRetryAckMessage
            ):
                return self._candidate_fault(
                    state,
                    "home_retry_emission",
                    "retry Home must emit exactly one RetryAck on rejection",
                )
            response = home_step.emissions[0]
            response_lineage = (
                *delivery.lineage,
                f"{self.home_binding.name}.retry_ack",
            )
            response_packet = ChiNetworkPacket.response(
                response,
                source_id=self.profile.home_node_id,
                target_id=self.profile.requester_node_id,
            )
            enqueue = self.network.step(
                network_state,
                ChiNetworkEnqueue(
                    self.response_connection,
                    response_packet,
                    lineage=response_lineage,
                ),
            )
            failed = self._network_failure(state, enqueue)
            if failed is not None:
                return failed
            network_state = enqueue.state
            event_kind = ChiReadNoSnpSystemEventKind.HOME_RETRY_ACK
            event_packet = response_packet
            event_lineage = response_lineage
            home_retry_lineages = (
                *state.home_retry_lineages,
                delivery.lineage,
            )
        else:
            pending_lineages[message.semantic_key] = delivery.lineage

        drain = self.network.step(
            network_state,
            ChiNetworkDrain(
                self.request_delivery_connection,
                ChiChannelKind.REQ,
            ),
        )
        failed = self._network_failure(state, drain)
        if failed is not None:
            return failed
        detail = drain.emissions[0] if drain.emissions else None
        return SemanticStep(
            replace(
                state,
                network=drain.state,
                home=home_step.state,
                home_lineage_by_request=pending_lineages,
                home_retry_lineages=home_retry_lineages,
            ),
            (
                ChiReadNoSnpSystemEvent(
                    event_kind,
                    participant=self.home_binding.name,
                    connection=(
                        self.response_connection
                        if home_step.emissions
                        else self.request_delivery_connection
                    ),
                    packet=event_packet,
                    lineage=event_lineage,
                    detail=detail,
                ),
            ),
        )

    def _cancel_requester(
        self,
        state: ChiReadNoSnpRetrySystemState,
        action: ChiCancelRead,
    ) -> SemanticStep[ChiReadNoSnpRetrySystemState, ChiReadNoSnpSystemEvent]:
        if action.requester != self.requester_binding.name:
            return self._candidate_fault(
                state,
                "unknown_cancel_requester",
                f"unknown CHI requester {action.requester!r}",
            )
        entry = state.requester.entries.get(action.request_key)
        if entry is None or entry.protocol_credit_type is None:
            return self._candidate_fault(
                state,
                "cancel_request",
                "canceled request has no retained RetryAck state",
            )
        credit_key = entry.protocol_credit_type
        ack_lineage = state.retry_ack_lineage_by_request.get(action.request_key)
        credit_lineages = state.pcredit_lineages_by_key.get(credit_key, ())
        if ack_lineage is None or not credit_lineages:
            return self._candidate_fault(
                state,
                "cancel_lineage",
                "canceled request has no matching RetryAck and P-Credit evidence",
            )
        requester_step = self.requester.step(
            state.requester, ChiReadNoSnpCancel(action.request_key)
        )
        failed = self._participant_failure(state, requester_step)
        if failed is not None:
            return failed
        if len(requester_step.emissions) != 1 or not isinstance(
            requester_step.emissions[0], ChiPCrdReturnMessage
        ):
            return self._candidate_fault(
                state,
                "cancel_emission",
                "canceling retry ledger must emit exactly one PCrdReturn",
            )
        returned = requester_step.emissions[0]
        returned_packet = ChiNetworkPacket.request(
            returned,
            source_id=self.profile.requester_node_id,
            target_id=self.profile.home_node_id,
        )
        lineage = (
            *ack_lineage,
            *credit_lineages[0],
            f"{self.requester_binding.name}.pcredit_return",
        )
        enqueue = self.network.step(
            state.network,
            ChiNetworkEnqueue(
                self.request_connection,
                returned_packet,
                resource_plane=0,
                lineage=lineage,
            ),
        )
        failed = self._network_failure(state, enqueue)
        if failed is not None:
            return failed
        ack_lineages = dict(state.retry_ack_lineage_by_request)
        del ack_lineages[action.request_key]
        remaining_credit_lineages = dict(state.pcredit_lineages_by_key)
        if len(credit_lineages) == 1:
            del remaining_credit_lineages[credit_key]
        else:
            remaining_credit_lineages[credit_key] = credit_lineages[1:]
        detail = enqueue.emissions[0] if enqueue.emissions else None
        return SemanticStep(
            replace(
                state,
                network=enqueue.state,
                requester=requester_step.state,
                retry_ack_lineage_by_request=ack_lineages,
                pcredit_lineages_by_key=remaining_credit_lineages,
            ),
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.REQUESTER_PCREDIT_RETURN,
                    participant=self.requester_binding.name,
                    connection=self.request_connection,
                    packet=returned_packet,
                    lineage=lineage,
                    detail=detail,
                ),
            ),
        )

    def _grant_home_credit(
        self,
        state: ChiReadNoSnpRetrySystemState,
    ) -> SemanticStep[ChiReadNoSnpRetrySystemState, ChiReadNoSnpSystemEvent]:
        if not state.home_retry_lineages:
            return self._blocked_candidate(
                state, "home_retry_debt", "Home has no retry debt lineage"
            )
        home_step = self.home.step(state.home, ChiRetryHomeGrant())
        failed = self._participant_failure(state, home_step)
        if failed is not None:
            return failed
        if len(home_step.emissions) != 1 or not isinstance(
            home_step.emissions[0], ChiPCrdGrantMessage
        ):
            return self._candidate_fault(
                state,
                "home_grant_emission",
                "retry Home must emit exactly one PCrdGrant",
            )
        grant = home_step.emissions[0]
        grant_packet = ChiNetworkPacket.response(
            grant,
            source_id=self.profile.home_node_id,
            target_id=self.profile.requester_node_id,
        )
        lineage = (
            *state.home_retry_lineages[0],
            f"{self.home_binding.name}.pcredit_grant",
        )
        enqueue = self.network.step(
            state.network,
            ChiNetworkEnqueue(
                self.response_connection,
                grant_packet,
                lineage=lineage,
            ),
        )
        failed = self._network_failure(state, enqueue)
        if failed is not None:
            return failed
        detail = enqueue.emissions[0] if enqueue.emissions else None
        return SemanticStep(
            replace(
                state,
                network=enqueue.state,
                home=home_step.state,
                home_retry_lineages=state.home_retry_lineages[1:],
            ),
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.HOME_PCREDIT_GRANT,
                    participant=self.home_binding.name,
                    connection=self.response_connection,
                    packet=grant_packet,
                    lineage=lineage,
                    detail=detail,
                ),
            ),
        )

    def _consume_requester_response(
        self,
        state: ChiReadNoSnpRetrySystemState,
    ) -> SemanticStep[ChiReadNoSnpRetrySystemState, ChiReadNoSnpSystemEvent]:
        delivery = self.network.peek_delivery(
            state.network,
            self.response_delivery_connection,
            ChiChannelKind.RSP,
        )
        if delivery is None:
            return self._blocked_candidate(
                state,
                "requester_response",
                "Requester has no captured RSP packet",
            )
        if (
            delivery.receiver != self.requester_response_ref
            or delivery.packet.channel is not ChiChannelKind.RSP
            or delivery.packet.source_id != self.profile.home_node_id
            or delivery.packet.target_id != self.profile.requester_node_id
            or not isinstance(
                delivery.packet.message,
                (ChiRetryAckMessage, ChiPCrdGrantMessage),
            )
        ):
            return self._candidate_fault(
                state,
                "requester_response",
                "captured packet does not match the Requester RSP port",
            )
        response = delivery.packet.message
        if isinstance(response, ChiRetryAckMessage):
            action = ChiReadNoSnpObserveRetryAck(response)
        else:
            action = ChiReadNoSnpObservePCrdGrant(response)
        requester_step = self.requester.step(state.requester, action)
        failed = self._participant_failure(state, requester_step)
        if failed is not None:
            return failed
        drain = self.network.step(
            state.network,
            ChiNetworkDrain(
                self.response_delivery_connection,
                ChiChannelKind.RSP,
            ),
        )
        failed = self._network_failure(state, drain)
        if failed is not None:
            return failed
        ack_lineages = dict(state.retry_ack_lineage_by_request)
        credit_lineages = dict(state.pcredit_lineages_by_key)
        if isinstance(response, ChiRetryAckMessage):
            ack_lineages[response.transaction_id] = delivery.lineage
        else:
            credit_key = response.protocol_credit_type
            credit_lineages[credit_key] = (
                *credit_lineages.get(credit_key, ()),
                delivery.lineage,
            )
        detail = drain.emissions[0] if drain.emissions else None
        return SemanticStep(
            replace(
                state,
                network=drain.state,
                requester=requester_step.state,
                retry_ack_lineage_by_request=ack_lineages,
                pcredit_lineages_by_key=credit_lineages,
            ),
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.REQUESTER_RSP,
                    participant=self.requester_binding.name,
                    connection=self.response_delivery_connection,
                    packet=delivery.packet,
                    lineage=delivery.lineage,
                    detail=detail,
                ),
            ),
        )

    def _retry_requester(
        self,
        state: ChiReadNoSnpRetrySystemState,
    ) -> SemanticStep[ChiReadNoSnpRetrySystemState, ChiReadNoSnpSystemEvent]:
        ready = self.requester.retryable_keys(state.requester)
        if not ready:
            return self._blocked_candidate(
                state,
                "retryable_request",
                "Requester has no RetryAck plus matching P-Credit",
            )
        request_key = ready[0]
        entry = state.requester.entries[request_key]
        assert entry.protocol_credit_type is not None
        credit_key = entry.protocol_credit_type
        ack_lineage = state.retry_ack_lineage_by_request.get(request_key)
        credit_lineages = state.pcredit_lineages_by_key.get(credit_key, ())
        if ack_lineage is None or not credit_lineages:
            return self._candidate_fault(
                state,
                "retry_lineage",
                "retry resources have no matching causal evidence",
            )
        requester_step = self.requester.step(
            state.requester, ChiReadNoSnpRetry(request_key)
        )
        failed = self._participant_failure(state, requester_step)
        if failed is not None:
            return failed
        if len(requester_step.emissions) != 1 or not isinstance(
            requester_step.emissions[0], ChiReadNoSnpMessage
        ):
            return self._candidate_fault(
                state,
                "retry_emission",
                "retry ledger must emit exactly one credited request",
            )
        request = requester_step.emissions[0]
        request_packet = ChiNetworkPacket.request(
            request,
            source_id=self.profile.requester_node_id,
            target_id=self.profile.home_node_id,
        )
        lineage = (
            *ack_lineage,
            *credit_lineages[0],
            f"{self.requester_binding.name}.retry",
        )
        enqueue = self.network.step(
            state.network,
            ChiNetworkEnqueue(
                self.request_connection,
                request_packet,
                resource_plane=0,
                lineage=lineage,
            ),
        )
        failed = self._network_failure(state, enqueue)
        if failed is not None:
            return failed
        ack_lineages = dict(state.retry_ack_lineage_by_request)
        del ack_lineages[request_key]
        remaining_credit_lineages = dict(state.pcredit_lineages_by_key)
        if len(credit_lineages) == 1:
            del remaining_credit_lineages[credit_key]
        else:
            remaining_credit_lineages[credit_key] = credit_lineages[1:]
        detail = enqueue.emissions[0] if enqueue.emissions else None
        return SemanticStep(
            replace(
                state,
                network=enqueue.state,
                requester=requester_step.state,
                retry_ack_lineage_by_request=ack_lineages,
                pcredit_lineages_by_key=remaining_credit_lineages,
            ),
            (
                ChiReadNoSnpSystemEvent(
                    ChiReadNoSnpSystemEventKind.RETRY,
                    participant=self.requester_binding.name,
                    connection=self.request_connection,
                    packet=request_packet,
                    lineage=lineage,
                    detail=detail,
                ),
            ),
        )

    def _has_protocol_work(self, state: ChiReadNoSnpRetrySystemState) -> bool:
        return (
            super()._has_protocol_work(state)
            or bool(state.home.retry_debts)
            or bool(state.home.reserved_by_requester_and_type)
            or bool(state.requester.protocol_credits)
            or bool(state.home_retry_lineages)
            or bool(state.retry_ack_lineage_by_request)
            or bool(state.pcredit_lineages_by_key)
        )

    def _state_fault(
        self, state: ChiReadNoSnpRetrySystemState
    ) -> SemanticFault | None:
        if not isinstance(state, ChiReadNoSnpRetrySystemState):
            raise TypeError("retry session requires its retry system state")
        fault = super()._state_fault(state)
        if fault is not None:
            return fault
        if not isinstance(state.requester, ChiReadNoSnpRetryLedgerState) or (
            not isinstance(state.home, ChiRetryHomeState)
        ):
            return SemanticFault(
                f"{self.name}.retry_state_type",
                "retry system state has incompatible participant states",
                ConstraintScope.SYSTEM,
                self.name,
            )
        if len(state.home_retry_lineages) != len(state.home.retry_debts):
            return SemanticFault(
                f"{self.name}.home_retry_lineage",
                "Home retry debts and causal lineages disagree",
                ConstraintScope.SYSTEM,
                self.home_binding.name,
            )
        waiting_keys = {
            key
            for key, entry in state.requester.entries.items()
            if entry.phase is ChiReadNoSnpRetryPhase.WAIT_RETRY_CREDIT
        }
        if set(state.retry_ack_lineage_by_request) != waiting_keys:
            return SemanticFault(
                f"{self.name}.requester_retry_lineage",
                "Requester RetryAck state and causal lineages disagree",
                ConstraintScope.SYSTEM,
                self.requester_binding.name,
            )
        evidence_counts = {
            key: len(entries)
            for key, entries in state.pcredit_lineages_by_key.items()
        }
        if evidence_counts != dict(state.requester.protocol_credits):
            return SemanticFault(
                f"{self.name}.pcredit_lineage",
                "Requester P-Credit inventory and causal lineages disagree",
                ConstraintScope.SYSTEM,
                self.requester_binding.name,
            )
        if state.home.depth + state.home.reserved_count > self.home.request_capacity:
            return SemanticFault(
                f"{self.name}.home_retry_capacity",
                "Home pending work and retry reservations exceed capacity",
                ConstraintScope.SYSTEM,
                self.home_binding.name,
            )
        return None

__all__ = [
    "ChiCancelRead",
    "ChiReadNoSnpRetrySystemSession",
    "ChiReadNoSnpRetrySystemState",
]
