"""Requester-side lifecycle for the first non-snoop Exclusive slice.

The profile closes one ``ReadNoSnp(Excl=1)`` followed by one matching
``WriteNoSnpPtl(Excl=1)``.  It deliberately selects one explicit
``SrcID+LPID`` logical processor.  A later multi-LP runtime can instantiate
multiple such profiles or replace the single-entry requester gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeAlias

from protocol_model.semantics import (
    ConstraintKind,
    ConstraintScope,
    ResourceDecl,
    SemanticComponent,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
)

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
_FULL_BYTE_ENABLE = (1 << _CACHE_LINE_BYTES) - 1
_CACHE_LINE_DATA_LIMIT = 1 << (_CACHE_LINE_BYTES * 8)


def _require_node_id(name: str, value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class ChiNonSnoopExclusivePtlProfile:
    """Single-Home, single-LP, 512-bit non-snoop Exclusive profile."""

    requester_node_id: int
    home_node_id: int
    logical_processor_id: int = 0
    data_width: int = 512
    monitor_granule_bytes: int = _CACHE_LINE_BYTES

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        _require_node_id("home_node_id", self.home_node_id)
        if self.requester_node_id == self.home_node_id:
            raise ValueError("Requester and Home NodeIDs must differ")
        if (
            not isinstance(self.logical_processor_id, int)
            or isinstance(self.logical_processor_id, bool)
            or not 0 <= self.logical_processor_id < (1 << 5)
        ):
            raise ValueError("logical_processor_id must be a 5-bit integer")
        if self.data_width != 512:
            raise ValueError(
                "the first non-snoop Exclusive profile requires a "
                "512-bit DAT channel"
            )
        if self.monitor_granule_bytes != _CACHE_LINE_BYTES:
            raise ValueError(
                "the first non-snoop Exclusive profile uses a 64-byte "
                "System-monitor granule"
            )

    @staticmethod
    def transfer_bytes(
        request: ChiReadNoSnpMessage | ChiWriteNoSnpPtlMessage,
    ) -> int:
        if not isinstance(
            request,
            (ChiReadNoSnpMessage, ChiWriteNoSnpPtlMessage),
        ):
            raise TypeError(
                "Exclusive transfer geometry requires ReadNoSnp or "
                "WriteNoSnpPtl"
            )
        return 1 << request.size

    @classmethod
    def transfer_window(
        cls,
        request: ChiReadNoSnpMessage | ChiWriteNoSnpPtlMessage,
    ) -> tuple[int, int]:
        """Return the exact aligned address and byte count."""

        return request.address, cls.transfer_bytes(request)

    @staticmethod
    def line_address(
        request: ChiReadNoSnpMessage | ChiWriteNoSnpPtlMessage,
    ) -> int:
        return request.address - request.address % _CACHE_LINE_BYTES

    @staticmethod
    def critical_chunk_id(
        request: ChiReadNoSnpMessage | ChiWriteNoSnpPtlMessage,
    ) -> int:
        """Return the DAT CCID selected by the original REQ address."""

        if not isinstance(
            request,
            (ChiReadNoSnpMessage, ChiWriteNoSnpPtlMessage),
        ):
            raise TypeError(
                "Exclusive CCID requires ReadNoSnp or WriteNoSnpPtl"
            )
        return (request.address >> 4) & 0b11

    @classmethod
    def data_window_mask(
        cls,
        request: ChiWriteNoSnpPtlMessage,
    ) -> int:
        if not isinstance(request, ChiWriteNoSnpPtlMessage):
            raise TypeError(
                "Exclusive partial-write mask requires WriteNoSnpPtl"
            )
        transfer_bytes = cls.transfer_bytes(request)
        lower = request.address % _CACHE_LINE_BYTES
        return ((1 << transfer_bytes) - 1) << lower

    def _common_request_reasons(
        self,
        request: ChiReadNoSnpMessage | ChiWriteNoSnpPtlMessage,
    ) -> list[str]:
        reasons: list[str] = []
        if not request.exclusive:
            reasons.append("non-snoop Exclusive requests require Excl=1")
        if request.snoop_attribute:
            reasons.append("non-snoop Exclusive requests require SnpAttr=0")
        if request.likely_shared:
            reasons.append(
                "non-snoop Exclusive requests require LikelyShared=0"
            )
        if request.memory_attributes not in (0b0000, 0b0001):
            reasons.append(
                "the first non-snoop Exclusive profile requires Normal "
                "Non-cacheable MemAttr 0000 or 0001"
            )
        if request.order != 0:
            reasons.append(
                "the first non-snoop Exclusive profile requires Order=00"
            )
        if request.expect_completion_ack:
            reasons.append(
                "the first non-snoop Exclusive profile requires ExpCompAck=0"
            )
        if not request.allow_retry:
            reasons.append(
                "an initial non-snoop Exclusive request must set AllowRetry"
            )
        if request.protocol_credit_type != 0:
            reasons.append(
                "an initial non-snoop Exclusive request requires PCrdType=0"
            )
        if request.tag_operation != 0:
            reasons.append(
                "the first non-snoop Exclusive profile requires TagOp=0"
            )
        if request.trace_tag:
            reasons.append(
                "the first non-snoop Exclusive profile requires TraceTag=0"
            )
        if request.logical_processor_id != self.logical_processor_id:
            reasons.append(
                "non-snoop Exclusive request LPID does not match the "
                "configured logical processor"
            )
        transfer_bytes = 1 << request.size
        if request.address % transfer_bytes:
            reasons.append(
                "an Exclusive address must be aligned to its transfer size"
            )
        return reasons

    def explain_read(
        self,
        request: ChiReadNoSnpMessage,
    ) -> tuple[str, ...]:
        if not isinstance(request, ChiReadNoSnpMessage):
            return ("expected ReadNoSnp",)
        return tuple(self._common_request_reasons(request))

    def explain_write(
        self,
        request: ChiWriteNoSnpPtlMessage,
    ) -> tuple[str, ...]:
        if not isinstance(request, ChiWriteNoSnpPtlMessage):
            return ("expected WriteNoSnpPtl",)
        return tuple(self._common_request_reasons(request))

    def explain_payload(
        self,
        request: ChiWriteNoSnpPtlMessage,
        data: int,
        byte_enable: int,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if not isinstance(request, ChiWriteNoSnpPtlMessage):
            return ("expected WriteNoSnpPtl",)
        if (
            not isinstance(data, int)
            or isinstance(data, bool)
            or not 0 <= data < _CACHE_LINE_DATA_LIMIT
        ):
            reasons.append("Exclusive write data must fit one 512-bit line")
        if (
            not isinstance(byte_enable, int)
            or isinstance(byte_enable, bool)
            or not 0 <= byte_enable <= _FULL_BYTE_ENABLE
        ):
            reasons.append("Exclusive write byte_enable must be 64-bit")
        if reasons:
            return tuple(reasons)
        window_mask = self.data_window_mask(request)
        outside = byte_enable & (_FULL_BYTE_ENABLE ^ window_mask)
        if outside:
            reasons.append(
                f"Exclusive write byte enables 0x{outside:x} lie outside "
                "the Addr/Size transfer window"
            )
        nonzero_disabled = tuple(
            lane
            for lane in range(_CACHE_LINE_BYTES)
            if not (byte_enable & (1 << lane))
            and ((data >> (lane * 8)) & 0xFF)
        )
        if nonzero_disabled:
            reasons.append(
                "Exclusive write data bytes with BE=0 must be zero; "
                f"nonzero byte lanes are {nonzero_disabled!r}"
            )
        return tuple(reasons)

    @staticmethod
    def explain_pair(
        read: ChiReadNoSnpMessage,
        write: ChiWriteNoSnpPtlMessage,
    ) -> tuple[str, ...]:
        if not isinstance(read, ChiReadNoSnpMessage):
            return ("expected the completed Exclusive ReadNoSnp",)
        if not isinstance(write, ChiWriteNoSnpPtlMessage):
            return ("expected the Exclusive WriteNoSnpPtl",)
        mismatches = tuple(
            name
            for name, read_value, write_value in (
                ("Addr", read.address, write.address),
                ("Size", read.size, write.size),
                ("MemAttr", read.memory_attributes, write.memory_attributes),
                ("SnpAttr", read.snoop_attribute, write.snoop_attribute),
                (
                    "LPID",
                    read.logical_processor_id,
                    write.logical_processor_id,
                ),
                ("PAS", read.pas, write.pas),
            )
            if read_value != write_value
        )
        if not mismatches:
            return ()
        return (
            "Exclusive read/write pair differs in "
            + ", ".join(mismatches),
        )


@dataclass(frozen=True)
class ChiIssueExclusiveReadNoSnp:
    request: ChiReadNoSnpMessage

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiReadNoSnpMessage):
            raise TypeError(
                "Exclusive read issue requires ChiReadNoSnpMessage"
            )


@dataclass(frozen=True)
class ChiAcceptExclusiveCompData:
    response: ChiCompDataMessage

    def __post_init__(self) -> None:
        if not isinstance(self.response, ChiCompDataMessage):
            raise TypeError(
                "Exclusive read completion requires ChiCompDataMessage"
            )


@dataclass(frozen=True)
class ChiIssueExclusiveWriteNoSnpPtl:
    request: ChiWriteNoSnpPtlMessage
    data: int
    byte_enable: int

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiWriteNoSnpPtlMessage):
            raise TypeError(
                "Exclusive write issue requires ChiWriteNoSnpPtlMessage"
            )
        if (
            not isinstance(self.data, int)
            or isinstance(self.data, bool)
            or self.data < 0
        ):
            raise ValueError("Exclusive write data must be non-negative")
        if (
            not isinstance(self.byte_enable, int)
            or isinstance(self.byte_enable, bool)
            or self.byte_enable < 0
        ):
            raise ValueError(
                "Exclusive write byte_enable must be non-negative"
            )


@dataclass(frozen=True)
class ChiAcceptExclusiveCompDBIDResp:
    response: ChiCompDBIDRespMessage

    def __post_init__(self) -> None:
        if not isinstance(self.response, ChiCompDBIDRespMessage):
            raise TypeError(
                "Exclusive write response requires ChiCompDBIDRespMessage"
            )


ChiNonSnoopExclusiveRequesterAction: TypeAlias = (
    ChiIssueExclusiveReadNoSnp
    | ChiAcceptExclusiveCompData
    | ChiIssueExclusiveWriteNoSnpPtl
    | ChiAcceptExclusiveCompDBIDResp
)


@dataclass(frozen=True)
class ChiNonSnoopExclusiveReadResult:
    request: ChiReadNoSnpMessage
    response: ChiCompDataMessage

    @property
    def monitor_allocated(self) -> bool:
        return self.response.response_error is ChiRespErr.EXOK

    @property
    def data(self) -> int:
        """Return read data for either EXOK or monitor-allocation failure."""

        return self.response.data


@dataclass(frozen=True)
class ChiNonSnoopExclusiveWriteResult:
    request: ChiWriteNoSnpPtlMessage
    response: ChiCompDBIDRespMessage

    @property
    def passed(self) -> bool:
        return self.response.response_error is ChiRespErr.EXOK


@dataclass(frozen=True)
class ChiNonSnoopExclusivePendingWrite:
    request: ChiWriteNoSnpPtlMessage
    data: int
    byte_enable: int

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiWriteNoSnpPtlMessage):
            raise TypeError(
                "pending Exclusive write requires WriteNoSnpPtl"
            )


@dataclass(frozen=True)
class ChiNonSnoopExclusiveRequesterState:
    pending_reads: Mapping[int, ChiReadNoSnpMessage] = field(
        default_factory=dict
    )
    pending_writes: Mapping[
        int, ChiNonSnoopExclusivePendingWrite
    ] = field(default_factory=dict)
    eligible_read: ChiReadNoSnpMessage | None = None
    completed_reads: tuple[ChiNonSnoopExclusiveReadResult, ...] = ()
    completed_writes: tuple[ChiNonSnoopExclusiveWriteResult, ...] = ()

    def __post_init__(self) -> None:
        pending_reads = dict(self.pending_reads)
        pending_writes = dict(self.pending_writes)
        if any(
            not isinstance(request, ChiReadNoSnpMessage)
            or transaction_id != request.transaction_id
            for transaction_id, request in pending_reads.items()
        ):
            raise ValueError(
                "pending Exclusive-read keys must match original TxnIDs"
            )
        if any(
            not isinstance(item, ChiNonSnoopExclusivePendingWrite)
            or transaction_id != item.request.transaction_id
            for transaction_id, item in pending_writes.items()
        ):
            raise ValueError(
                "pending Exclusive-write keys must match original TxnIDs"
            )
        if len(pending_reads) + len(pending_writes) > 1:
            raise ValueError(
                "the single-LP Exclusive profile permits one outstanding "
                "Exclusive transaction"
            )
        if self.eligible_read is not None and not isinstance(
            self.eligible_read, ChiReadNoSnpMessage
        ):
            raise TypeError(
                "eligible Exclusive read requires ChiReadNoSnpMessage"
            )
        object.__setattr__(
            self, "pending_reads", MappingProxyType(pending_reads)
        )
        object.__setattr__(
            self, "pending_writes", MappingProxyType(pending_writes)
        )


class ChiNonSnoopExclusiveRequester(
    SemanticComponent[
        ChiNonSnoopExclusiveRequesterAction,
        ChiNonSnoopExclusiveRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]
):
    """Track the Requester-local half of one non-snoop Exclusive sequence."""

    def __init__(
        self,
        name: str,
        profile: ChiNonSnoopExclusivePtlProfile,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("non-snoop Exclusive requester requires a name")
        if not isinstance(profile, ChiNonSnoopExclusivePtlProfile):
            raise TypeError(
                "non-snoop Exclusive requester requires its profile"
            )
        self.name = name
        self.profile = profile
        self.semantics = SemanticFragment(
            f"{name}.semantics",
            constraints=(
                SemanticConstraint(
                    f"{name}.pair",
                    "Exclusive WriteNoSnpPtl matches a completed EXOK "
                    "ReadNoSnp in Addr, Size, MemAttr, SnpAttr, PAS, "
                    "Requester NodeID, and the configured LPID",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RELATION,
                ),
                SemanticConstraint(
                    f"{name}.write_data_on_fail",
                    "both EXOK and OK Exclusive-write responses release one "
                    "NonCopyBackWrData carrying the granted Home DBID",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RELATION,
                ),
            ),
            resources=(
                ResourceDecl(
                    f"{name}.exclusive_outstanding",
                    ConstraintScope.INTERFACE,
                    capacity=1,
                    description=(
                        "the one Exclusive transaction permitted for the "
                        "configured logical processor"
                    ),
                    acquired_by=(
                        "ReadNoSnp(Excl)",
                        "WriteNoSnpPtl(Excl)",
                    ),
                    released_by=("CompData", "NonCopyBackWrData"),
                ),
            ),
            sources=(
                "Arm IHI 0050 Issue H B2.4.7, B6.2, and B6.3",
            ),
        )

    def initial_state(self) -> ChiNonSnoopExclusiveRequesterState:
        return ChiNonSnoopExclusiveRequesterState()

    def is_quiescent(
        self,
        state: ChiNonSnoopExclusiveRequesterState,
    ) -> bool:
        return (
            isinstance(state, ChiNonSnoopExclusiveRequesterState)
            and not state.pending_reads
            and not state.pending_writes
        )

    def step(
        self,
        state: ChiNonSnoopExclusiveRequesterState,
        action: ChiNonSnoopExclusiveRequesterAction,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        if not isinstance(state, ChiNonSnoopExclusiveRequesterState):
            raise TypeError(
                "non-snoop Exclusive requester requires its state type"
            )
        if isinstance(action, ChiIssueExclusiveReadNoSnp):
            return self._issue_read(state, action.request)
        if isinstance(action, ChiAcceptExclusiveCompData):
            return self._accept_read(state, action.response)
        if isinstance(action, ChiIssueExclusiveWriteNoSnpPtl):
            return self._issue_write(
                state,
                action.request,
                action.data,
                action.byte_enable,
            )
        if isinstance(action, ChiAcceptExclusiveCompDBIDResp):
            return self._accept_write_response(state, action.response)
        raise TypeError("unknown non-snoop Exclusive requester action")

    def _has_outstanding(
        self,
        state: ChiNonSnoopExclusiveRequesterState,
    ) -> bool:
        return bool(state.pending_reads or state.pending_writes)

    def _issue_read(
        self,
        state: ChiNonSnoopExclusiveRequesterState,
        request: ChiReadNoSnpMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        reasons = self.profile.explain_read(request)
        if reasons:
            return self._fault(
                state, "read_profile", "; ".join(reasons)
            )
        if self._has_outstanding(state):
            return self._fault(
                state,
                "exclusive_outstanding",
                "the fixed logical processor already has an outstanding "
                "Exclusive transaction",
            )
        return SemanticStep(
            ChiNonSnoopExclusiveRequesterState(
                {request.transaction_id: request},
                {},
                None,
                state.completed_reads,
                state.completed_writes,
            )
        )

    def _accept_read(
        self,
        state: ChiNonSnoopExclusiveRequesterState,
        response: ChiCompDataMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        request = state.pending_reads.get(response.transaction_id)
        if request is None:
            return self._fault(
                state,
                "unknown_read_completion",
                "CompData does not match an outstanding Exclusive read",
            )
        reasons: list[str] = []
        if response.home_node_id != self.profile.home_node_id:
            reasons.append("CompData HomeNID is not the configured Home")
        if response.response_error not in (
            ChiRespErr.EXOK,
            ChiRespErr.OK,
        ):
            reasons.append(
                "Exclusive ReadNoSnp completion requires EXOK or OK"
            )
        if response.response != int(ChiRespCode.I):
            reasons.append("Exclusive ReadNoSnp CompData requires Resp=I")
        if response.data_id != 0:
            reasons.append(
                "512-bit Exclusive ReadNoSnp requires DataID=0"
            )
        if (
            response.critical_chunk_id
            != self.profile.critical_chunk_id(request)
        ):
            reasons.append(
                "Exclusive ReadNoSnp CompData CCID must equal original "
                "Addr[5:4]"
            )
        if response.data >= _CACHE_LINE_DATA_LIMIT:
            reasons.append(
                "Exclusive ReadNoSnp data exceeds the 512-bit profile"
            )
        if reasons:
            return self._fault(
                state, "read_completion", "; ".join(reasons)
            )
        result = ChiNonSnoopExclusiveReadResult(request, response)
        return SemanticStep(
            ChiNonSnoopExclusiveRequesterState(
                {},
                state.pending_writes,
                request if result.monitor_allocated else None,
                state.completed_reads + (result,),
                state.completed_writes,
            )
        )

    def _issue_write(
        self,
        state: ChiNonSnoopExclusiveRequesterState,
        request: ChiWriteNoSnpPtlMessage,
        data: int,
        byte_enable: int,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        reasons = (
            *self.profile.explain_write(request),
            *self.profile.explain_payload(request, data, byte_enable),
        )
        if reasons:
            return self._fault(
                state, "write_profile", "; ".join(reasons)
            )
        if self._has_outstanding(state):
            return self._fault(
                state,
                "exclusive_outstanding",
                "the fixed logical processor already has an outstanding "
                "Exclusive transaction",
            )
        if state.eligible_read is None:
            return self._fault(
                state,
                "local_monitor",
                "Exclusive write requires a completed EXOK Exclusive read",
            )
        pair_reasons = self.profile.explain_pair(
            state.eligible_read, request
        )
        if pair_reasons:
            return self._fault(
                state, "exclusive_pair", "; ".join(pair_reasons)
            )
        pending = ChiNonSnoopExclusivePendingWrite(
            request, data, byte_enable
        )
        return SemanticStep(
            ChiNonSnoopExclusiveRequesterState(
                state.pending_reads,
                {request.transaction_id: pending},
                None,
                state.completed_reads,
                state.completed_writes,
            )
        )

    def _accept_write_response(
        self,
        state: ChiNonSnoopExclusiveRequesterState,
        response: ChiCompDBIDRespMessage,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        pending = state.pending_writes.get(response.transaction_id)
        if pending is None:
            return self._fault(
                state,
                "unknown_write_response",
                "CompDBIDResp does not match an outstanding Exclusive write",
            )
        reasons: list[str] = []
        if response.response_error not in (
            ChiRespErr.EXOK,
            ChiRespErr.OK,
        ):
            reasons.append(
                "Exclusive WriteNoSnpPtl response requires EXOK or OK"
            )
        if response.response != int(ChiRespCode.I):
            reasons.append(
                "Exclusive WriteNoSnpPtl CompDBIDResp requires Resp=I"
            )
        if reasons:
            return self._fault(
                state, "write_response", "; ".join(reasons)
            )
        data = ChiNonCopyBackWrDataMessage(
            transaction_id=response.data_buffer_id,
            data=pending.data,
            response=ChiRespCode.I,
            data_id=0,
            response_error=ChiRespErr.OK,
            byte_enable=pending.byte_enable,
            critical_chunk_id=self.profile.critical_chunk_id(
                pending.request
            ),
            trace_tag=response.trace_tag,
        )
        result = ChiNonSnoopExclusiveWriteResult(
            pending.request, response
        )
        return SemanticStep(
            ChiNonSnoopExclusiveRequesterState(
                state.pending_reads,
                {},
                state.eligible_read,
                state.completed_reads,
                state.completed_writes + (result,),
            ),
            (data,),
        )

    def _fault(
        self,
        state: ChiNonSnoopExclusiveRequesterState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[
        ChiNonSnoopExclusiveRequesterState,
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


__all__ = [
    "ChiAcceptExclusiveCompDBIDResp",
    "ChiAcceptExclusiveCompData",
    "ChiIssueExclusiveReadNoSnp",
    "ChiIssueExclusiveWriteNoSnpPtl",
    "ChiNonSnoopExclusivePendingWrite",
    "ChiNonSnoopExclusivePtlProfile",
    "ChiNonSnoopExclusiveReadResult",
    "ChiNonSnoopExclusiveRequester",
    "ChiNonSnoopExclusiveRequesterAction",
    "ChiNonSnoopExclusiveRequesterState",
    "ChiNonSnoopExclusiveWriteResult",
]
