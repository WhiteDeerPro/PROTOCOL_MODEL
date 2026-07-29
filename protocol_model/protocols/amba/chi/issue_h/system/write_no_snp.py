"""Packet-delivery composition for typed CHI Immediate Write slices.

Transport remains a separate concern.  This session accepts packets only
after a direct caller or ``ChiTransportNetworkSession`` has delivered them to
the endpoint.  Exact packet evidence makes forged, altered, or replayed
REQ/RSP/DAT traffic unable to advance participant state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintScope,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.system.contracts.address import AddressWindow

from ..interface import (
    ChiWriteNoSnpAcceptCompDBIDResp,
    ChiWriteNoSnpFullIssue,
    ChiWriteNoSnpFullRequesterLedger,
    ChiWriteNoSnpPending,
    ChiWriteNoSnpPtlIssue,
    ChiWriteNoSnpPtlProfile,
    ChiWriteNoSnpPtlRequesterLedger,
    ChiWriteNoSnpRequesterState,
)
from ..participants import (
    ChiWriteNoSnpHomeAcceptData,
    ChiWriteNoSnpHomeAcceptRequest,
    ChiWriteNoSnpHomeNode,
    ChiWriteNoSnpHomeState,
)
from ..representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiCompDBIDRespMessage,
    ChiNetworkPacket,
    ChiNonCopyBackWrDataMessage,
    ChiWriteNoSnpFullMessage,
    ChiWriteNoSnpPtlMessage,
)


_OriginalKey = tuple[int, int]
_DataKey = tuple[int, int]


@dataclass(frozen=True)
class ChiSubmitWriteNoSnpFull:
    requester_node_id: int
    request: ChiWriteNoSnpFullMessage
    data: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError(
                "WriteNoSnpFull requester NodeID must be non-negative"
            )
        if not isinstance(self.request, ChiWriteNoSnpFullMessage):
            raise TypeError(
                "WriteNoSnpFull submission requires its typed REQ"
            )
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or not 0 <= self.data < (1 << 512)
        ):
            raise ValueError(
                "WriteNoSnpFull submission data must fit one 512-bit line"
            )


@dataclass(frozen=True)
class ChiSubmitWriteNoSnpPtl:
    requester_node_id: int
    request: ChiWriteNoSnpPtlMessage
    data: int
    byte_enable: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.requester_node_id, int)
            or isinstance(self.requester_node_id, bool)
            or self.requester_node_id < 0
        ):
            raise ValueError(
                "WriteNoSnpPtl requester NodeID must be non-negative"
            )
        if not isinstance(self.request, ChiWriteNoSnpPtlMessage):
            raise TypeError(
                "WriteNoSnpPtl submission requires its typed REQ"
            )
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or not 0 <= self.data < (1 << 512)
        ):
            raise ValueError(
                "WriteNoSnpPtl submission data must fit one 512-bit DAT"
            )
        if (
            not isinstance(self.byte_enable, int)
            or isinstance(self.byte_enable, bool)
            or not 0 <= self.byte_enable < (1 << 64)
        ):
            raise ValueError(
                "WriteNoSnpPtl submission byte enable must be 64-bit"
            )


@dataclass(frozen=True)
class ChiDeliverWriteNoSnpPacket:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError(
                "WriteNoSnp delivery requires ChiNetworkPacket"
            )


ChiWriteNoSnpSystemAction = (
    ChiSubmitWriteNoSnpFull
    | ChiSubmitWriteNoSnpPtl
    | ChiDeliverWriteNoSnpPacket
)


def _valid_original_key(key: object) -> bool:
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
class ChiWriteNoSnpSystemState:
    """Participant states plus one exact delivery authority per phase.

    REQ evidence is bound to the requester-retained operation.  RSP evidence
    additionally binds that operation to the exact Home pending selected by
    its DBID; comparing the original-ID and DBID sets independently is not
    sufficient because two grants could otherwise be exchanged.  Once the
    requester emits DAT, the generated state retains the submit intent beside
    the packet so a packet whose data/BE differs from that intent is invalid.
    As elsewhere in the model, these public dataclasses enforce internal
    consistency; they are not opaque provenance against coordinated
    reconstruction of every correlated field.
    """

    requester: ChiWriteNoSnpRequesterState
    home: ChiWriteNoSnpHomeState
    expected_requests: Mapping[_OriginalKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    expected_responses: Mapping[_OriginalKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    expected_data: Mapping[_DataKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    retained_data_intents: Mapping[
        _DataKey,
        ChiWriteNoSnpPending,
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.requester, ChiWriteNoSnpRequesterState):
            raise TypeError(
                "WriteNoSnp system requires requester ledger state"
            )
        if not isinstance(self.home, ChiWriteNoSnpHomeState):
            raise TypeError(
                "WriteNoSnp system requires Home participant state"
            )
        expected_requests = dict(self.expected_requests)
        expected_responses = dict(self.expected_responses)
        expected_data = dict(self.expected_data)
        retained_data_intents = dict(self.retained_data_intents)
        if set(expected_requests) & set(expected_responses):
            raise ValueError(
                "one original WriteNoSnp identity cannot await both REQ and "
                "RSP delivery"
            )
        for key, packet in expected_requests.items():
            retained = (
                self.requester.pending.get(key[1])
                if _valid_original_key(key)
                else None
            )
            if (
                not _valid_original_key(key)
                or not isinstance(packet, ChiNetworkPacket)
                or not isinstance(
                    packet.message,
                    (
                        ChiWriteNoSnpFullMessage,
                        ChiWriteNoSnpPtlMessage,
                    ),
                )
                or key
                != (
                    packet.source_id,
                    packet.message.transaction_id,
                )
                or retained is None
                or packet.message != retained.request
            ):
                raise ValueError(
                    "expected WriteNoSnp REQ delivery requires exact "
                    "Requester/original-TxnID and retained-request evidence"
                )
        for key, packet in expected_responses.items():
            retained = (
                self.requester.pending.get(key[1])
                if _valid_original_key(key)
                else None
            )
            home_pending = (
                self.home.pending_by_dbid.get(
                    packet.message.data_buffer_id
                )
                if isinstance(
                    packet,
                    ChiNetworkPacket,
                )
                and isinstance(
                    packet.message,
                    ChiCompDBIDRespMessage,
                )
                else None
            )
            if (
                not _valid_original_key(key)
                or not isinstance(packet, ChiNetworkPacket)
                or not isinstance(
                    packet.message,
                    ChiCompDBIDRespMessage,
                )
                or key
                != (
                    packet.target_id,
                    packet.message.transaction_id,
                )
                or retained is None
                or home_pending is None
                or home_pending.requester_node_id != key[0]
                or home_pending.request != retained.request
                or packet.message.trace_tag
                != home_pending.response_trace_tag
            ):
                raise ValueError(
                    "expected WriteNoSnp RSP delivery requires exact "
                    "Requester/original-TxnID, retained-request, response "
                    "TraceTag, and Home DBID evidence"
                )
        for key, packet in expected_data.items():
            home_pending = (
                self.home.pending_by_dbid.get(key[1])
                if _valid_original_key(key)
                else None
            )
            intent = retained_data_intents.get(key)
            if (
                not _valid_original_key(key)
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
                or not isinstance(intent, ChiWriteNoSnpPending)
                or home_pending.request != intent.request
                or packet.message.data != intent.data
                or packet.message.byte_enable != intent.byte_enable
                or packet.message.critical_chunk_id
                != ((intent.request.address >> 4) & 0b11)
                or packet.message.trace_tag
                != home_pending.response_trace_tag
            ):
                raise ValueError(
                    "expected WriteNoSnp DAT delivery requires exact "
                    "Requester/Home-DBID, retained payload, request-derived "
                    "CCID, response TraceTag, and Home-pending evidence"
                )
        if set(retained_data_intents) != set(expected_data):
            raise ValueError(
                "every retained WriteNoSnp DAT intent must match one exact "
                "packet delivery"
            )
        requester_phase_keys = (
            tuple(expected_requests) + tuple(expected_responses)
        )
        if (
            len(requester_phase_keys) != len(self.requester.pending)
            or {
                key[1] for key in requester_phase_keys
            }
            != set(self.requester.pending)
        ):
            raise ValueError(
                "every requester pending WriteNoSnp operation must await "
                "exactly one REQ or RSP delivery"
            )
        response_dbids = {
            packet.message.data_buffer_id
            for packet in expected_responses.values()
        }
        data_dbids = {key[1] for key in expected_data}
        if response_dbids & data_dbids:
            raise ValueError(
                "one Home DBID cannot await both RSP and DAT delivery"
            )
        if (
            len(response_dbids) != len(expected_responses)
            or len(data_dbids) != len(expected_data)
            or set(self.home.pending_by_dbid)
            != response_dbids | data_dbids
        ):
            raise ValueError(
                "every Home DBID must await exactly one RSP or DAT delivery"
            )
        object.__setattr__(
            self,
            "expected_requests",
            MappingProxyType(expected_requests),
        )
        object.__setattr__(
            self,
            "expected_responses",
            MappingProxyType(expected_responses),
        )
        object.__setattr__(
            self,
            "expected_data",
            MappingProxyType(expected_data),
        )
        object.__setattr__(
            self,
            "retained_data_intents",
            MappingProxyType(retained_data_intents),
        )


class ChiWriteNoSnpSystemSession(
    SemanticComponent[
        ChiWriteNoSnpSystemAction,
        ChiWriteNoSnpSystemState,
        ChiNetworkPacket,
    ]
):
    """Close REQ→combined RSP→single DAT across one Requester and Home."""

    def __init__(
        self,
        name: str,
        *,
        requester: (
            ChiWriteNoSnpFullRequesterLedger
            | ChiWriteNoSnpPtlRequesterLedger
        ),
        home: ChiWriteNoSnpHomeNode,
        authority_window: AddressWindow | None = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("WriteNoSnp system session requires a name")
        if not isinstance(
            requester,
            (
                ChiWriteNoSnpFullRequesterLedger,
                ChiWriteNoSnpPtlRequesterLedger,
            ),
        ):
            raise TypeError(
                "WriteNoSnp system requester requires its ledger"
            )
        if not isinstance(home, ChiWriteNoSnpHomeNode):
            raise TypeError(
                "WriteNoSnp system Home requires its participant"
            )
        if requester.profile != home.profile:
            raise ValueError(
                "WriteNoSnp requester and Home profiles must match"
            )
        if authority_window is not None and not isinstance(
            authority_window,
            AddressWindow,
        ):
            raise TypeError(
                "WriteNoSnp authority_window must be AddressWindow or None"
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
    ) -> "ChiWriteNoSnpSystemSession":
        """Open the lifecycle only after feature/authority closure."""

        from .capability import (
            CHI_FEATURE_WRITE_NO_SNP_FULL,
            CHI_FEATURE_WRITE_NO_SNP_PTL,
        )
        from .resolved import ResolvedChiSystem

        if not isinstance(resolved, ResolvedChiSystem):
            raise TypeError(
                "WriteNoSnp resolved construction requires "
                "ResolvedChiSystem"
        )
        resolved.require_closed()
        requester_binding = resolved.role_binding("requester")
        home_binding = resolved.role_binding("home")
        if not isinstance(
            requester_binding.component,
            (
                ChiWriteNoSnpFullRequesterLedger,
                ChiWriteNoSnpPtlRequesterLedger,
            ),
        ):
            raise TypeError(
                "resolved WriteNoSnp requester has another component type"
            )
        if not isinstance(
            home_binding.component,
            ChiWriteNoSnpHomeNode,
        ):
            raise TypeError(
                "resolved WriteNoSnp Home has another component type"
            )
        feature = (
            CHI_FEATURE_WRITE_NO_SNP_PTL
            if isinstance(
                requester_binding.component,
                ChiWriteNoSnpPtlRequesterLedger,
            )
            else CHI_FEATURE_WRITE_NO_SNP_FULL
        )
        if resolved.feature_contract.required != frozenset((feature,)):
            raise ValueError(
                "resolved WriteNoSnp construction does not select the "
                "requester's typed Immediate-Write feature"
            )
        resolved.capabilities.require(feature)
        requester_profile = requester_binding.component.profile
        if requester_binding.node_ids != frozenset(
            (requester_profile.requester_node_id,)
        ):
            raise ValueError(
                "resolved WriteNoSnp requester NodeID does not match its "
                "component profile"
            )
        if home_binding.node_ids != frozenset(
            (requester_profile.home_node_id,)
        ):
            raise ValueError(
                "resolved WriteNoSnp Home NodeID does not match the "
                "requester/Home component profile"
            )
        return cls(
            "chi.write_no_snp.resolved",
            requester=requester_binding.component,
            home=home_binding.component,
            authority_window=resolved.feature_authority.address_claim.window,
        )

    def initial_state(self) -> ChiWriteNoSnpSystemState:
        return ChiWriteNoSnpSystemState(
            self.requester.initial_state(),
            self.home.initial_state(),
        )

    def is_quiescent(self, state: ChiWriteNoSnpSystemState) -> bool:
        return (
            isinstance(state, ChiWriteNoSnpSystemState)
            and self.requester.is_quiescent(state.requester)
            and self.home.is_quiescent(state.home)
            and not state.expected_requests
            and not state.expected_responses
            and not state.expected_data
        )

    def step(
        self,
        state: ChiWriteNoSnpSystemState,
        action: ChiWriteNoSnpSystemAction,
    ) -> SemanticStep[
        ChiWriteNoSnpSystemState,
        ChiNetworkPacket,
    ]:
        if not isinstance(state, ChiWriteNoSnpSystemState):
            raise TypeError("WriteNoSnp system requires its state type")
        if isinstance(
            action,
            (ChiSubmitWriteNoSnpFull, ChiSubmitWriteNoSnpPtl),
        ):
            return self._submit(state, action)
        if isinstance(action, ChiDeliverWriteNoSnpPacket):
            return self._deliver(state, action.packet)
        raise TypeError("unknown WriteNoSnp system action")

    def _submit(
        self,
        state: ChiWriteNoSnpSystemState,
        action: ChiSubmitWriteNoSnpFull | ChiSubmitWriteNoSnpPtl,
    ) -> SemanticStep[
        ChiWriteNoSnpSystemState,
        ChiNetworkPacket,
    ]:
        expects_ptl = isinstance(
            self.requester,
            ChiWriteNoSnpPtlRequesterLedger,
        )
        if expects_ptl != isinstance(action, ChiSubmitWriteNoSnpPtl):
            return self._fault(
                state,
                "submission_profile",
                "submission opcode does not match the configured "
                "WriteNoSnp requester profile",
            )
        if action.requester_node_id != self.profile.requester_node_id:
            return self._fault(
                state,
                "requester_authority",
                "submission selects another Requester NodeID",
            )
        if self.authority_window is not None:
            if isinstance(action, ChiSubmitWriteNoSnpPtl):
                if not isinstance(
                    self.profile,
                    ChiWriteNoSnpPtlProfile,
                ):
                    raise RuntimeError(
                        "validated Ptl session lost its typed profile"
                    )
                aligned_address, size_bytes = self.profile.data_window(
                    action.request
                )
            else:
                aligned_address = action.request.address
                size_bytes = 64
            transfer = AddressWindow(aligned_address, size_bytes)
            if not self.authority_window.contains(transfer):
                return self._fault(
                    state,
                    "address_authority",
                    "WriteNoSnp is outside the resolved Home authority",
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
        issue = (
            ChiWriteNoSnpPtlIssue(
                action.request,
                action.data,
                action.byte_enable,
            )
            if isinstance(action, ChiSubmitWriteNoSnpPtl)
            else ChiWriteNoSnpFullIssue(action.request, action.data)
        )
        requester_step = self.requester.step(state.requester, issue)
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
            or key in state.expected_responses
        ):
            return self._fault(
                state,
                "duplicate_delivery",
                "system already retains this original transaction identity",
            )
        expected_requests = dict(state.expected_requests)
        expected_requests[key] = packet
        candidate = ChiWriteNoSnpSystemState(
            requester_step.state,
            state.home,
            expected_requests,
            state.expected_responses,
            state.expected_data,
            state.retained_data_intents,
        )
        return SemanticStep(candidate, (packet,))

    def _deliver(
        self,
        state: ChiWriteNoSnpSystemState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[
        ChiWriteNoSnpSystemState,
        ChiNetworkPacket,
    ]:
        if packet.packet_index != 0 or packet.packet_count != 1:
            return self._fault(
                state,
                "packetization",
                "the first WriteNoSnp slice requires one packet",
            )
        message = packet.message
        if isinstance(
            message,
            (ChiWriteNoSnpFullMessage, ChiWriteNoSnpPtlMessage),
        ):
            return self._deliver_request(state, packet, message)
        if isinstance(message, ChiCompDBIDRespMessage):
            return self._deliver_response(state, packet, message)
        if isinstance(message, ChiNonCopyBackWrDataMessage):
            return self._deliver_data(state, packet, message)
        return self._fault(
            state,
            "message_type",
            "packet is not part of the WriteNoSnp lifecycle",
        )

    def _deliver_request(
        self,
        state: ChiWriteNoSnpSystemState,
        packet: ChiNetworkPacket,
        request: ChiWriteNoSnpFullMessage | ChiWriteNoSnpPtlMessage,
    ) -> SemanticStep[
        ChiWriteNoSnpSystemState,
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
            ChiWriteNoSnpHomeAcceptRequest(
                packet.source_id,
                request,
            ),
        )
        failure = self._participant_failure(state, home_step)
        if failure is not None:
            return failure
        if len(home_step.emissions) != 1:
            raise RuntimeError(
                "successful WriteNoSnp Home request must emit one response"
            )
        response = home_step.emissions[0]
        response_packet = ChiNetworkPacket.response(
            response,
            source_id=self.profile.home_node_id,
            target_id=packet.source_id,
        )
        expected_requests = dict(state.expected_requests)
        del expected_requests[key]
        expected_responses = dict(state.expected_responses)
        expected_responses[key] = response_packet
        candidate = ChiWriteNoSnpSystemState(
            state.requester,
            home_step.state,
            expected_requests,
            expected_responses,
            state.expected_data,
            state.retained_data_intents,
        )
        return SemanticStep(candidate, (response_packet,))

    def _deliver_response(
        self,
        state: ChiWriteNoSnpSystemState,
        packet: ChiNetworkPacket,
        response: ChiCompDBIDRespMessage,
    ) -> SemanticStep[
        ChiWriteNoSnpSystemState,
        ChiNetworkPacket,
    ]:
        key = (packet.target_id, response.transaction_id)
        if (
            packet.source_id != self.profile.home_node_id
            or state.expected_responses.get(key) != packet
        ):
            return self._fault(
                state,
                "response_correlation",
                "RSP does not exactly match one Home-produced packet",
            )
        retained = state.requester.pending.get(response.transaction_id)
        if retained is None:
            return self._fault(
                state,
                "response_correlation",
                "RSP original TxnID has no retained requester operation",
            )
        requester_step = self.requester.step(
            state.requester,
            ChiWriteNoSnpAcceptCompDBIDResp(response),
        )
        failure = self._participant_failure(state, requester_step)
        if failure is not None:
            return failure
        if len(requester_step.emissions) != 1:
            raise RuntimeError(
                "successful CompDBIDResp must produce one NCB DAT"
            )
        data = requester_step.emissions[0]
        data_packet = ChiNetworkPacket.data(
            data,
            source_id=self.profile.requester_node_id,
            target_id=self.profile.home_node_id,
        )
        expected_responses = dict(state.expected_responses)
        del expected_responses[key]
        expected_data = dict(state.expected_data)
        data_key = (
            self.profile.requester_node_id,
            data.transaction_id,
        )
        if data_key in expected_data:
            return self._fault(
                state,
                "data_buffer_collision",
                "Home reused a DBID before its earlier DAT was delivered",
            )
        expected_data[data_key] = data_packet
        retained_data_intents = dict(state.retained_data_intents)
        retained_data_intents[data_key] = retained
        candidate = ChiWriteNoSnpSystemState(
            requester_step.state,
            state.home,
            state.expected_requests,
            expected_responses,
            expected_data,
            retained_data_intents,
        )
        return SemanticStep(candidate, (data_packet,))

    def _deliver_data(
        self,
        state: ChiWriteNoSnpSystemState,
        packet: ChiNetworkPacket,
        data: ChiNonCopyBackWrDataMessage,
    ) -> SemanticStep[
        ChiWriteNoSnpSystemState,
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
                "DAT does not exactly match one requester-produced packet",
            )
        home_step = self.home.step(
            state.home,
            ChiWriteNoSnpHomeAcceptData(packet.source_id, data),
        )
        failure = self._participant_failure(state, home_step)
        if failure is not None:
            return failure
        if home_step.emissions:
            raise RuntimeError(
                "the no-CompAck WriteNoSnp DAT terminal emits no packet"
            )
        expected_data = dict(state.expected_data)
        del expected_data[key]
        retained_data_intents = dict(state.retained_data_intents)
        del retained_data_intents[key]
        candidate = ChiWriteNoSnpSystemState(
            state.requester,
            home_step.state,
            state.expected_requests,
            state.expected_responses,
            expected_data,
            retained_data_intents,
        )
        return SemanticStep(candidate)

    def _participant_failure(
        self,
        state: ChiWriteNoSnpSystemState,
        step: SemanticStep,
    ) -> SemanticStep[
        ChiWriteNoSnpSystemState,
        ChiNetworkPacket,
    ] | None:
        if step.fault is not None:
            return SemanticStep(state, fault=step.fault)
        if step.blocked is not None:
            return SemanticStep(state, blocked=step.blocked)
        return None

    def _fault(
        self,
        state: ChiWriteNoSnpSystemState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[
        ChiWriteNoSnpSystemState,
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


__all__ = [
    "ChiDeliverWriteNoSnpPacket",
    "ChiSubmitWriteNoSnpFull",
    "ChiSubmitWriteNoSnpPtl",
    "ChiWriteNoSnpSystemAction",
    "ChiWriteNoSnpSystemSession",
    "ChiWriteNoSnpSystemState",
]
