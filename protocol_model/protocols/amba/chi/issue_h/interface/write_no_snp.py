"""Requester-side contracts for the first CHI Immediate Write slices.

The represented transaction is deliberately narrow:

``WriteNoSnp{Ptl,Full}(original TxnID) -> CompDBIDResp(Home DBID)
-> NonCopyBackWrData(Home DBID)``.

Full and Ptl retain distinct typed REQ/profile/issue forms.  Their common
TxnID-to-DBID correlation, pending state, and DAT emission live in one
family-level ledger.  REQ/RSP/DAT routing identities and exact packet
provenance remain system contracts above this interface-local lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeAlias

from protocol_model.semantics import (
    ConstraintKind,
    ConstraintScope,
    ResourceDecl,
    ResourceDemand,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
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
_CACHE_LINE_DATA_LIMIT = 1 << (_CACHE_LINE_BYTES * 8)
_FULL_BYTE_ENABLE = (1 << _CACHE_LINE_BYTES) - 1
_MAX_OUTSTANDING_TRANSACTIONS = 1024


def _validate_profile_shape(
    requester_node_id: int,
    home_node_id: int,
    data_width: int,
    outstanding_capacity: int,
    *,
    operation: str,
) -> None:
    for name, value in (
        ("requester_node_id", requester_node_id),
        ("home_node_id", home_node_id),
    ):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ValueError(f"{name} must be a non-negative integer")
    if requester_node_id == home_node_id:
        raise ValueError("Requester and Home NodeIDs must differ")
    if data_width != 512:
        raise ValueError(
            f"the first {operation} profile requires a 512-bit DAT channel"
        )
    if (
        not isinstance(outstanding_capacity, int)
        or isinstance(outstanding_capacity, bool)
        or outstanding_capacity <= 0
        or outstanding_capacity > _MAX_OUTSTANDING_TRANSACTIONS
    ):
        raise ValueError(
            "outstanding capacity must be in the Issue H range 1..1024"
        )


def _payload_shape_reasons(
    operation: str,
    data: int,
    byte_enable: int,
) -> list[str]:
    reasons: list[str] = []
    if (
        not isinstance(data, int)
        or isinstance(data, bool)
        or not 0 <= data < _CACHE_LINE_DATA_LIMIT
    ):
        reasons.append(
            f"{operation} operation data must fit one 512-bit line"
        )
    if (
        not isinstance(byte_enable, int)
        or isinstance(byte_enable, bool)
        or not 0 <= byte_enable <= _FULL_BYTE_ENABLE
    ):
        reasons.append(f"{operation} byte_enable must be 64-bit")
    return reasons


@dataclass(frozen=True)
class ChiWriteNoSnpFullProfile:
    """Restricted full-line, single-packet Immediate Write profile."""

    requester_node_id: int
    home_node_id: int
    data_width: int = 512
    outstanding_capacity: int = 8

    def __post_init__(self) -> None:
        _validate_profile_shape(
            self.requester_node_id,
            self.home_node_id,
            self.data_width,
            self.outstanding_capacity,
            operation="WriteNoSnpFull",
        )

    def explain_request(
        self,
        request: ChiWriteNoSnpFullMessage,
    ) -> tuple[str, ...]:
        """Return lifecycle-profile errors for one initial REQ."""

        if not isinstance(request, ChiWriteNoSnpFullMessage):
            return ("expected WriteNoSnpFull",)
        reasons: list[str] = []
        if request.size != 6:
            reasons.append("WriteNoSnpFull requires Size=6 (64 bytes)")
        if request.address % _CACHE_LINE_BYTES:
            reasons.append(
                "WriteNoSnpFull requires a 64-byte aligned address"
            )
        if request.snoop_attribute:
            reasons.append("WriteNoSnpFull requires SnpAttr=0")
        if request.likely_shared:
            reasons.append("WriteNoSnpFull requires LikelyShared=0")
        if request.expect_completion_ack:
            reasons.append(
                "the first WriteNoSnpFull profile requires ExpCompAck=0"
            )
        if request.order != 0:
            reasons.append(
                "the first WriteNoSnpFull profile requires Order=00"
            )
        if request.exclusive:
            reasons.append(
                "the first WriteNoSnpFull profile requires Excl=0"
            )
        if request.memory_attributes != 0b0101:
            reasons.append(
                "the first WriteNoSnpFull profile requires MemAttr=0101"
            )
        if not request.allow_retry:
            reasons.append("an initial WriteNoSnpFull must set AllowRetry")
        if request.protocol_credit_type != 0:
            reasons.append(
                "an initial WriteNoSnpFull requires PCrdType=0"
            )
        if request.tag_operation != 0:
            reasons.append(
                "the first WriteNoSnpFull profile requires TagOp=0"
            )
        if request.trace_tag:
            reasons.append(
                "the first WriteNoSnpFull profile requires TraceTag=0"
            )
        return tuple(reasons)

    def explain_payload(
        self,
        request: ChiWriteNoSnpFullMessage,
        data: int,
        byte_enable: int = _FULL_BYTE_ENABLE,
    ) -> tuple[str, ...]:
        """Check the full-line DAT payload retained with one REQ."""

        if not isinstance(request, ChiWriteNoSnpFullMessage):
            return ("expected WriteNoSnpFull",)
        reasons = _payload_shape_reasons(
            "WriteNoSnpFull",
            data,
            byte_enable,
        )
        if not reasons and byte_enable != _FULL_BYTE_ENABLE:
            reasons.append(
                "WriteNoSnpFull requires all 64 byte enables"
            )
        return tuple(reasons)


@dataclass(frozen=True)
class ChiWriteNoSnpPtlProfile:
    """Normal-memory, 512-bit single-DAT partial-write profile."""

    requester_node_id: int
    home_node_id: int
    data_width: int = 512
    outstanding_capacity: int = 8

    def __post_init__(self) -> None:
        _validate_profile_shape(
            self.requester_node_id,
            self.home_node_id,
            self.data_width,
            self.outstanding_capacity,
            operation="WriteNoSnpPtl",
        )

    def data_window(
        self,
        request: ChiWriteNoSnpPtlMessage,
    ) -> tuple[int, int]:
        """Return ``(aligned_address, size_bytes)`` for Addr/Size."""

        if not isinstance(request, ChiWriteNoSnpPtlMessage):
            raise TypeError("WriteNoSnpPtl data window requires its REQ")
        transfer_bytes = 1 << request.size
        aligned_address = (
            request.address // transfer_bytes
        ) * transfer_bytes
        return aligned_address, transfer_bytes

    def line_address(
        self,
        request: ChiWriteNoSnpPtlMessage,
    ) -> int:
        """Return the 64-byte line base containing the REQ address."""

        if not isinstance(request, ChiWriteNoSnpPtlMessage):
            raise TypeError("WriteNoSnpPtl line address requires its REQ")
        return (
            request.address // _CACHE_LINE_BYTES
        ) * _CACHE_LINE_BYTES

    def data_window_mask(
        self,
        request: ChiWriteNoSnpPtlMessage,
    ) -> int:
        """Return the 64-bit BE mask selected by rounded-down Addr/Size.

        Data bytes occupy their natural positions in the single 512-bit DAT.
        An unaligned request therefore starts at ``Addr`` rounded down to its
        ``2**Size`` boundary, not at the literal byte address.
        """

        aligned_address, transfer_bytes = self.data_window(request)
        line_base = self.line_address(request)
        lower = aligned_address - line_base
        upper = lower + transfer_bytes
        if lower < 0 or upper > _CACHE_LINE_BYTES:
            raise ValueError(
                "WriteNoSnpPtl Addr/Size data window crosses its 64-byte DAT "
                "line"
            )
        return ((1 << transfer_bytes) - 1) << lower

    def explain_request(
        self,
        request: ChiWriteNoSnpPtlMessage,
    ) -> tuple[str, ...]:
        """Return lifecycle-profile errors for one initial partial REQ."""

        if not isinstance(request, ChiWriteNoSnpPtlMessage):
            return ("expected WriteNoSnpPtl",)
        reasons: list[str] = []
        try:
            self.data_window_mask(request)
        except ValueError as error:
            reasons.append(str(error))
        if request.snoop_attribute:
            reasons.append("WriteNoSnpPtl requires SnpAttr=0")
        if request.likely_shared:
            reasons.append("WriteNoSnpPtl requires LikelyShared=0")
        if request.expect_completion_ack:
            reasons.append(
                "the first WriteNoSnpPtl profile requires ExpCompAck=0"
            )
        if request.order != 0:
            reasons.append(
                "the first WriteNoSnpPtl profile requires Order=00"
            )
        if request.exclusive:
            reasons.append(
                "the first WriteNoSnpPtl profile requires Excl=0"
            )
        if request.memory_attributes != 0b0101:
            reasons.append(
                "the first WriteNoSnpPtl profile requires Normal-memory "
                "MemAttr=0101"
            )
        if not request.allow_retry:
            reasons.append("an initial WriteNoSnpPtl must set AllowRetry")
        if request.protocol_credit_type != 0:
            reasons.append(
                "an initial WriteNoSnpPtl requires PCrdType=0"
            )
        if request.tag_operation != 0:
            reasons.append(
                "the first WriteNoSnpPtl profile requires TagOp=0"
            )
        if request.trace_tag:
            reasons.append(
                "the first WriteNoSnpPtl profile requires TraceTag=0"
            )
        return tuple(reasons)

    def explain_payload(
        self,
        request: ChiWriteNoSnpPtlMessage,
        data: int,
        byte_enable: int,
    ) -> tuple[str, ...]:
        """Check one 512-bit DAT payload against the REQ data window."""

        reasons = _payload_shape_reasons(
            "WriteNoSnpPtl",
            data,
            byte_enable,
        )
        if reasons:
            return tuple(reasons)
        if not isinstance(request, ChiWriteNoSnpPtlMessage):
            return ("expected WriteNoSnpPtl",)
        try:
            window_mask = self.data_window_mask(request)
        except ValueError as error:
            return (str(error),)
        outside = byte_enable & (_FULL_BYTE_ENABLE ^ window_mask)
        if outside:
            reasons.append(
                f"WriteNoSnpPtl byte enables 0x{outside:x} lie outside the "
                "rounded-down Addr/Size data window"
            )
        nonzero_disabled = tuple(
            byte_index
            for byte_index in range(_CACHE_LINE_BYTES)
            if not (byte_enable & (1 << byte_index))
            and ((data >> (byte_index * 8)) & 0xFF)
        )
        if nonzero_disabled:
            reasons.append(
                "WriteNoSnpPtl data bytes with BE=0 must be zero; nonzero "
                f"byte lanes are {nonzero_disabled!r}"
            )
        return tuple(reasons)


ChiWriteNoSnpProfile: TypeAlias = (
    ChiWriteNoSnpFullProfile | ChiWriteNoSnpPtlProfile
)
ChiWriteNoSnpRequest: TypeAlias = (
    ChiWriteNoSnpFullMessage | ChiWriteNoSnpPtlMessage
)


@dataclass(frozen=True)
class ChiWriteNoSnpPending:
    """One retained typed REQ and its line-positioned DAT payload."""

    request: ChiWriteNoSnpRequest
    data: int
    byte_enable: int

    def __post_init__(self) -> None:
        if not isinstance(
            self.request,
            (ChiWriteNoSnpFullMessage, ChiWriteNoSnpPtlMessage),
        ):
            raise TypeError(
                "WriteNoSnp pending requires a Full or Ptl typed REQ"
            )
        reasons = _payload_shape_reasons(
            type(self.request).__name__.removesuffix("Message"),
            self.data,
            self.byte_enable,
        )
        if reasons:
            raise ValueError("; ".join(reasons))


@dataclass(frozen=True)
class ChiWriteNoSnpFullIssue:
    request: ChiWriteNoSnpFullMessage
    data: int

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiWriteNoSnpFullMessage):
            raise TypeError("WriteNoSnpFull issue requires its typed REQ")
        ChiWriteNoSnpPending(
            self.request,
            self.data,
            _FULL_BYTE_ENABLE,
        )


@dataclass(frozen=True)
class ChiWriteNoSnpPtlIssue:
    request: ChiWriteNoSnpPtlMessage
    data: int
    byte_enable: int

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiWriteNoSnpPtlMessage):
            raise TypeError("WriteNoSnpPtl issue requires its typed REQ")
        ChiWriteNoSnpPending(
            self.request,
            self.data,
            self.byte_enable,
        )


@dataclass(frozen=True)
class ChiWriteNoSnpAcceptCompDBIDResp:
    response: ChiCompDBIDRespMessage

    def __post_init__(self) -> None:
        if not isinstance(self.response, ChiCompDBIDRespMessage):
            raise TypeError("WriteNoSnp completion requires CompDBIDResp")


ChiWriteNoSnpRequesterAction: TypeAlias = (
    ChiWriteNoSnpFullIssue
    | ChiWriteNoSnpPtlIssue
    | ChiWriteNoSnpAcceptCompDBIDResp
)


@dataclass(frozen=True)
class ChiWriteNoSnpRequesterState:
    """Shared original-TxnID phase for Full and Ptl Immediate Writes."""

    pending: Mapping[int, ChiWriteNoSnpPending] = field(default_factory=dict)
    issued_count: int = 0
    data_sent_count: int = 0

    def __post_init__(self) -> None:
        pending = dict(self.pending)
        if any(
            not isinstance(item, ChiWriteNoSnpPending)
            or transaction_id != item.request.transaction_id
            for transaction_id, item in pending.items()
        ):
            raise ValueError(
                "WriteNoSnp pending keys must match original TxnIDs"
            )
        for name, value in (
            ("issued_count", self.issued_count),
            ("data_sent_count", self.data_sent_count),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{name} must be non-negative")
        if self.data_sent_count > self.issued_count:
            raise ValueError(
                "WriteNoSnp data count cannot exceed issued count"
            )
        object.__setattr__(self, "pending", MappingProxyType(pending))


class ChiWriteNoSnpRequesterLedger(
    SemanticComponent[
        ChiWriteNoSnpRequesterAction,
        ChiWriteNoSnpRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]
):
    """Own the common original-TxnID to Home-DBID write lifecycle."""

    def __init__(
        self,
        name: str,
        profile: ChiWriteNoSnpProfile,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("WriteNoSnp requester requires a name")
        if not isinstance(
            profile,
            (ChiWriteNoSnpFullProfile, ChiWriteNoSnpPtlProfile),
        ):
            raise TypeError("WriteNoSnp requester requires a typed profile")
        self.name = name
        self.profile = profile
        operation = self.operation_name
        constraints = [
            SemanticConstraint(
                f"{name}.txn_to_dbid",
                "CompDBIDResp echoes one outstanding original TxnID; "
                "the produced NonCopyBackWrData uses the granted DBID",
                ConstraintScope.INTERFACE,
                kind=ConstraintKind.RELATION,
            )
        ]
        if isinstance(profile, ChiWriteNoSnpPtlProfile):
            constraints.append(
                SemanticConstraint(
                    f"{name}.partial_byte_enables",
                    "NonCopyBackWrData byte enables stay inside the rounded-"
                    "down Addr/Size window and disabled bytes carry zero",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RELATION,
                )
            )
        self.semantics = SemanticFragment(
            f"{name}.semantics",
            constraints=tuple(constraints),
            resources=(
                ResourceDecl(
                    f"{name}.outstanding",
                    ConstraintScope.INTERFACE,
                    capacity=profile.outstanding_capacity,
                    description=(
                        f"{operation} operations awaiting CompDBIDResp"
                    ),
                    acquired_by=(operation,),
                    released_by=("NonCopyBackWrData",),
                ),
            ),
            sources=(
                "Arm IHI 0050 Issue H B2.3 Immediate Write and B2.9.3 "
                "Byte Enables",
            ),
        )

    @property
    def operation_name(self) -> str:
        if isinstance(self.profile, ChiWriteNoSnpFullProfile):
            return "WriteNoSnpFull"
        return "WriteNoSnpPtl"

    def initial_state(self) -> ChiWriteNoSnpRequesterState:
        return ChiWriteNoSnpRequesterState()

    def is_quiescent(
        self,
        state: ChiWriteNoSnpRequesterState,
    ) -> bool:
        return (
            isinstance(state, ChiWriteNoSnpRequesterState)
            and not state.pending
        )

    def step(
        self,
        state: ChiWriteNoSnpRequesterState,
        action: ChiWriteNoSnpRequesterAction,
    ) -> SemanticStep[
        ChiWriteNoSnpRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        if not isinstance(state, ChiWriteNoSnpRequesterState):
            raise TypeError("WriteNoSnp requester requires its state type")
        if isinstance(action, ChiWriteNoSnpFullIssue):
            if not isinstance(self.profile, ChiWriteNoSnpFullProfile):
                return self._fault(
                    state,
                    "operation_profile",
                    "WriteNoSnpPtl ledger cannot accept WriteNoSnpFull",
                )
            return self._issue(
                state,
                action.request,
                action.data,
                _FULL_BYTE_ENABLE,
            )
        if isinstance(action, ChiWriteNoSnpPtlIssue):
            if not isinstance(self.profile, ChiWriteNoSnpPtlProfile):
                return self._fault(
                    state,
                    "operation_profile",
                    "WriteNoSnpFull ledger cannot accept WriteNoSnpPtl",
                )
            return self._issue(
                state,
                action.request,
                action.data,
                action.byte_enable,
            )
        if isinstance(action, ChiWriteNoSnpAcceptCompDBIDResp):
            return self._accept_response(state, action.response)
        raise TypeError("unknown WriteNoSnp requester action")

    def _issue(
        self,
        state: ChiWriteNoSnpRequesterState,
        request: ChiWriteNoSnpRequest,
        data: int,
        byte_enable: int,
    ) -> SemanticStep[
        ChiWriteNoSnpRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        pending_item = ChiWriteNoSnpPending(
            request,
            data,
            byte_enable,
        )
        reasons = (
            *self.profile.explain_request(request),  # type: ignore[arg-type]
            *self.profile.explain_payload(  # type: ignore[arg-type]
                request,
                data,
                byte_enable,
            ),
        )
        if reasons:
            return self._fault(
                state,
                "request_profile",
                "; ".join(reasons),
            )
        key = request.transaction_id
        if key in state.pending:
            return self._fault(
                state,
                "duplicate_identity",
                f"original TxnID {key} is already outstanding",
            )
        if len(state.pending) >= self.profile.outstanding_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.outstanding",
                    ConstraintScope.INTERFACE,
                    available=0,
                    capacity=self.profile.outstanding_capacity,
                    reason=(
                        f"{self.operation_name} requester outstanding "
                        "capacity is full"
                    ),
                    location=self.name,
                ),
            )
        pending = dict(state.pending)
        pending[key] = pending_item
        return SemanticStep(
            ChiWriteNoSnpRequesterState(
                pending,
                state.issued_count + 1,
                state.data_sent_count,
            )
        )

    def _accept_response(
        self,
        state: ChiWriteNoSnpRequesterState,
        response: ChiCompDBIDRespMessage,
    ) -> SemanticStep[
        ChiWriteNoSnpRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        pending_item = state.pending.get(response.transaction_id)
        if pending_item is None:
            return self._fault(
                state,
                "unknown_completion",
                "CompDBIDResp does not match an outstanding original TxnID",
            )
        if isinstance(self.profile, ChiWriteNoSnpFullProfile):
            request_matches = isinstance(
                pending_item.request,
                ChiWriteNoSnpFullMessage,
            )
        else:
            request_matches = isinstance(
                pending_item.request,
                ChiWriteNoSnpPtlMessage,
            )
        if not request_matches:
            return self._fault(
                state,
                "operation_state",
                "pending WriteNoSnp operation does not match ledger profile",
            )
        reasons: list[str] = []
        if response.response_error is not ChiRespErr.OK:
            reasons.append(
                f"the first {self.operation_name} profile requires "
                "RespErr=OK"
            )
        if response.response != int(ChiRespCode.I):
            reasons.append(
                f"{self.operation_name} CompDBIDResp requires Resp=I"
            )
        if reasons:
            return self._fault(
                state,
                "completion_profile",
                "; ".join(reasons),
            )
        data_message = ChiNonCopyBackWrDataMessage(
            transaction_id=response.data_buffer_id,
            data=pending_item.data,
            response=ChiRespCode.I,
            data_id=0,
            response_error=ChiRespErr.OK,
            byte_enable=pending_item.byte_enable,
            critical_chunk_id=(pending_item.request.address >> 4) & 0b11,
            trace_tag=response.trace_tag,
        )
        pending = dict(state.pending)
        del pending[response.transaction_id]
        return SemanticStep(
            ChiWriteNoSnpRequesterState(
                pending,
                state.issued_count,
                state.data_sent_count + 1,
            ),
            (data_message,),
        )

    def _fault(
        self,
        state: ChiWriteNoSnpRequesterState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[
        ChiWriteNoSnpRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                ConstraintScope.INTERFACE,
                self.name,
            ),
        )


class ChiWriteNoSnpFullRequesterLedger(ChiWriteNoSnpRequesterLedger):
    """Typed Full entry point over the shared WriteNoSnp lifecycle."""

    def __init__(
        self,
        name: str,
        profile: ChiWriteNoSnpFullProfile,
    ) -> None:
        if not isinstance(profile, ChiWriteNoSnpFullProfile):
            raise TypeError(
                "WriteNoSnpFull requester requires its direct profile"
            )
        super().__init__(name, profile)


class ChiWriteNoSnpPtlRequesterLedger(ChiWriteNoSnpRequesterLedger):
    """Typed Ptl entry point over the shared WriteNoSnp lifecycle."""

    def __init__(
        self,
        name: str,
        profile: ChiWriteNoSnpPtlProfile,
    ) -> None:
        if not isinstance(profile, ChiWriteNoSnpPtlProfile):
            raise TypeError(
                "WriteNoSnpPtl requester requires its direct profile"
            )
        super().__init__(name, profile)


# Public compatibility names keep the first Full slice and the new Ptl slice
# source-compatible while making their shared family-level state explicit.
ChiWriteNoSnpFullPending = ChiWriteNoSnpPending
ChiWriteNoSnpPtlPending = ChiWriteNoSnpPending
ChiWriteNoSnpFullAcceptCompDBIDResp = ChiWriteNoSnpAcceptCompDBIDResp
ChiWriteNoSnpPtlAcceptCompDBIDResp = ChiWriteNoSnpAcceptCompDBIDResp
ChiWriteNoSnpFullRequesterState = ChiWriteNoSnpRequesterState
ChiWriteNoSnpPtlRequesterState = ChiWriteNoSnpRequesterState
ChiWriteNoSnpFullRequesterAction: TypeAlias = (
    ChiWriteNoSnpFullIssue | ChiWriteNoSnpAcceptCompDBIDResp
)
ChiWriteNoSnpPtlRequesterAction: TypeAlias = (
    ChiWriteNoSnpPtlIssue | ChiWriteNoSnpAcceptCompDBIDResp
)


__all__ = [
    "ChiWriteNoSnpAcceptCompDBIDResp",
    "ChiWriteNoSnpFullAcceptCompDBIDResp",
    "ChiWriteNoSnpFullIssue",
    "ChiWriteNoSnpFullPending",
    "ChiWriteNoSnpFullProfile",
    "ChiWriteNoSnpFullRequesterAction",
    "ChiWriteNoSnpFullRequesterLedger",
    "ChiWriteNoSnpFullRequesterState",
    "ChiWriteNoSnpPending",
    "ChiWriteNoSnpProfile",
    "ChiWriteNoSnpPtlAcceptCompDBIDResp",
    "ChiWriteNoSnpPtlIssue",
    "ChiWriteNoSnpPtlPending",
    "ChiWriteNoSnpPtlProfile",
    "ChiWriteNoSnpPtlRequesterAction",
    "ChiWriteNoSnpPtlRequesterLedger",
    "ChiWriteNoSnpPtlRequesterState",
    "ChiWriteNoSnpRequest",
    "ChiWriteNoSnpRequesterAction",
    "ChiWriteNoSnpRequesterLedger",
    "ChiWriteNoSnpRequesterState",
]
