"""Exact packet composition for non-snoop Exclusive Read/WriteNoSnpPtl.

The session joins one requester-local Exclusive gate with one aggregate Home
that owns backing, the System monitor, and write DBIDs.  Transport remains
orthogonal: emitted packets can be delivered directly or carried through a
``ChiTransportNetworkSession`` before they are presented back here.
"""

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

from ..interface.exclusive import (
    ChiAcceptExclusiveCompDBIDResp,
    ChiAcceptExclusiveCompData,
    ChiIssueExclusiveReadNoSnp,
    ChiIssueExclusiveWriteNoSnpPtl,
    ChiNonSnoopExclusivePendingWrite,
    ChiNonSnoopExclusiveRequester,
    ChiNonSnoopExclusiveRequesterState,
)
from ..participants.exclusive import (
    ChiNonSnoopExclusiveHomeAcceptData,
    ChiNonSnoopExclusiveHomeAcceptRead,
    ChiNonSnoopExclusiveHomeAcceptWrite,
    ChiNonSnoopExclusiveHomeCommitUpdate,
    ChiNonSnoopExclusiveHomeNode,
    ChiNonSnoopExclusiveHomeState,
)
from ..representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiCompDBIDRespMessage,
    ChiCompDataMessage,
    ChiNetworkPacket,
    ChiNonCopyBackWrDataMessage,
    ChiReadNoSnpMessage,
    ChiRespErr,
    ChiWriteNoSnpPtlMessage,
)


_OriginalKey = tuple[int, int]
_DataKey = tuple[int, int]


def _require_node_id(name: str, value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{name} must be a non-negative integer")


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
class ChiSubmitNonSnoopExclusiveRead:
    requester_node_id: int
    request: ChiReadNoSnpMessage

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(self.request, ChiReadNoSnpMessage):
            raise TypeError(
                "non-snoop Exclusive read submission requires ReadNoSnp"
            )


@dataclass(frozen=True)
class ChiSubmitNonSnoopExclusiveWrite:
    requester_node_id: int
    request: ChiWriteNoSnpPtlMessage
    data: int
    byte_enable: int

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(self.request, ChiWriteNoSnpPtlMessage):
            raise TypeError(
                "non-snoop Exclusive write submission requires "
                "WriteNoSnpPtl"
            )
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or self.data < 0
        ):
            raise ValueError(
                "non-snoop Exclusive write data must be non-negative"
            )
        if (
            not isinstance(self.byte_enable, int)
            or isinstance(self.byte_enable, bool)
            or self.byte_enable < 0
        ):
            raise ValueError(
                "non-snoop Exclusive write byte_enable must be non-negative"
            )


@dataclass(frozen=True)
class ChiDeliverNonSnoopExclusivePacket:
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError(
                "non-snoop Exclusive delivery requires ChiNetworkPacket"
            )


@dataclass(frozen=True)
class ChiCommitNonSnoopExclusiveUpdate:
    """Apply a committed competing update through the aggregate Home."""

    update: ChiNonSnoopExclusiveHomeCommitUpdate

    def __post_init__(self) -> None:
        if not isinstance(
            self.update, ChiNonSnoopExclusiveHomeCommitUpdate
        ):
            raise TypeError(
                "non-snoop Exclusive update requires the typed Home "
                "commit action"
            )


ChiNonSnoopExclusiveSystemAction: TypeAlias = (
    ChiSubmitNonSnoopExclusiveRead
    | ChiSubmitNonSnoopExclusiveWrite
    | ChiDeliverNonSnoopExclusivePacket
    | ChiCommitNonSnoopExclusiveUpdate
)


