"""Backing-owning Home participant for typed WriteNoSnp Immediate Writes."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)
from protocol_model.virtual_dut.backend.backing import (
    BackingCommitConflict,
    FullLineBackingCore,
    LineBackingState,
)

from ..interface.write_no_snp import (
    ChiWriteNoSnpFullProfile,
    ChiWriteNoSnpPtlProfile,
)
from ..representation import (
    ChiCompDBIDRespMessage,
    ChiNonCopyBackWrDataMessage,
    ChiRespCode,
    ChiRespErr,
    ChiWriteNoSnpFullMessage,
    ChiWriteNoSnpPtlMessage,
)


_CACHE_LINE_BYTES = 64
_FULL_BYTE_ENABLE = (1 << _CACHE_LINE_BYTES) - 1
_TRANSACTION_ID_LIMIT = 1 << 12

_ChiWriteNoSnpRequest = (
    ChiWriteNoSnpFullMessage | ChiWriteNoSnpPtlMessage
)
_ChiWriteNoSnpProfile = (
    ChiWriteNoSnpFullProfile | ChiWriteNoSnpPtlProfile
)


def _require_node_id(name: str, value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{name} must be a non-negative integer")


def _line_address(request: _ChiWriteNoSnpRequest) -> int:
    """Return the protocol-independent 64-byte backing-line base."""

    return request.address - request.address % _CACHE_LINE_BYTES


@dataclass(frozen=True)
class ChiWriteNoSnpHomePending:
    """One accepted REQ holding a Home DBID until DAT arrives.

    The retained request supplies address and audit context, but its original
    TxnID is no longer a Home allocation key after ``CompDBIDResp``.  Multiple
    live DBIDs can therefore retain the same reused Requester TxnID.
    """

    requester_node_id: int
    request: _ChiWriteNoSnpRequest
    data_buffer_id: int
    response_trace_tag: bool
    expected_backing_version: int

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(
            self.request,
            (ChiWriteNoSnpFullMessage, ChiWriteNoSnpPtlMessage),
        ):
            raise TypeError(
                "WriteNoSnp Home pending requires a typed Immediate Write"
            )
        for name, value in (
            ("data_buffer_id", self.data_buffer_id),
            ("expected_backing_version", self.expected_backing_version),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{name} must be non-negative")
        if self.data_buffer_id >= _TRANSACTION_ID_LIMIT:
            raise ValueError("data_buffer_id must be 12-bit")
        if type(self.response_trace_tag) is not bool:
            raise TypeError("response_trace_tag must be bool")


@dataclass(frozen=True)
class ChiWriteNoSnpHomeAcceptRequest:
    requester_node_id: int
    request: _ChiWriteNoSnpRequest

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(
            self.request,
            (ChiWriteNoSnpFullMessage, ChiWriteNoSnpPtlMessage),
        ):
            raise TypeError(
                "WriteNoSnp Home request action requires a typed "
                "Immediate Write"
            )


@dataclass(frozen=True)
class ChiWriteNoSnpHomeAcceptData:
    requester_node_id: int
    data: ChiNonCopyBackWrDataMessage

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(self.data, ChiNonCopyBackWrDataMessage):
            raise TypeError(
                "WriteNoSnp Home data action requires NonCopyBackWrData"
            )


ChiWriteNoSnpHomeAction = (
    ChiWriteNoSnpHomeAcceptRequest | ChiWriteNoSnpHomeAcceptData
)


@dataclass(frozen=True)
class ChiWriteNoSnpHomeState:
    """Single-authority backing state and outstanding DBID reservations.

    ``pending_by_dbid`` is the only live transaction index after a combined
    response.  Requester original TxnIDs are deliberately not unique here.
    """

    backing: LineBackingState
    pending_by_dbid: Mapping[int, ChiWriteNoSnpHomePending] = field(
        default_factory=dict
    )
    next_data_buffer_id: int = 0
    accepted_count: int = 0
    committed_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.backing, LineBackingState):
            raise TypeError(
                "WriteNoSnp Home backing requires LineBackingState"
            )
        pending = dict(self.pending_by_dbid)
        if any(
            not isinstance(item, ChiWriteNoSnpHomePending)
            or data_buffer_id != item.data_buffer_id
            for data_buffer_id, item in pending.items()
        ):
            raise ValueError(
                "WriteNoSnp Home pending keys must match granted DBIDs"
            )
        addresses = tuple(
            _line_address(item.request) for item in pending.values()
        )
        if len(set(addresses)) != len(addresses):
            raise ValueError(
                "the first WriteNoSnp Home profile reserves one writer per "
                "line"
            )
        for name, value in (
            ("next_data_buffer_id", self.next_data_buffer_id),
            ("accepted_count", self.accepted_count),
            ("committed_count", self.committed_count),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{name} must be non-negative")
        if self.next_data_buffer_id >= _TRANSACTION_ID_LIMIT:
            raise ValueError("next_data_buffer_id must be 12-bit")
        if self.committed_count > self.accepted_count:
            raise ValueError(
                "WriteNoSnp committed count cannot exceed accepted count"
            )
        object.__setattr__(
            self,
            "pending_by_dbid",
            MappingProxyType(pending),
        )

class ChiWriteNoSnpHomeNode(
    SemanticComponent[
        ChiWriteNoSnpHomeAction,
        ChiWriteNoSnpHomeState,
        ChiCompDBIDRespMessage,
    ]
):
    """Accept typed non-snoop writes and commit DAT exactly once.

    This component is the sole owner of its ``LineBackingState`` during one
    execution.  Sharing the same ``FullLineBackingCore`` object with another
    runtime does not merge their states; a future aggregate Home must provide
    the common state owner before coherence and Immediate Write sessions can
    be driven together.
    """

    def __init__(
        self,
        name: str,
        profile: _ChiWriteNoSnpProfile,
        *,
        backing_core: FullLineBackingCore,
        transaction_capacity: int = 4,
        initial_data_buffer_id: int = 0x200,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("WriteNoSnp Home requires a name")
        if not isinstance(
            profile,
            (ChiWriteNoSnpFullProfile, ChiWriteNoSnpPtlProfile),
        ):
            raise TypeError(
                "WriteNoSnp Home requires a Full or Ptl profile"
            )
        if not isinstance(backing_core, FullLineBackingCore):
            raise TypeError(
                "WriteNoSnp Home requires FullLineBackingCore"
            )
        if backing_core.line_bytes != _CACHE_LINE_BYTES:
            raise ValueError(
                "WriteNoSnp requires 64-byte backing lines"
            )
        if (
            not isinstance(transaction_capacity, int)
            or isinstance(transaction_capacity, bool)
            or not 0 < transaction_capacity <= _TRANSACTION_ID_LIMIT
        ):
            raise ValueError(
                "transaction capacity must be in 1..4096"
            )
        if (
            not isinstance(initial_data_buffer_id, int)
            or isinstance(initial_data_buffer_id, bool)
            or not 0
            <= initial_data_buffer_id
            < _TRANSACTION_ID_LIMIT
        ):
            raise ValueError("initial_data_buffer_id must be 12-bit")
        self.name = name
        self.profile = profile
        self.backing_core = backing_core
        self.transaction_capacity = transaction_capacity
        self.initial_data_buffer_id = initial_data_buffer_id

    def initial_state(self) -> ChiWriteNoSnpHomeState:
        return ChiWriteNoSnpHomeState(
            self.backing_core.initial_state(),
            next_data_buffer_id=self.initial_data_buffer_id,
        )

    def is_quiescent(self, state: ChiWriteNoSnpHomeState) -> bool:
        return (
            isinstance(state, ChiWriteNoSnpHomeState)
            and not state.pending_by_dbid
        )

    def step(
        self,
        state: ChiWriteNoSnpHomeState,
        action: ChiWriteNoSnpHomeAction,
    ) -> SemanticStep[
        ChiWriteNoSnpHomeState,
        ChiCompDBIDRespMessage,
    ]:
        if not isinstance(state, ChiWriteNoSnpHomeState):
            raise TypeError("WriteNoSnp Home requires its state type")
        if isinstance(action, ChiWriteNoSnpHomeAcceptRequest):
            return self._accept_request(
                state,
                action.requester_node_id,
                action.request,
            )
        if isinstance(action, ChiWriteNoSnpHomeAcceptData):
            return self._accept_data(
                state,
                action.requester_node_id,
                action.data,
            )
        raise TypeError("unknown WriteNoSnp Home action")

    def _accept_request(
        self,
        state: ChiWriteNoSnpHomeState,
        requester_node_id: int,
        request: _ChiWriteNoSnpRequest,
    ) -> SemanticStep[
        ChiWriteNoSnpHomeState,
        ChiCompDBIDRespMessage,
    ]:
        reasons = self.profile.explain_request(request)
        if reasons:
            return self._fault(
                state,
                "request_profile",
                "; ".join(reasons),
            )
        if requester_node_id != self.profile.requester_node_id:
            return self._fault(
                state,
                "requester_identity",
                "WriteNoSnp came from another Requester NodeID",
            )
        line_address = _line_address(request)
        if any(
            _line_address(item.request) == line_address
            for item in state.pending_by_dbid.values()
        ):
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.line[{line_address:#x}]",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=1,
                    reason=(
                        "the first WriteNoSnp Home profile serializes "
                        "same-line writes"
                    ),
                    location=self.name,
                ),
            )
        if len(state.pending_by_dbid) >= self.transaction_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.data_buffer",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.transaction_capacity,
                    reason="WriteNoSnp Home DBID capacity is full",
                    location=self.name,
                ),
            )
        record = state.backing.line_at(line_address)
        if record is None:
            return self._fault(
                state,
                "backing_address",
                f"Home has no backing line at {line_address:#x}",
            )
        data_buffer_id = self._next_free_dbid(state)
        response = ChiCompDBIDRespMessage(
            transaction_id=request.transaction_id,
            data_buffer_id=data_buffer_id,
            response_error=ChiRespErr.OK,
            response=ChiRespCode.I,
            trace_tag=request.trace_tag,
        )
        pending = dict(state.pending_by_dbid)
        pending[data_buffer_id] = ChiWriteNoSnpHomePending(
            requester_node_id,
            request,
            data_buffer_id,
            response.trace_tag,
            record.version,
        )
        candidate = ChiWriteNoSnpHomeState(
            state.backing,
            pending,
            (data_buffer_id + 1) % _TRANSACTION_ID_LIMIT,
            state.accepted_count + 1,
            state.committed_count,
        )
        return SemanticStep(candidate, (response,))

    def _accept_data(
        self,
        state: ChiWriteNoSnpHomeState,
        requester_node_id: int,
        data: ChiNonCopyBackWrDataMessage,
    ) -> SemanticStep[
        ChiWriteNoSnpHomeState,
        ChiCompDBIDRespMessage,
    ]:
        pending_item = state.pending_by_dbid.get(data.transaction_id)
        if pending_item is None:
            return self._fault(
                state,
                "unknown_data_buffer",
                "NonCopyBackWrData does not select a live Home DBID",
            )
        if pending_item.requester_node_id != requester_node_id:
            return self._fault(
                state,
                "data_requester",
                "NonCopyBackWrData came from another Requester",
            )
        reasons: list[str] = []
        if data.response is not ChiRespCode.I:
            reasons.append("NonCopyBackWrData requires Resp=I")
        if data.response_error is not ChiRespErr.OK:
            reasons.append(
                "the first WriteNoSnp DAT profile requires RespErr=OK"
            )
        if data.data_id != 0:
            reasons.append(
                "single-packet 512-bit WriteNoSnp requires DataID=0"
            )
        if data.critical_chunk_id != (
            pending_item.request.address >> 4
        ) & 0b11:
            reasons.append(
                "WriteNoSnp DAT CCID must equal original Addr[5:4]"
            )
        if data.trace_tag != pending_item.response_trace_tag:
            reasons.append(
                "WriteNoSnp DAT TraceTag must match CompDBIDResp"
            )
        if data.data >= 1 << 512:
            reasons.append(
                "WriteNoSnp data must fit one 512-bit line"
            )
        request = pending_item.request
        reasons.extend(
            self.profile.explain_payload(
                request,
                data.data,
                data.byte_enable,
            )
        )
        if reasons:
            return self._fault(
                state,
                "data_profile",
                "; ".join(reasons),
            )
        line_address = _line_address(pending_item.request)
        current = state.backing.line_at(line_address)
        if (
            current is None
            or current.version
            != pending_item.expected_backing_version
        ):
            return self._fault(
                state,
                "backing_version",
                "the backing line changed while the Home DBID was live",
            )
        try:
            if isinstance(
                pending_item.request,
                ChiWriteNoSnpFullMessage,
            ):
                prepared = self.backing_core.prepare_write(
                    state.backing,
                    line_address,
                    data.data,
                )
                mutation = self.backing_core.commit_write(
                    state.backing,
                    prepared,
                )
            else:
                prepared_patch = self.backing_core.prepare_masked_write(
                    state.backing,
                    line_address,
                    data.data,
                    data.byte_enable,
                )
                mutation = self.backing_core.commit_masked_write(
                    state.backing,
                    prepared_patch,
                )
        except (BackingCommitConflict, KeyError, TypeError, ValueError) as error:
            return self._fault(
                state,
                "backing_commit",
                str(error),
            )
        pending = dict(state.pending_by_dbid)
        del pending[data.transaction_id]
        candidate = ChiWriteNoSnpHomeState(
            mutation.state,
            pending,
            state.next_data_buffer_id,
            state.accepted_count,
            state.committed_count + 1,
        )
        return SemanticStep(candidate)

    def _next_free_dbid(
        self,
        state: ChiWriteNoSnpHomeState,
    ) -> int:
        candidate = state.next_data_buffer_id
        for _ in range(_TRANSACTION_ID_LIMIT):
            if candidate not in state.pending_by_dbid:
                return candidate
            candidate = (candidate + 1) % _TRANSACTION_ID_LIMIT
        raise RuntimeError(
            "validated WriteNoSnp Home capacity has no free DBID"
        )

    def _fault(
        self,
        state: ChiWriteNoSnpHomeState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[
        ChiWriteNoSnpHomeState,
        ChiCompDBIDRespMessage,
    ]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.name,
            ),
        )


__all__ = [
    "ChiWriteNoSnpHomeAcceptData",
    "ChiWriteNoSnpHomeAcceptRequest",
    "ChiWriteNoSnpHomeAction",
    "ChiWriteNoSnpHomeNode",
    "ChiWriteNoSnpHomePending",
    "ChiWriteNoSnpHomeState",
]
