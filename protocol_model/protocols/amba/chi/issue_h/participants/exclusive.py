"""Single-authority Home for non-snoop Exclusive Read/WriteNoSnpPtl.

The Home owns one backing state, one System-monitor reservation for the
configured ``SrcID+LPID`` logical processor, and every live write DBID.  The
monitor is explicit state rather than an inference from backing versions:
versions protect prepare/commit atomicity, while the monitor decides whether
an Exclusive Store passes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeAlias

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

from ..interface.exclusive import ChiNonSnoopExclusivePtlProfile
from ..representation import (
    ChiCompDBIDRespMessage,
    ChiCompDataMessage,
    ChiNonCopyBackWrDataMessage,
    ChiReadNoSnpMessage,
    ChiRespCode,
    ChiRespErr,
    ChiWriteNoSnpPtlMessage,
)


_CACHE_LINE_BYTES = 64
_TRANSACTION_ID_LIMIT = 1 << 12


def _require_node_id(name: str, value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{name} must be a non-negative integer")


def _require_lpid(name: str, value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < (1 << 5)
    ):
        raise ValueError(f"{name} must be a 5-bit integer")


@dataclass(frozen=True)
class ChiNonSnoopExclusiveReservation:
    """One allocated System-monitor entry.

    The profile deliberately monitors the whole 64-byte backing line.  That
    conservative granule is permitted to produce a false failure when a
    neighboring byte changes, but it can never produce a false success.
    """

    requester_node_id: int
    logical_processor_id: int
    read: ChiReadNoSnpMessage
    line_address: int

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        _require_lpid(
            "logical_processor_id", self.logical_processor_id
        )
        if not isinstance(self.read, ChiReadNoSnpMessage):
            raise TypeError(
                "non-snoop Exclusive reservation requires ReadNoSnp"
            )
        if not self.read.exclusive:
            raise ValueError(
                "non-snoop Exclusive reservation requires Excl=1"
            )
        if self.read.logical_processor_id != self.logical_processor_id:
            raise ValueError(
                "reservation LPID must match the retained ReadNoSnp"
            )
        if (
            not isinstance(self.line_address, int)
            or isinstance(self.line_address, bool)
            or self.line_address < 0
            or self.line_address % _CACHE_LINE_BYTES
        ):
            raise ValueError(
                "reservation line_address must be 64-byte aligned"
            )
        if not (
            self.line_address
            <= self.read.address
            < self.line_address + _CACHE_LINE_BYTES
        ):
            raise ValueError(
                "reservation line must contain the retained read address"
            )

    def matches(
        self,
        requester_node_id: int,
        write: ChiWriteNoSnpPtlMessage,
        profile: ChiNonSnoopExclusivePtlProfile,
    ) -> bool:
        return (
            requester_node_id == self.requester_node_id
            and write.logical_processor_id
            == self.logical_processor_id
            and not profile.explain_pair(self.read, write)
        )

    def overlaps(self, address: int, size_bytes: int) -> bool:
        return (
            address < self.line_address + _CACHE_LINE_BYTES
            and self.line_address < address + size_bytes
        )


@dataclass(frozen=True)
class ChiNonSnoopExclusiveHomePendingWrite:
    requester_node_id: int
    request: ChiWriteNoSnpPtlMessage
    data_buffer_id: int
    exclusive_passed: bool
    response_trace_tag: bool
    expected_backing_version: int

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(self.request, ChiWriteNoSnpPtlMessage):
            raise TypeError(
                "pending non-snoop Exclusive write requires WriteNoSnpPtl"
            )
        if type(self.exclusive_passed) is not bool:
            raise TypeError("exclusive_passed must be bool")
        if type(self.response_trace_tag) is not bool:
            raise TypeError("response_trace_tag must be bool")
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


@dataclass(frozen=True)
class ChiNonSnoopExclusiveHomeAcceptRead:
    requester_node_id: int
    request: ChiReadNoSnpMessage

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(self.request, ChiReadNoSnpMessage):
            raise TypeError(
                "non-snoop Exclusive Home read requires ReadNoSnp"
            )


@dataclass(frozen=True)
class ChiNonSnoopExclusiveHomeAcceptWrite:
    requester_node_id: int
    request: ChiWriteNoSnpPtlMessage

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(self.request, ChiWriteNoSnpPtlMessage):
            raise TypeError(
                "non-snoop Exclusive Home write requires WriteNoSnpPtl"
            )


@dataclass(frozen=True)
class ChiNonSnoopExclusiveHomeAcceptData:
    requester_node_id: int
    data: ChiNonCopyBackWrDataMessage

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(self.data, ChiNonCopyBackWrDataMessage):
            raise TypeError(
                "non-snoop Exclusive Home data requires "
                "NonCopyBackWrData"
            )


@dataclass(frozen=True)
class ChiNonSnoopExclusiveHomeCommitUpdate:
    """Commit another LP's line-positioned update and observe it atomically.

    This is a Home operation boundary rather than another CHI opcode.  It
    gives later write lifecycles one explicit method to call after their own
    protocol admission, while keeping backing mutation and System-monitor
    invalidation under this aggregate Home's single state authority.
    """

    requester_node_id: int
    logical_processor_id: int
    line_address: int
    data: int
    byte_enable: int

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        _require_lpid(
            "logical_processor_id", self.logical_processor_id
        )
        if (
            not isinstance(self.line_address, int)
            or isinstance(self.line_address, bool)
            or self.line_address < 0
            or self.line_address % _CACHE_LINE_BYTES
        ):
            raise ValueError(
                "committed update line_address must be 64-byte aligned"
            )
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or not 0 <= self.data < (1 << 512)
        ):
            raise ValueError("committed update data must fit one line")
        if (
            not isinstance(self.byte_enable, int)
            or isinstance(self.byte_enable, bool)
            or not 0 <= self.byte_enable < (1 << _CACHE_LINE_BYTES)
        ):
            raise ValueError("committed update byte_enable must be 64-bit")


ChiNonSnoopExclusiveHomeAction: TypeAlias = (
    ChiNonSnoopExclusiveHomeAcceptRead
    | ChiNonSnoopExclusiveHomeAcceptWrite
    | ChiNonSnoopExclusiveHomeAcceptData
    | ChiNonSnoopExclusiveHomeCommitUpdate
)

ChiNonSnoopExclusiveHomeEmission: TypeAlias = (
    ChiCompDataMessage | ChiCompDBIDRespMessage
)


@dataclass(frozen=True)
class ChiNonSnoopExclusiveHomeState:
    backing: LineBackingState
    reservation: ChiNonSnoopExclusiveReservation | None = None
    pending_by_dbid: Mapping[
        int, ChiNonSnoopExclusiveHomePendingWrite
    ] = field(default_factory=dict)
    next_data_buffer_id: int = 0
    accepted_read_count: int = 0
    accepted_write_count: int = 0
    committed_write_count: int = 0
    failed_write_count: int = 0
    invalidation_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.backing, LineBackingState):
            raise TypeError(
                "non-snoop Exclusive Home backing requires "
                "LineBackingState"
            )
        if self.reservation is not None and not isinstance(
            self.reservation, ChiNonSnoopExclusiveReservation
        ):
            raise TypeError(
                "non-snoop Exclusive Home reservation has another type"
            )
        pending = dict(self.pending_by_dbid)
        if any(
            not isinstance(
                item, ChiNonSnoopExclusiveHomePendingWrite
            )
            or data_buffer_id != item.data_buffer_id
            for data_buffer_id, item in pending.items()
        ):
            raise ValueError(
                "non-snoop Exclusive Home pending keys must match DBIDs"
            )
        line_addresses = tuple(
            item.request.address
            - item.request.address % _CACHE_LINE_BYTES
            for item in pending.values()
        )
        if len(set(line_addresses)) != len(line_addresses):
            raise ValueError(
                "the first non-snoop Exclusive Home serializes writers "
                "per line"
            )
        for name, value in (
            ("next_data_buffer_id", self.next_data_buffer_id),
            ("accepted_read_count", self.accepted_read_count),
            ("accepted_write_count", self.accepted_write_count),
            ("committed_write_count", self.committed_write_count),
            ("failed_write_count", self.failed_write_count),
            ("invalidation_count", self.invalidation_count),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{name} must be non-negative")
        if self.next_data_buffer_id >= _TRANSACTION_ID_LIMIT:
            raise ValueError("next_data_buffer_id must be 12-bit")
        if (
            self.committed_write_count + self.failed_write_count
            > self.accepted_write_count
        ):
            raise ValueError(
                "retired Exclusive writes cannot exceed accepted writes"
            )
        object.__setattr__(
            self, "pending_by_dbid", MappingProxyType(pending)
        )


class ChiNonSnoopExclusiveHomeNode(
    SemanticComponent[
        ChiNonSnoopExclusiveHomeAction,
        ChiNonSnoopExclusiveHomeState,
        ChiNonSnoopExclusiveHomeEmission,
    ]
):
    """Own the System monitor, backing, and conditional write commit."""

    def __init__(
        self,
        name: str,
        profile: ChiNonSnoopExclusivePtlProfile,
        *,
        backing_core: FullLineBackingCore,
        transaction_capacity: int = 4,
        initial_data_buffer_id: int = 0x200,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("non-snoop Exclusive Home requires a name")
        if not isinstance(profile, ChiNonSnoopExclusivePtlProfile):
            raise TypeError(
                "non-snoop Exclusive Home requires its profile"
            )
        if not isinstance(backing_core, FullLineBackingCore):
            raise TypeError(
                "non-snoop Exclusive Home requires FullLineBackingCore"
            )
        if backing_core.line_bytes != _CACHE_LINE_BYTES:
            raise ValueError(
                "non-snoop Exclusive Home requires 64-byte backing lines"
            )
        if (
            not isinstance(transaction_capacity, int)
            or isinstance(transaction_capacity, bool)
            or not 0 < transaction_capacity <= _TRANSACTION_ID_LIMIT
        ):
            raise ValueError(
                "transaction_capacity must be in the range 1..4096"
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

    def initial_state(self) -> ChiNonSnoopExclusiveHomeState:
        return ChiNonSnoopExclusiveHomeState(
            self.backing_core.initial_state(),
            next_data_buffer_id=self.initial_data_buffer_id,
        )

    def is_quiescent(
        self,
        state: ChiNonSnoopExclusiveHomeState,
    ) -> bool:
        return (
            isinstance(state, ChiNonSnoopExclusiveHomeState)
            and not state.pending_by_dbid
        )

    def step(
        self,
        state: ChiNonSnoopExclusiveHomeState,
        action: ChiNonSnoopExclusiveHomeAction,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveHomeState,
        ChiNonSnoopExclusiveHomeEmission,
    ]:
        if not isinstance(state, ChiNonSnoopExclusiveHomeState):
            raise TypeError(
                "non-snoop Exclusive Home requires its state type"
            )
        if isinstance(action, ChiNonSnoopExclusiveHomeAcceptRead):
            return self._accept_read(
                state, action.requester_node_id, action.request
            )
        if isinstance(action, ChiNonSnoopExclusiveHomeAcceptWrite):
            return self._accept_write(
                state, action.requester_node_id, action.request
            )
        if isinstance(action, ChiNonSnoopExclusiveHomeAcceptData):
            return self._accept_data(
                state, action.requester_node_id, action.data
            )
        if isinstance(action, ChiNonSnoopExclusiveHomeCommitUpdate):
            return self._commit_update(state, action)
        raise TypeError("unknown non-snoop Exclusive Home action")

    def _accept_read(
        self,
        state: ChiNonSnoopExclusiveHomeState,
        requester_node_id: int,
        request: ChiReadNoSnpMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveHomeState,
        ChiNonSnoopExclusiveHomeEmission,
    ]:
        reasons = self.profile.explain_read(request)
        if reasons:
            return self._fault(
                state, "read_profile", "; ".join(reasons)
            )
        identity_reason = self._identity_reason(
            requester_node_id, request.logical_processor_id
        )
        if identity_reason is not None:
            return self._fault(
                state, "read_identity", identity_reason
            )
        line_address = self.profile.line_address(request)
        if self._line_pending(state, line_address):
            return self._line_blocked(state, line_address)
        record = state.backing.line_at(line_address)
        if record is None:
            return self._fault(
                state,
                "backing_address",
                f"Home has no backing line at {line_address:#x}",
            )
        reservation = ChiNonSnoopExclusiveReservation(
            requester_node_id,
            request.logical_processor_id,
            request,
            line_address,
        )
        response = ChiCompDataMessage(
            transaction_id=request.transaction_id,
            data=record.data,
            data_id=0,
            home_node_id=self.profile.home_node_id,
            response_error=ChiRespErr.EXOK,
            response=ChiRespCode.I,
            critical_chunk_id=self.profile.critical_chunk_id(request),
            trace_tag=request.trace_tag,
        )
        return SemanticStep(
            ChiNonSnoopExclusiveHomeState(
                state.backing,
                reservation,
                state.pending_by_dbid,
                state.next_data_buffer_id,
                state.accepted_read_count + 1,
                state.accepted_write_count,
                state.committed_write_count,
                state.failed_write_count,
                state.invalidation_count,
            ),
            (response,),
        )

    def _accept_write(
        self,
        state: ChiNonSnoopExclusiveHomeState,
        requester_node_id: int,
        request: ChiWriteNoSnpPtlMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveHomeState,
        ChiNonSnoopExclusiveHomeEmission,
    ]:
        reasons = self.profile.explain_write(request)
        if reasons:
            return self._fault(
                state, "write_profile", "; ".join(reasons)
            )
        identity_reason = self._identity_reason(
            requester_node_id, request.logical_processor_id
        )
        if identity_reason is not None:
            return self._fault(
                state, "write_identity", identity_reason
            )
        line_address = self.profile.line_address(request)
        if self._line_pending(state, line_address):
            return self._line_blocked(state, line_address)
        if len(state.pending_by_dbid) >= self.transaction_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.data_buffer",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.transaction_capacity,
                    reason=(
                        "non-snoop Exclusive Home DBID capacity is full"
                    ),
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
        passed = (
            state.reservation is not None
            and state.reservation.matches(
                requester_node_id, request, self.profile
            )
        )
        dbid = self._next_free_dbid(state)
        response = ChiCompDBIDRespMessage(
            transaction_id=request.transaction_id,
            data_buffer_id=dbid,
            response_error=(
                ChiRespErr.EXOK if passed else ChiRespErr.OK
            ),
            response=ChiRespCode.I,
            trace_tag=request.trace_tag,
        )
        pending = dict(state.pending_by_dbid)
        pending[dbid] = ChiNonSnoopExclusiveHomePendingWrite(
            requester_node_id,
            request,
            dbid,
            passed,
            response.trace_tag,
            record.version,
        )
        return SemanticStep(
            ChiNonSnoopExclusiveHomeState(
                state.backing,
                None,
                pending,
                (dbid + 1) % _TRANSACTION_ID_LIMIT,
                state.accepted_read_count,
                state.accepted_write_count + 1,
                state.committed_write_count,
                state.failed_write_count,
                state.invalidation_count,
            ),
            (response,),
        )

    def _accept_data(
        self,
        state: ChiNonSnoopExclusiveHomeState,
        requester_node_id: int,
        data: ChiNonCopyBackWrDataMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveHomeState,
        ChiNonSnoopExclusiveHomeEmission,
    ]:
        pending_item = state.pending_by_dbid.get(data.transaction_id)
        if pending_item is None:
            return self._fault(
                state,
                "unknown_data_buffer",
                "NonCopyBackWrData does not select a live Exclusive DBID",
            )
        if pending_item.requester_node_id != requester_node_id:
            return self._fault(
                state,
                "data_requester",
                "NonCopyBackWrData came from another Requester",
            )
        reasons: list[str] = []
        if data.response != ChiRespCode.I:
            reasons.append("NonCopyBackWrData requires Resp=I")
        if data.response_error is not ChiRespErr.OK:
            reasons.append("Exclusive write DAT requires RespErr=OK")
        if data.data_id != 0:
            reasons.append(
                "512-bit Exclusive WriteNoSnpPtl requires DataID=0"
            )
        if (
            data.critical_chunk_id
            != self.profile.critical_chunk_id(pending_item.request)
        ):
            reasons.append(
                "Exclusive WriteNoSnpPtl DAT CCID must equal original "
                "Addr[5:4]"
            )
        if data.trace_tag != pending_item.response_trace_tag:
            reasons.append(
                "Exclusive WriteNoSnpPtl DAT TraceTag must match "
                "CompDBIDResp"
            )
        reasons.extend(
            self.profile.explain_payload(
                pending_item.request,
                data.data,
                data.byte_enable,
            )
        )
        if reasons:
            return self._fault(
                state, "data_profile", "; ".join(reasons)
            )
        backing = state.backing
        committed_delta = 0
        failed_delta = 0
        if pending_item.exclusive_passed:
            line_address = self.profile.line_address(
                pending_item.request
            )
            current = state.backing.line_at(line_address)
            if (
                current is None
                or current.version
                != pending_item.expected_backing_version
            ):
                return self._fault(
                    state,
                    "backing_version",
                    "backing changed after the Exclusive check passed",
                )
            try:
                prepared = self.backing_core.prepare_masked_write(
                    state.backing,
                    line_address,
                    data.data,
                    data.byte_enable,
                )
                mutation = self.backing_core.commit_masked_write(
                    state.backing,
                    prepared,
                )
            except (
                BackingCommitConflict,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                return self._fault(
                    state, "backing_commit", str(error)
                )
            backing = mutation.state
            committed_delta = 1
        else:
            failed_delta = 1
        pending = dict(state.pending_by_dbid)
        del pending[data.transaction_id]
        return SemanticStep(
            ChiNonSnoopExclusiveHomeState(
                backing,
                state.reservation,
                pending,
                state.next_data_buffer_id,
                state.accepted_read_count,
                state.accepted_write_count,
                state.committed_write_count + committed_delta,
                state.failed_write_count + failed_delta,
                state.invalidation_count,
            )
        )

    def _commit_update(
        self,
        state: ChiNonSnoopExclusiveHomeState,
        action: ChiNonSnoopExclusiveHomeCommitUpdate,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveHomeState,
        ChiNonSnoopExclusiveHomeEmission,
    ]:
        if self._line_pending(state, action.line_address):
            return self._line_blocked(state, action.line_address)
        try:
            prepared = self.backing_core.prepare_masked_write(
                state.backing,
                action.line_address,
                action.data,
                action.byte_enable,
            )
            mutation = self.backing_core.commit_masked_write(
                state.backing,
                prepared,
            )
        except (
            BackingCommitConflict,
            KeyError,
            TypeError,
            ValueError,
        ) as error:
            return self._fault(state, "observed_update_commit", str(error))
        reservation = state.reservation
        invalidate = False
        if reservation is not None and action.byte_enable:
            same_lp = (
                action.requester_node_id
                == reservation.requester_node_id
                and action.logical_processor_id
                == reservation.logical_processor_id
            )
            invalidate = (
                not same_lp
                and action.line_address == reservation.line_address
            )
        return SemanticStep(
            ChiNonSnoopExclusiveHomeState(
                mutation.state,
                None if invalidate else reservation,
                state.pending_by_dbid,
                state.next_data_buffer_id,
                state.accepted_read_count,
                state.accepted_write_count,
                state.committed_write_count,
                state.failed_write_count,
                state.invalidation_count + int(invalidate),
            )
        )

    def _identity_reason(
        self,
        requester_node_id: int,
        logical_processor_id: int,
    ) -> str | None:
        if requester_node_id != self.profile.requester_node_id:
            return "request came from another Requester NodeID"
        if logical_processor_id != self.profile.logical_processor_id:
            return "request LPID does not match the configured logical thread"
        return None

    @staticmethod
    def _line_pending(
        state: ChiNonSnoopExclusiveHomeState,
        line_address: int,
    ) -> bool:
        return any(
            item.request.address
            - item.request.address % _CACHE_LINE_BYTES
            == line_address
            for item in state.pending_by_dbid.values()
        )

    def _line_blocked(
        self,
        state: ChiNonSnoopExclusiveHomeState,
        line_address: int,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveHomeState,
        ChiNonSnoopExclusiveHomeEmission,
    ]:
        return SemanticStep(
            state,
            blocked=ResourceDemand(
                f"{self.name}.line[{line_address:#x}]",
                ConstraintScope.VIRTUAL_DUT,
                available=0,
                capacity=1,
                reason=(
                    "the first non-snoop Exclusive Home serializes "
                    "same-line access while a write DBID is live"
                ),
                location=self.name,
            ),
        )

    def _next_free_dbid(
        self,
        state: ChiNonSnoopExclusiveHomeState,
    ) -> int:
        candidate = state.next_data_buffer_id
        for _ in range(_TRANSACTION_ID_LIMIT):
            if candidate not in state.pending_by_dbid:
                return candidate
            candidate = (candidate + 1) % _TRANSACTION_ID_LIMIT
        raise RuntimeError(
            "validated non-snoop Exclusive Home has no free DBID"
        )

    def _fault(
        self,
        state: ChiNonSnoopExclusiveHomeState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveHomeState,
        ChiNonSnoopExclusiveHomeEmission,
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
    "ChiNonSnoopExclusiveHomeAcceptData",
    "ChiNonSnoopExclusiveHomeAcceptRead",
    "ChiNonSnoopExclusiveHomeAcceptWrite",
    "ChiNonSnoopExclusiveHomeAction",
    "ChiNonSnoopExclusiveHomeCommitUpdate",
    "ChiNonSnoopExclusiveHomeEmission",
    "ChiNonSnoopExclusiveHomeNode",
    "ChiNonSnoopExclusiveHomePendingWrite",
    "ChiNonSnoopExclusiveHomeState",
    "ChiNonSnoopExclusiveReservation",
]
