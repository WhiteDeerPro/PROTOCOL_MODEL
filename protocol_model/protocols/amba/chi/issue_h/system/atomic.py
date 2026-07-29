"""Exact packet-delivery composition for returning CHI Atomics."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeAlias

from protocol_model.semantics import (
    ConstraintScope,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.system.contracts.address import AddressWindow

from ..interface.atomic import (
    ChiAcceptAtomicCompData,
    ChiAcceptAtomicDBIDResp,
    ChiAtomicGeometry,
    ChiAtomicOperation,
    ChiAtomicPending,
    ChiAtomicProfile,
    ChiAtomicRequest,
    ChiAtomicRequester,
    ChiAtomicRequesterState,
    ChiIssueAtomic,
)
from ..participants.atomic import (
    ChiAtomicHomeAcceptData,
    ChiAtomicHomeAcceptRequest,
    ChiAtomicHomeNode,
    ChiAtomicHomeState,
)
from ..representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiAtomicLoadAddMessage,
    ChiAtomicSwapMessage,
    ChiCompDataMessage,
    ChiDBIDRespMessage,
    ChiNetworkPacket,
    ChiNonCopyBackWrDataMessage,
)


_OriginalKey: TypeAlias = tuple[int, int]
_DataKey: TypeAlias = tuple[int, int]
_ATOMIC_REQUEST_TYPES = (
    ChiAtomicSwapMessage,
    ChiAtomicLoadAddMessage,
)


def _valid_key(key: object) -> bool:
    return (
        isinstance(key, tuple)
        and len(key) == 2
        and all(
            isinstance(value, int)
            and not isinstance(value, bool)
            and value >= 0
            for value in key
        )
        and key[1] < (1 << 12)
    )


@dataclass(frozen=True)
class ChiSubmitAtomic:
    requester_node_id: int
    request: ChiAtomicRequest
    operand_value: int
    requester_line_is_invalid: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError(
                "Atomic requester NodeID must be non-negative"
            )
        ChiIssueAtomic(
            self.request,
            self.operand_value,
            self.requester_line_is_invalid,
        )

    @property
    def swap_value(self) -> int:
        """Compatibility projection for the original AtomicSwap API."""

        return self.operand_value


@dataclass(frozen=True)
class ChiDeliverAtomicPacket:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError(
                "Atomic delivery requires ChiNetworkPacket"
            )


ChiAtomicSystemAction: TypeAlias = (
    ChiSubmitAtomic | ChiDeliverAtomicPacket
)


@dataclass(frozen=True)
class ChiAtomicSystemState:
    """Participant states plus one authorized packet value per phase.

    Packet correlation deliberately uses value semantics so serialization or
    lowering may rebuild immutable packets.  A wire-identical duplicate after
    TxnID/DBID reuse is therefore outside this layer and must be excluded by
    the reliable transport/delivery contract.
    """

    requester: ChiAtomicRequesterState
    home: ChiAtomicHomeState
    expected_requests: Mapping[_OriginalKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    expected_grants: Mapping[_OriginalKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    expected_data: Mapping[_DataKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    expected_completions: Mapping[_OriginalKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    retained_data_intents: Mapping[
        _DataKey,
        ChiAtomicPending,
    ] = field(default_factory=dict)
    retained_completion_evidence: Mapping[
        _OriginalKey,
        ChiCompDataMessage,
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.requester, ChiAtomicRequesterState):
            raise TypeError(
                "Atomic system requires requester state"
            )
        if not isinstance(self.home, ChiAtomicHomeState):
            raise TypeError("Atomic system requires Home state")
        requests = dict(self.expected_requests)
        grants = dict(self.expected_grants)
        data_packets = dict(self.expected_data)
        completions = dict(self.expected_completions)
        intents = dict(self.retained_data_intents)
        completion_evidence = dict(self.retained_completion_evidence)
        original_sets = (
            set(requests),
            set(grants),
            set(completions),
        )
        if any(
            left & right
            for index, left in enumerate(original_sets)
            for right in original_sets[index + 1 :]
        ):
            raise ValueError(
                "one Atomic original identity cannot await multiple "
                "packet phases"
            )
        for key, packet in requests.items():
            pending = (
                self.requester.pending.get(key[1])
                if _valid_key(key)
                else None
            )
            if (
                not _valid_key(key)
                or not isinstance(packet, ChiNetworkPacket)
                or not isinstance(packet.message, _ATOMIC_REQUEST_TYPES)
                or key
                != (
                    packet.source_id,
                    packet.message.transaction_id,
                )
                or pending is None
                or not pending.awaiting_grant
                or pending.request != packet.message
            ):
                raise ValueError(
                    "expected Atomic REQ requires exact requester, "
                    "original TxnID, and retained intent"
                )
        for key, packet in grants.items():
            pending = (
                self.requester.pending.get(key[1])
                if _valid_key(key)
                else None
            )
            home_pending = (
                self.home.pending_by_dbid.get(
                    packet.message.data_buffer_id
                )
                if isinstance(packet, ChiNetworkPacket)
                and isinstance(packet.message, ChiDBIDRespMessage)
                else None
            )
            if (
                not _valid_key(key)
                or not isinstance(packet, ChiNetworkPacket)
                or not isinstance(packet.message, ChiDBIDRespMessage)
                or key
                != (
                    packet.target_id,
                    packet.message.transaction_id,
                )
                or pending is None
                or not pending.awaiting_grant
                or home_pending is None
                or home_pending.requester_node_id != key[0]
                or home_pending.request != pending.request
            ):
                raise ValueError(
                    "expected Atomic DBIDResp requires exact requester, "
                    "original TxnID, and Home DBID evidence"
                )
        for key, packet in data_packets.items():
            home_pending = (
                self.home.pending_by_dbid.get(key[1])
                if _valid_key(key)
                else None
            )
            intent = intents.get(key)
            requester_pending = (
                self.requester.pending.get(
                    home_pending.request.transaction_id
                )
                if home_pending is not None
                else None
            )
            geometry = (
                ChiAtomicGeometry.from_request(intent.request)
                if isinstance(intent, ChiAtomicPending)
                else None
            )
            if (
                not _valid_key(key)
                or not isinstance(packet, ChiNetworkPacket)
                or not isinstance(
                    packet.message,
                    ChiNonCopyBackWrDataMessage,
                )
                or key
                != (
                    packet.source_id,
                    packet.message.transaction_id,
                )
                or home_pending is None
                or home_pending.requester_node_id != key[0]
                or not isinstance(intent, ChiAtomicPending)
                or requester_pending != intent
                or intent.data_buffer_id != key[1]
                or geometry is None
                or packet.message.data
                != geometry.position(intent.operand_value)
                or packet.message.byte_enable
                != geometry.byte_enable
                or packet.message.data_id != 0
                or packet.message.critical_chunk_id
                != geometry.critical_chunk_id
            ):
                raise ValueError(
                    "expected Atomic operand DAT requires exact Home "
                    "DBID, requester intent, natural lanes, byte enables, "
                    "and CCID"
                )
        if set(intents) != set(data_packets):
            raise ValueError(
                "every Atomic retained DAT intent must match one packet"
            )
        for key, packet in completions.items():
            pending = (
                self.requester.pending.get(key[1])
                if _valid_key(key)
                else None
            )
            evidence = completion_evidence.get(key)
            geometry = (
                ChiAtomicGeometry.from_request(pending.request)
                if isinstance(pending, ChiAtomicPending)
                else None
            )
            if (
                not _valid_key(key)
                or not isinstance(packet, ChiNetworkPacket)
                or not isinstance(packet.message, ChiCompDataMessage)
                or not isinstance(evidence, ChiCompDataMessage)
                or packet.message != evidence
                or key
                != (
                    packet.target_id,
                    packet.message.transaction_id,
                )
                or pending is None
                or not pending.awaiting_completion
                or geometry is None
                or packet.message.data_id != 0
                or packet.message.critical_chunk_id
                != geometry.critical_chunk_id
                or any(
                    item.requester_node_id == key[0]
                    and item.request.transaction_id == key[1]
                    for item in self.home.pending_by_dbid.values()
                )
            ):
                raise ValueError(
                    "expected Atomic CompData requires exact original "
                    "TxnID, request-derived CCID, committed Home DBID, and "
                    "Home-produced completion evidence"
                )
        if set(completion_evidence) != set(completions):
            raise ValueError(
                "every Atomic completion evidence entry must match one "
                "expected packet"
            )
        requester_phase_ids = {
            key[1] for key in requests
        } | {
            key[1] for key in grants
        } | {
            item.request.transaction_id for item in intents.values()
        } | {
            key[1] for key in completions
        }
        if requester_phase_ids != set(self.requester.pending):
            raise ValueError(
                "every Atomic requester entry must await one exact phase"
            )
        home_phase_dbids = {
            packet.message.data_buffer_id for packet in grants.values()
        } | {
            key[1] for key in data_packets
        }
        if home_phase_dbids != set(self.home.pending_by_dbid):
            raise ValueError(
                "every Atomic Home DBID must await grant or DAT delivery"
            )
        object.__setattr__(
            self,
            "expected_requests",
            MappingProxyType(requests),
        )
        object.__setattr__(
            self,
            "expected_grants",
            MappingProxyType(grants),
        )
        object.__setattr__(
            self,
            "expected_data",
            MappingProxyType(data_packets),
        )
        object.__setattr__(
            self,
            "expected_completions",
            MappingProxyType(completions),
        )
        object.__setattr__(
            self,
            "retained_data_intents",
            MappingProxyType(intents),
        )
        object.__setattr__(
            self,
            "retained_completion_evidence",
            MappingProxyType(completion_evidence),
        )


class ChiAtomicSystemSession(
    SemanticComponent[
        ChiAtomicSystemAction,
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ]
):
    """Close one four-packet Atomic lifecycle."""

    def __init__(
        self,
        name: str,
        *,
        requester: ChiAtomicRequester,
        home: ChiAtomicHomeNode,
        authority_window: AddressWindow | None = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("Atomic system session requires a name")
        if not isinstance(requester, ChiAtomicRequester):
            raise TypeError(
                "Atomic system requester requires its participant"
            )
        if not isinstance(home, ChiAtomicHomeNode):
            raise TypeError("Atomic system Home requires its participant")
        if requester.profile != home.profile:
            raise ValueError(
                "Atomic requester and Home profiles must match"
            )
        if authority_window is not None and not isinstance(
            authority_window,
            AddressWindow,
        ):
            raise TypeError(
                "Atomic authority_window must be AddressWindow or None"
            )
        self.name = name
        self.requester = requester
        self.home = home
        self.profile = requester.profile
        self.authority_window = authority_window

    @classmethod
    def from_resolved(
        cls,
        resolved: "ResolvedChiSystem",
    ) -> "ChiAtomicSystemSession":
        from .capability import (
            CHI_FEATURE_ATOMIC_LOAD_ADD,
            CHI_FEATURE_ATOMIC_SWAP,
        )
        from .resolved import ResolvedChiSystem

        if not isinstance(resolved, ResolvedChiSystem):
            raise TypeError(
                "Atomic resolved construction requires ResolvedChiSystem"
            )
        resolved.require_closed()
        requester_binding = resolved.role_binding("requester")
        home_binding = resolved.role_binding("home")
        if not isinstance(
            requester_binding.component,
            ChiAtomicRequester,
        ):
            raise TypeError(
                "resolved Atomic requester has another component type"
            )
        if not isinstance(home_binding.component, ChiAtomicHomeNode):
            raise TypeError(
                "resolved Atomic Home has another component type"
            )
        operation_by_feature = {
            CHI_FEATURE_ATOMIC_SWAP: ChiAtomicOperation.SWAP,
            CHI_FEATURE_ATOMIC_LOAD_ADD: ChiAtomicOperation.LOAD_ADD,
        }
        required_features = frozenset(
            resolved.feature_contract.required
        )
        if (
            not required_features
            or any(
                feature not in operation_by_feature
                for feature in required_features
            )
        ):
            raise ValueError(
                "resolved Atomic construction must select only one or both "
                "returning Atomic features"
            )
        for feature in required_features:
            resolved.capabilities.require(feature)
        profile = requester_binding.component.profile
        expected_operations = frozenset(
            operation_by_feature[feature]
            for feature in required_features
        )
        if profile.enabled_operations != expected_operations:
            raise ValueError(
                "resolved Atomic feature set must exactly match the "
                "participant profile operation gate"
            )
        if requester_binding.node_ids != frozenset(
            (profile.requester_node_id,)
        ):
            raise ValueError(
                "resolved Atomic requester NodeID does not match profile"
            )
        if home_binding.node_ids != frozenset((profile.home_node_id,)):
            raise ValueError(
                "resolved Atomic Home NodeID does not match profile"
            )
        session_name = (
            "chi.atomic_swap.resolved"
            if expected_operations == {ChiAtomicOperation.SWAP}
            else (
                "chi.atomic_load_add.resolved"
                if expected_operations == {ChiAtomicOperation.LOAD_ADD}
                else "chi.atomic.resolved"
            )
        )
        return cls(
            session_name,
            requester=requester_binding.component,
            home=home_binding.component,
            authority_window=(
                resolved.feature_authority.address_claim.window
            ),
        )

    def initial_state(self) -> ChiAtomicSystemState:
        return ChiAtomicSystemState(
            self.requester.initial_state(),
            self.home.initial_state(),
        )

    def is_quiescent(self, state: ChiAtomicSystemState) -> bool:
        return (
            isinstance(state, ChiAtomicSystemState)
            and self.requester.is_quiescent(state.requester)
            and self.home.is_quiescent(state.home)
            and not state.expected_requests
            and not state.expected_grants
            and not state.expected_data
            and not state.expected_completions
            and not state.retained_data_intents
            and not state.retained_completion_evidence
        )

    def step(
        self,
        state: ChiAtomicSystemState,
        action: ChiAtomicSystemAction,
    ) -> SemanticStep[
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ]:
        if not isinstance(state, ChiAtomicSystemState):
            raise TypeError("Atomic system requires its state type")
        if isinstance(action, ChiSubmitAtomic):
            return self._submit(state, action)
        if isinstance(action, ChiDeliverAtomicPacket):
            return self._deliver(state, action.packet)
        raise TypeError("unknown Atomic system action")

    def _submit(
        self,
        state: ChiAtomicSystemState,
        action: ChiSubmitAtomic,
    ) -> SemanticStep[
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ]:
        if action.requester_node_id != self.profile.requester_node_id:
            return self._fault(
                state,
                "requester_authority",
                "submission selects another Requester NodeID",
            )
        if self.authority_window is not None:
            geometry = self.profile.geometry(action.request)
            transfer = AddressWindow(
                action.request.address,
                geometry.transfer_bytes,
            )
            if not self.authority_window.contains(transfer):
                return self._fault(
                    state,
                    "address_authority",
                    "Atomic is outside the resolved Home authority",
                )
        representation_reasons = (
            CHI_ISSUE_H_CHANNEL_DOMAIN.explain_profile(action.request)
        )
        if representation_reasons:
            return self._fault(
                state,
                "request_representation",
                "; ".join(representation_reasons),
            )
        requester_step = self.requester.step(
            state.requester,
            ChiIssueAtomic(
                action.request,
                action.operand_value,
                action.requester_line_is_invalid,
            ),
        )
        failure = self._participant_failure(state, requester_step)
        if failure is not None:
            return failure
        packet = ChiNetworkPacket.request(
            action.request,
            source_id=self.profile.requester_node_id,
            target_id=self.profile.home_node_id,
        )
        key = (
            self.profile.requester_node_id,
            action.request.transaction_id,
        )
        if (
            key in state.expected_requests
            or key in state.expected_grants
            or key in state.expected_completions
        ):
            return self._fault(
                state,
                "duplicate_delivery",
                "system already retains this Atomic original identity",
            )
        expected_requests = dict(state.expected_requests)
        expected_requests[key] = packet
        return SemanticStep(
            ChiAtomicSystemState(
                requester_step.state,
                state.home,
                expected_requests,
                state.expected_grants,
                state.expected_data,
                state.expected_completions,
                state.retained_data_intents,
                state.retained_completion_evidence,
            ),
            (packet,),
        )

    def _deliver(
        self,
        state: ChiAtomicSystemState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ]:
        if packet.packet_index != 0 or packet.packet_count != 1:
            return self._fault(
                state,
                "packetization",
                "the first Atomic slice requires one packet per message",
            )
        message = packet.message
        if isinstance(message, _ATOMIC_REQUEST_TYPES):
            return self._deliver_request(state, packet, message)
        if isinstance(message, ChiDBIDRespMessage):
            return self._deliver_grant(state, packet, message)
        if isinstance(message, ChiNonCopyBackWrDataMessage):
            return self._deliver_data(state, packet, message)
        if isinstance(message, ChiCompDataMessage):
            return self._deliver_completion(state, packet, message)
        return self._fault(
            state,
            "message_type",
            "packet is not part of the Atomic lifecycle",
        )

    def _deliver_request(
        self,
        state: ChiAtomicSystemState,
        packet: ChiNetworkPacket,
        request: ChiAtomicRequest,
    ) -> SemanticStep[
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ]:
        key = (packet.source_id, request.transaction_id)
        if (
            packet.target_id != self.profile.home_node_id
            or state.expected_requests.get(key) != packet
        ):
            return self._fault(
                state,
                "request_correlation",
                "REQ does not exactly match one requester-produced packet",
            )
        home_step = self.home.step(
            state.home,
            ChiAtomicHomeAcceptRequest(packet.source_id, request),
        )
        failure = self._participant_failure(state, home_step)
        if failure is not None:
            return failure
        if (
            len(home_step.emissions) != 1
            or not isinstance(home_step.emissions[0], ChiDBIDRespMessage)
        ):
            raise RuntimeError(
                "successful Atomic Home request must emit DBIDResp"
            )
        response_packet = ChiNetworkPacket.response(
            home_step.emissions[0],
            source_id=self.profile.home_node_id,
            target_id=packet.source_id,
        )
        expected_requests = dict(state.expected_requests)
        del expected_requests[key]
        expected_grants = dict(state.expected_grants)
        expected_grants[key] = response_packet
        return SemanticStep(
            ChiAtomicSystemState(
                state.requester,
                home_step.state,
                expected_requests,
                expected_grants,
                state.expected_data,
                state.expected_completions,
                state.retained_data_intents,
                state.retained_completion_evidence,
            ),
            (response_packet,),
        )

    def _deliver_grant(
        self,
        state: ChiAtomicSystemState,
        packet: ChiNetworkPacket,
        response: ChiDBIDRespMessage,
    ) -> SemanticStep[
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ]:
        key = (packet.target_id, response.transaction_id)
        if (
            packet.source_id != self.profile.home_node_id
            or state.expected_grants.get(key) != packet
        ):
            return self._fault(
                state,
                "grant_correlation",
                "DBIDResp does not exactly match one Home-produced packet",
            )
        requester_step = self.requester.step(
            state.requester,
            ChiAcceptAtomicDBIDResp(response),
        )
        failure = self._participant_failure(state, requester_step)
        if failure is not None:
            return failure
        if (
            len(requester_step.emissions) != 1
            or not isinstance(
                requester_step.emissions[0],
                ChiNonCopyBackWrDataMessage,
            )
        ):
            raise RuntimeError(
                "successful Atomic DBIDResp must emit operand DAT"
            )
        data_message = requester_step.emissions[0]
        data_packet = ChiNetworkPacket.data(
            data_message,
            source_id=self.profile.requester_node_id,
            target_id=self.profile.home_node_id,
        )
        data_key = (
            self.profile.requester_node_id,
            data_message.transaction_id,
        )
        if data_key in state.expected_data:
            return self._fault(
                state,
                "data_buffer_collision",
                "Home reused an Atomic DBID before DAT delivery",
            )
        updated_intent = requester_step.state.pending.get(
            response.transaction_id
        )
        if updated_intent is None:
            raise RuntimeError(
                "Atomic requester lost its pending completion intent"
            )
        expected_grants = dict(state.expected_grants)
        del expected_grants[key]
        expected_data = dict(state.expected_data)
        expected_data[data_key] = data_packet
        intents = dict(state.retained_data_intents)
        intents[data_key] = updated_intent
        return SemanticStep(
            ChiAtomicSystemState(
                requester_step.state,
                state.home,
                state.expected_requests,
                expected_grants,
                expected_data,
                state.expected_completions,
                intents,
                state.retained_completion_evidence,
            ),
            (data_packet,),
        )

    def _deliver_data(
        self,
        state: ChiAtomicSystemState,
        packet: ChiNetworkPacket,
        data: ChiNonCopyBackWrDataMessage,
    ) -> SemanticStep[
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ]:
        key = (packet.source_id, data.transaction_id)
        if (
            packet.target_id != self.profile.home_node_id
            or state.expected_data.get(key) != packet
        ):
            return self._fault(
                state,
                "data_correlation",
                "operand DAT does not match one requester-produced packet",
            )
        intent = state.retained_data_intents.get(key)
        if intent is None:
            return self._fault(
                state,
                "data_intent",
                "operand DAT has no retained Atomic intent",
            )
        home_step = self.home.step(
            state.home,
            ChiAtomicHomeAcceptData(packet.source_id, data),
        )
        failure = self._participant_failure(state, home_step)
        if failure is not None:
            return failure
        if (
            len(home_step.emissions) != 1
            or not isinstance(home_step.emissions[0], ChiCompDataMessage)
        ):
            raise RuntimeError(
                "successful Atomic operand commit must emit CompData"
            )
        completion = home_step.emissions[0]
        completion_packet = ChiNetworkPacket.data(
            completion,
            source_id=self.profile.home_node_id,
            target_id=packet.source_id,
        )
        original_key = (
            self.profile.requester_node_id,
            intent.request.transaction_id,
        )
        expected_data = dict(state.expected_data)
        del expected_data[key]
        intents = dict(state.retained_data_intents)
        del intents[key]
        completions = dict(state.expected_completions)
        completions[original_key] = completion_packet
        completion_evidence = dict(state.retained_completion_evidence)
        completion_evidence[original_key] = completion
        return SemanticStep(
            ChiAtomicSystemState(
                state.requester,
                home_step.state,
                state.expected_requests,
                state.expected_grants,
                expected_data,
                completions,
                intents,
                completion_evidence,
            ),
            (completion_packet,),
        )

    def _deliver_completion(
        self,
        state: ChiAtomicSystemState,
        packet: ChiNetworkPacket,
        completion: ChiCompDataMessage,
    ) -> SemanticStep[
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ]:
        key = (packet.target_id, completion.transaction_id)
        if (
            packet.source_id != self.profile.home_node_id
            or state.expected_completions.get(key) != packet
        ):
            return self._fault(
                state,
                "completion_correlation",
                "CompData does not match one Home-produced packet",
            )
        requester_step = self.requester.step(
            state.requester,
            ChiAcceptAtomicCompData(completion),
        )
        failure = self._participant_failure(state, requester_step)
        if failure is not None:
            return failure
        if requester_step.emissions:
            raise RuntimeError(
                "Atomic CompData terminal must not emit another packet"
            )
        completions = dict(state.expected_completions)
        del completions[key]
        completion_evidence = dict(state.retained_completion_evidence)
        del completion_evidence[key]
        return SemanticStep(
            ChiAtomicSystemState(
                requester_step.state,
                state.home,
                state.expected_requests,
                state.expected_grants,
                state.expected_data,
                completions,
                state.retained_data_intents,
                completion_evidence,
            )
        )

    def _participant_failure(
        self,
        state: ChiAtomicSystemState,
        step: SemanticStep,
    ) -> SemanticStep[
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ] | None:
        if step.fault is not None:
            return SemanticStep(state, fault=step.fault)
        if step.blocked is not None:
            return SemanticStep(state, blocked=step.blocked)
        return None

    def _fault(
        self,
        state: ChiAtomicSystemState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[
        ChiAtomicSystemState,
        ChiNetworkPacket,
    ]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.SYSTEM,
                self.name,
            ),
        )


# Operation-specific public names remain thin views of the one runtime.  The
# participant profile is the authority that determines which request types
# the session can admit.


class ChiSubmitAtomicSwap(ChiSubmitAtomic):
    """Compatibility submission retaining the ``swap_value`` keyword."""

    def __init__(
        self,
        requester_node_id: int,
        request: ChiAtomicSwapMessage,
        swap_value: int,
        requester_line_is_invalid: bool,
    ) -> None:
        super().__init__(
            requester_node_id,
            request,
            swap_value,
            requester_line_is_invalid,
        )


ChiDeliverAtomicSwapPacket = ChiDeliverAtomicPacket
ChiAtomicSwapSystemAction: TypeAlias = ChiAtomicSystemAction
ChiAtomicSwapSystemSession = ChiAtomicSystemSession
ChiAtomicSwapSystemState = ChiAtomicSystemState

ChiSubmitAtomicLoadAdd = ChiSubmitAtomic
ChiDeliverAtomicLoadAddPacket = ChiDeliverAtomicPacket
ChiAtomicLoadAddSystemAction: TypeAlias = ChiAtomicSystemAction
ChiAtomicLoadAddSystemSession = ChiAtomicSystemSession
ChiAtomicLoadAddSystemState = ChiAtomicSystemState


__all__ = [
    "ChiAtomicLoadAddSystemAction",
    "ChiAtomicLoadAddSystemSession",
    "ChiAtomicLoadAddSystemState",
    "ChiAtomicSwapSystemAction",
    "ChiAtomicSwapSystemSession",
    "ChiAtomicSwapSystemState",
    "ChiAtomicSystemAction",
    "ChiAtomicSystemSession",
    "ChiAtomicSystemState",
    "ChiDeliverAtomicLoadAddPacket",
    "ChiDeliverAtomicSwapPacket",
    "ChiDeliverAtomicPacket",
    "ChiSubmitAtomicLoadAdd",
    "ChiSubmitAtomicSwap",
    "ChiSubmitAtomic",
]