@dataclass(frozen=True)
class ChiNonSnoopExclusiveSystemState:
    """Participant state plus exact delivery evidence for every live phase."""

    requester: ChiNonSnoopExclusiveRequesterState
    home: ChiNonSnoopExclusiveHomeState
    expected_requests: Mapping[_OriginalKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    expected_read_data: Mapping[_OriginalKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    expected_write_responses: Mapping[
        _OriginalKey, ChiNetworkPacket
    ] = field(default_factory=dict)
    expected_write_data: Mapping[_DataKey, ChiNetworkPacket] = field(
        default_factory=dict
    )
    retained_write_intents: Mapping[
        _DataKey, ChiNonSnoopExclusivePendingWrite
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(
            self.requester, ChiNonSnoopExclusiveRequesterState
        ):
            raise TypeError(
                "non-snoop Exclusive system requires requester state"
            )
        if not isinstance(self.home, ChiNonSnoopExclusiveHomeState):
            raise TypeError(
                "non-snoop Exclusive system requires Home state"
            )
        expected_requests = dict(self.expected_requests)
        expected_read_data = dict(self.expected_read_data)
        expected_write_responses = dict(
            self.expected_write_responses
        )
        expected_write_data = dict(self.expected_write_data)
        retained_write_intents = dict(self.retained_write_intents)
        original_phase_keys = (
            set(expected_requests),
            set(expected_read_data),
            set(expected_write_responses),
        )
        if any(
            left & right
            for index, left in enumerate(original_phase_keys)
            for right in original_phase_keys[index + 1 :]
        ):
            raise ValueError(
                "one original Exclusive identity cannot await two phases"
            )
        for key, packet in expected_requests.items():
            if not _valid_original_key(key) or not isinstance(
                packet, ChiNetworkPacket
            ):
                raise ValueError(
                    "expected Exclusive REQ requires a valid identity and "
                    "packet"
                )
            message = packet.message
            retained = (
                self.requester.pending_reads.get(key[1])
                if isinstance(message, ChiReadNoSnpMessage)
                else self.requester.pending_writes.get(key[1])
                if isinstance(message, ChiWriteNoSnpPtlMessage)
                else None
            )
            retained_request = (
                retained.request
                if isinstance(
                    retained, ChiNonSnoopExclusivePendingWrite
                )
                else retained
            )
            if (
                key != (packet.source_id, message.transaction_id)
                or retained_request != message
            ):
                raise ValueError(
                    "expected Exclusive REQ must match retained requester "
                    "evidence"
                )
        for key, packet in expected_read_data.items():
            retained = (
                self.requester.pending_reads.get(key[1])
                if _valid_original_key(key)
                else None
            )
            if (
                retained is None
                or not isinstance(packet, ChiNetworkPacket)
                or not isinstance(packet.message, ChiCompDataMessage)
                or key
                != (
                    packet.target_id,
                    packet.message.transaction_id,
                )
                or packet.message.critical_chunk_id
                != self._critical_chunk_id(retained)
            ):
                raise ValueError(
                    "expected Exclusive read DAT must match one pending read"
                )
        for key, packet in expected_write_responses.items():
            retained = (
                self.requester.pending_writes.get(key[1])
                if _valid_original_key(key)
                else None
            )
            home_pending = (
                self.home.pending_by_dbid.get(
                    packet.message.data_buffer_id
                )
                if isinstance(packet, ChiNetworkPacket)
                and isinstance(
                    packet.message, ChiCompDBIDRespMessage
                )
                else None
            )
            if (
                retained is None
                or home_pending is None
                or key
                != (
                    packet.target_id,
                    packet.message.transaction_id,
                )
                or home_pending.request != retained.request
                or home_pending.requester_node_id != key[0]
                or packet.message.trace_tag
                != home_pending.response_trace_tag
                or packet.message.response_error
                is not (
                    ChiRespErr.EXOK
                    if home_pending.exclusive_passed
                    else ChiRespErr.OK
                )
            ):
                raise ValueError(
                    "expected Exclusive write RSP must bind requester "
                    "intent, Home DBID, response TraceTag, and pass/fail "
                    "outcome"
                )
        for key, packet in expected_write_data.items():
            home_pending = (
                self.home.pending_by_dbid.get(key[1])
                if _valid_original_key(key)
                else None
            )
            intent = retained_write_intents.get(key)
            if (
                home_pending is None
                or not isinstance(packet, ChiNetworkPacket)
                or not isinstance(
                    packet.message, ChiNonCopyBackWrDataMessage
                )
                or not isinstance(
                    intent, ChiNonSnoopExclusivePendingWrite
                )
                or key
                != (
                    packet.source_id,
                    packet.message.transaction_id,
                )
                or home_pending.request != intent.request
                or packet.message.data != intent.data
                or packet.message.byte_enable != intent.byte_enable
                or packet.message.critical_chunk_id
                != self._critical_chunk_id(intent.request)
                or packet.message.trace_tag
                != home_pending.response_trace_tag
            ):
                raise ValueError(
                    "expected Exclusive write DAT must bind Home DBID, "
                    "retained payload, request-derived CCID, and response "
                    "TraceTag"
                )
        if set(retained_write_intents) != set(expected_write_data):
            raise ValueError(
                "every retained Exclusive DAT intent needs one packet"
            )
        requester_phase_txnids = {
            key[1]
            for mapping in (
                expected_requests,
                expected_read_data,
                expected_write_responses,
            )
            for key in mapping
        }
        if requester_phase_txnids != (
            set(self.requester.pending_reads)
            | set(self.requester.pending_writes)
        ):
            raise ValueError(
                "every pending Exclusive requester operation must await one "
                "exact delivery phase"
            )
        response_dbids = {
            packet.message.data_buffer_id
            for packet in expected_write_responses.values()
        }
        data_dbids = {key[1] for key in expected_write_data}
        if (
            response_dbids & data_dbids
            or set(self.home.pending_by_dbid)
            != response_dbids | data_dbids
        ):
            raise ValueError(
                "every Exclusive Home DBID must await one RSP or DAT phase"
            )
        object.__setattr__(
            self,
            "expected_requests",
            MappingProxyType(expected_requests),
        )
        object.__setattr__(
            self,
            "expected_read_data",
            MappingProxyType(expected_read_data),
        )
        object.__setattr__(
            self,
            "expected_write_responses",
            MappingProxyType(expected_write_responses),
        )
        object.__setattr__(
            self,
            "expected_write_data",
            MappingProxyType(expected_write_data),
        )
        object.__setattr__(
            self,
            "retained_write_intents",
            MappingProxyType(retained_write_intents),
        )

    @staticmethod
    def _critical_chunk_id(
        request: ChiReadNoSnpMessage | ChiWriteNoSnpPtlMessage,
    ) -> int:
        return (request.address >> 4) & 0b11


class ChiNonSnoopExclusiveSystemSession(
    SemanticComponent[
        ChiNonSnoopExclusiveSystemAction,
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]
):
    """Close one typed Exclusive sequence over exact packet delivery."""

    def __init__(
        self,
        name: str,
        *,
        requester: ChiNonSnoopExclusiveRequester,
        home: ChiNonSnoopExclusiveHomeNode,
        authority_window: AddressWindow | None = None,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError(
                "non-snoop Exclusive system session requires a name"
            )
        if not isinstance(
            requester, ChiNonSnoopExclusiveRequester
        ):
            raise TypeError(
                "non-snoop Exclusive session requires its requester"
            )
        if not isinstance(home, ChiNonSnoopExclusiveHomeNode):
            raise TypeError(
                "non-snoop Exclusive session requires its aggregate Home"
            )
        if requester.profile != home.profile:
            raise ValueError(
                "non-snoop Exclusive requester and Home profiles must match"
            )
        if authority_window is not None and not isinstance(
            authority_window, AddressWindow
        ):
            raise TypeError(
                "non-snoop Exclusive authority must be AddressWindow or None"
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
    ) -> "ChiNonSnoopExclusiveSystemSession":
        from .capability import CHI_FEATURE_NON_SNOOP_EXCLUSIVE_PTL
        from .resolved import ResolvedChiSystem

        if not isinstance(resolved, ResolvedChiSystem):
            raise TypeError(
                "resolved Exclusive construction requires ResolvedChiSystem"
            )
        resolved.require_closed()
        if resolved.feature_contract.required != frozenset(
            (CHI_FEATURE_NON_SNOOP_EXCLUSIVE_PTL,)
        ):
            raise ValueError(
                "resolved Exclusive construction requires only the typed "
                "non-snoop Exclusive-Ptl feature"
            )
        resolved.capabilities.require(
            CHI_FEATURE_NON_SNOOP_EXCLUSIVE_PTL
        )
        requester_binding = resolved.role_binding("requester")
        home_binding = resolved.role_binding("home")
        if not isinstance(
            requester_binding.component,
            ChiNonSnoopExclusiveRequester,
        ):
            raise TypeError(
                "resolved Exclusive requester has another component type"
            )
        if not isinstance(
            home_binding.component, ChiNonSnoopExclusiveHomeNode
        ):
            raise TypeError(
                "resolved Exclusive Home has another component type"
            )
        profile = requester_binding.component.profile
        if requester_binding.node_ids != frozenset(
            (profile.requester_node_id,)
        ):
            raise ValueError(
                "resolved Exclusive requester NodeID disagrees with profile"
            )
        if home_binding.node_ids != frozenset(
            (profile.home_node_id,)
        ):
            raise ValueError(
                "resolved Exclusive Home NodeID disagrees with profile"
            )
        return cls(
            "chi.non_snoop_exclusive.resolved",
            requester=requester_binding.component,
            home=home_binding.component,
            authority_window=(
                resolved.feature_authority.address_claim.window
            ),
        )

    def initial_state(self) -> ChiNonSnoopExclusiveSystemState:
        return ChiNonSnoopExclusiveSystemState(
            self.requester.initial_state(),
            self.home.initial_state(),
        )

    def is_quiescent(
        self,
        state: ChiNonSnoopExclusiveSystemState,
    ) -> bool:
        return (
            isinstance(state, ChiNonSnoopExclusiveSystemState)
            and self.requester.is_quiescent(state.requester)
            and self.home.is_quiescent(state.home)
            and not state.expected_requests
            and not state.expected_read_data
            and not state.expected_write_responses
            and not state.expected_write_data
        )

    def step(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        action: ChiNonSnoopExclusiveSystemAction,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]:
        if not isinstance(state, ChiNonSnoopExclusiveSystemState):
            raise TypeError(
                "non-snoop Exclusive session requires its state type"
            )
        if isinstance(action, ChiSubmitNonSnoopExclusiveRead):
            return self._submit_read(state, action)
        if isinstance(action, ChiSubmitNonSnoopExclusiveWrite):
            return self._submit_write(state, action)
        if isinstance(action, ChiDeliverNonSnoopExclusivePacket):
            return self._deliver(state, action.packet)
        if isinstance(action, ChiCommitNonSnoopExclusiveUpdate):
            return self._commit_update(state, action.update)
        raise TypeError("unknown non-snoop Exclusive system action")

    def _submit_read(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        action: ChiSubmitNonSnoopExclusiveRead,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]:
        submission_fault = self._submission_fault(
            state, action.requester_node_id, action.request
        )
        if submission_fault is not None:
            return submission_fault
        requester_step = self.requester.step(
            state.requester,
            ChiIssueExclusiveReadNoSnp(action.request),
        )
        failure = self._participant_failure(state, requester_step)
        if failure is not None:
            return failure
        packet = ChiNetworkPacket.request(
            action.request,
            source_id=self.profile.requester_node_id,
            target_id=self.profile.home_node_id,
        )
        return self._retain_request(
            state, requester_step.state, packet
        )

    def _submit_write(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        action: ChiSubmitNonSnoopExclusiveWrite,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]:
        submission_fault = self._submission_fault(
            state, action.requester_node_id, action.request
        )
        if submission_fault is not None:
            return submission_fault
        requester_step = self.requester.step(
            state.requester,
            ChiIssueExclusiveWriteNoSnpPtl(
                action.request,
                action.data,
                action.byte_enable,
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
        return self._retain_request(
            state, requester_step.state, packet
        )

    def _submission_fault(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        requester_node_id: int,
        request: ChiReadNoSnpMessage | ChiWriteNoSnpPtlMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ] | None:
        if requester_node_id != self.profile.requester_node_id:
            return self._fault(
                state,
                "requester_authority",
                "submission selects another Requester NodeID",
            )
        if self.authority_window is not None:
            line_address = self.profile.line_address(request)
            if not self.authority_window.contains(
                AddressWindow(
                    line_address,
                    self.profile.monitor_granule_bytes,
                )
            ):
                return self._fault(
                    state,
                    "address_authority",
                    "the full Exclusive monitor granule is outside Home "
                    "authority",
                )
        reasons = CHI_ISSUE_H_CHANNEL_DOMAIN.explain_profile(request)
        if reasons:
            return self._fault(
                state,
                "request_representation",
                "; ".join(reasons),
            )
        return None

    def _retain_request(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        requester_state: ChiNonSnoopExclusiveRequesterState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]:
        key = (
            self.profile.requester_node_id,
            packet.message.transaction_id,
        )
        if (
            key in state.expected_requests
            or key in state.expected_read_data
            or key in state.expected_write_responses
        ):
            return self._fault(
                state,
                "duplicate_delivery",
                "system already retains this original Exclusive identity",
            )
        expected_requests = dict(state.expected_requests)
        expected_requests[key] = packet
        return SemanticStep(
            ChiNonSnoopExclusiveSystemState(
                requester_state,
                state.home,
                expected_requests,
                state.expected_read_data,
                state.expected_write_responses,
                state.expected_write_data,
                state.retained_write_intents,
            ),
            (packet,),
        )

    def _deliver(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        packet: ChiNetworkPacket,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]:
        if packet.packet_index != 0 or packet.packet_count != 1:
            return self._fault(
                state,
                "packetization",
                "the first Exclusive slice requires one packet per message",
            )
        message = packet.message
        if isinstance(
            message, (ChiReadNoSnpMessage, ChiWriteNoSnpPtlMessage)
        ):
            return self._deliver_request(state, packet, message)
        if isinstance(message, ChiCompDataMessage):
            return self._deliver_read_data(state, packet, message)
        if isinstance(message, ChiCompDBIDRespMessage):
            return self._deliver_write_response(state, packet, message)
        if isinstance(message, ChiNonCopyBackWrDataMessage):
            return self._deliver_write_data(state, packet, message)
        return self._fault(
            state,
            "message_type",
            "packet is outside the non-snoop Exclusive lifecycle",
        )

    def _deliver_request(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        packet: ChiNetworkPacket,
        request: ChiReadNoSnpMessage | ChiWriteNoSnpPtlMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
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
                "REQ does not match one requester-produced packet",
            )
        home_action = (
            ChiNonSnoopExclusiveHomeAcceptRead(
                packet.source_id, request
            )
            if isinstance(request, ChiReadNoSnpMessage)
            else ChiNonSnoopExclusiveHomeAcceptWrite(
                packet.source_id, request
            )
        )
        home_step = self.home.step(state.home, home_action)
        failure = self._participant_failure(state, home_step)
        if failure is not None:
            return failure
        if len(home_step.emissions) != 1:
            raise RuntimeError(
                "successful Exclusive Home REQ must emit one completion"
            )
        response = home_step.emissions[0]
        if isinstance(request, ChiReadNoSnpMessage):
            if not isinstance(response, ChiCompDataMessage):
                raise RuntimeError(
                    "Exclusive ReadNoSnp must produce CompData"
                )
            response_packet = ChiNetworkPacket.data(
                response,
                source_id=self.profile.home_node_id,
                target_id=packet.source_id,
            )
            expected_read_data = dict(state.expected_read_data)
            expected_read_data[key] = response_packet
            expected_write_responses = state.expected_write_responses
        else:
            if not isinstance(response, ChiCompDBIDRespMessage):
                raise RuntimeError(
                    "Exclusive WriteNoSnpPtl must produce CompDBIDResp"
                )
            response_packet = ChiNetworkPacket.response(
                response,
                source_id=self.profile.home_node_id,
                target_id=packet.source_id,
            )
            expected_read_data = state.expected_read_data
            expected_write_responses = dict(
                state.expected_write_responses
            )
            expected_write_responses[key] = response_packet
        expected_requests = dict(state.expected_requests)
        del expected_requests[key]
        return SemanticStep(
            ChiNonSnoopExclusiveSystemState(
                state.requester,
                home_step.state,
                expected_requests,
                expected_read_data,
                expected_write_responses,
                state.expected_write_data,
                state.retained_write_intents,
            ),
            (response_packet,),
        )

    def _deliver_read_data(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        packet: ChiNetworkPacket,
        response: ChiCompDataMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]:
        key = (packet.target_id, response.transaction_id)
        if (
            packet.source_id != self.profile.home_node_id
            or state.expected_read_data.get(key) != packet
        ):
            return self._fault(
                state,
                "read_data_correlation",
                "CompData does not match one Home-produced read completion",
            )
        requester_step = self.requester.step(
            state.requester, ChiAcceptExclusiveCompData(response)
        )
        failure = self._participant_failure(state, requester_step)
        if failure is not None:
            return failure
        if requester_step.emissions:
            raise RuntimeError(
                "Exclusive CompData acceptance must not emit another message"
            )
        expected = dict(state.expected_read_data)
        del expected[key]
        return SemanticStep(
            ChiNonSnoopExclusiveSystemState(
                requester_step.state,
                state.home,
                state.expected_requests,
                expected,
                state.expected_write_responses,
                state.expected_write_data,
                state.retained_write_intents,
            )
        )

    def _deliver_write_response(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        packet: ChiNetworkPacket,
        response: ChiCompDBIDRespMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]:
        key = (packet.target_id, response.transaction_id)
        if (
            packet.source_id != self.profile.home_node_id
            or state.expected_write_responses.get(key) != packet
        ):
            return self._fault(
                state,
                "write_response_correlation",
                "CompDBIDResp does not match one Home-produced response",
            )
        retained = state.requester.pending_writes.get(
            response.transaction_id
        )
        if retained is None:
            return self._fault(
                state,
                "write_response_correlation",
                "CompDBIDResp has no retained requester write intent",
            )
        requester_step = self.requester.step(
            state.requester,
            ChiAcceptExclusiveCompDBIDResp(response),
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
                "both pass and fail Exclusive responses must produce DAT"
            )
        data = requester_step.emissions[0]
        data_packet = ChiNetworkPacket.data(
            data,
            source_id=self.profile.requester_node_id,
            target_id=self.profile.home_node_id,
        )
        data_key = (
            self.profile.requester_node_id,
            data.transaction_id,
        )
        if data_key in state.expected_write_data:
            return self._fault(
                state,
                "data_buffer_collision",
                "Home reused an Exclusive DBID before DAT delivery",
            )
        expected_responses = dict(state.expected_write_responses)
        del expected_responses[key]
        expected_data = dict(state.expected_write_data)
        expected_data[data_key] = data_packet
        retained_intents = dict(state.retained_write_intents)
        retained_intents[data_key] = retained
        return SemanticStep(
            ChiNonSnoopExclusiveSystemState(
                requester_step.state,
                state.home,
                state.expected_requests,
                state.expected_read_data,
                expected_responses,
                expected_data,
                retained_intents,
            ),
            (data_packet,),
        )

    def _deliver_write_data(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        packet: ChiNetworkPacket,
        data: ChiNonCopyBackWrDataMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]:
        key = (packet.source_id, data.transaction_id)
        if (
            packet.target_id != self.profile.home_node_id
            or state.expected_write_data.get(key) != packet
        ):
            return self._fault(
                state,
                "write_data_correlation",
                "DAT does not match one requester-produced Exclusive packet",
            )
        home_step = self.home.step(
            state.home,
            ChiNonSnoopExclusiveHomeAcceptData(
                packet.source_id, data
            ),
        )
        failure = self._participant_failure(state, home_step)
        if failure is not None:
            return failure
        if home_step.emissions:
            raise RuntimeError(
                "Exclusive DAT retirement must not emit another message"
            )
        expected_data = dict(state.expected_write_data)
        del expected_data[key]
        retained = dict(state.retained_write_intents)
        del retained[key]
        return SemanticStep(
            ChiNonSnoopExclusiveSystemState(
                state.requester,
                home_step.state,
                state.expected_requests,
                state.expected_read_data,
                state.expected_write_responses,
                expected_data,
                retained,
            )
        )

    def _commit_update(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        update: ChiNonSnoopExclusiveHomeCommitUpdate,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ]:
        if self.authority_window is not None and not (
            self.authority_window.contains(
                AddressWindow(update.line_address, 64)
            )
        ):
            return self._fault(
                state,
                "update_authority",
                "competing update is outside Home authority",
            )
        home_step = self.home.step(state.home, update)
        failure = self._participant_failure(state, home_step)
        if failure is not None:
            return failure
        return SemanticStep(
            ChiNonSnoopExclusiveSystemState(
                state.requester,
                home_step.state,
                state.expected_requests,
                state.expected_read_data,
                state.expected_write_responses,
                state.expected_write_data,
                state.retained_write_intents,
            )
        )

    def _participant_failure(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        transition: SemanticStep,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
        ChiNetworkPacket,
    ] | None:
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        if transition.blocked is not None:
            return SemanticStep(state, blocked=transition.blocked)
        return None

    def _fault(
        self,
        state: ChiNonSnoopExclusiveSystemState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveSystemState,
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
    "ChiCommitNonSnoopExclusiveUpdate",
    "ChiDeliverNonSnoopExclusivePacket",
    "ChiNonSnoopExclusiveSystemAction",
    "ChiNonSnoopExclusiveSystemSession",
    "ChiNonSnoopExclusiveSystemState",
    "ChiSubmitNonSnoopExclusiveRead",
    "ChiSubmitNonSnoopExclusiveWrite",
]
