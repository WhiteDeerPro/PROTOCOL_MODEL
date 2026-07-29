"""Requester lifecycle shared by the executable returning CHI Atomics."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
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
    ChiAtomicLoadAddMessage,
    ChiAtomicSwapMessage,
    ChiCompDataMessage,
    ChiDBIDRespMessage,
    ChiNonCopyBackWrDataMessage,
    ChiRespCode,
    ChiRespErr,
)


_CACHE_LINE_BYTES = 64
_ATOMIC_MAX_SIZE = 3
_DATA_WIDTH = 512
_MAX_REQUESTER_OUTSTANDING = 1 << 10


def _require_node_id(name: str, value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{name} must be a non-negative integer")


class ChiAtomicOperation(str, Enum):
    """Returning Atomic operations implemented by this lifecycle."""

    SWAP = "swap"
    LOAD_ADD = "load_add"


ChiAtomicRequest: TypeAlias = (
    ChiAtomicSwapMessage | ChiAtomicLoadAddMessage
)

_OPERATION_BY_REQUEST_TYPE = MappingProxyType(
    {
        ChiAtomicSwapMessage: ChiAtomicOperation.SWAP,
        ChiAtomicLoadAddMessage: ChiAtomicOperation.LOAD_ADD,
    }
)
_ALL_ATOMIC_OPERATIONS = frozenset(ChiAtomicOperation)


def _operation_for_request(
    request: ChiAtomicRequest,
) -> ChiAtomicOperation:
    try:
        return _OPERATION_BY_REQUEST_TYPE[type(request)]
    except (KeyError, TypeError) as error:
        raise TypeError(
            "returning Atomic lifecycle requires AtomicSwap or "
            "AtomicLoad ADD"
        ) from error


@dataclass(frozen=True)
class ChiAtomicGeometry:
    """Natural-lane geometry of one 1/2/4/8-byte returning Atomic."""

    line_address: int
    lane_offset: int
    transfer_bytes: int
    byte_enable: int
    value_mask: int
    critical_chunk_id: int

    @classmethod
    def from_request(
        cls,
        request: ChiAtomicRequest,
    ) -> "ChiAtomicGeometry":
        _operation_for_request(request)
        if request.size not in range(_ATOMIC_MAX_SIZE + 1):
            raise ValueError(
                "returning Atomic Size must select 1, 2, 4, or 8 bytes"
            )
        transfer_bytes = 1 << request.size
        if request.address % transfer_bytes:
            raise ValueError(
                "returning Atomic address must be naturally aligned to "
                "its transfer size"
            )
        lane_offset = request.address % _CACHE_LINE_BYTES
        if lane_offset + transfer_bytes > _CACHE_LINE_BYTES:
            raise ValueError(
                "returning Atomic transfer cannot cross a cache line"
            )
        return cls(
            request.address - lane_offset,
            lane_offset,
            transfer_bytes,
            ((1 << transfer_bytes) - 1) << lane_offset,
            (1 << (transfer_bytes * 8)) - 1,
            (request.address >> 4) & 0b11,
        )

    @property
    def shift_bits(self) -> int:
        return self.lane_offset * 8

    @property
    def positioned_mask(self) -> int:
        return self.value_mask << self.shift_bits

    def position(self, value: int) -> int:
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= self.value_mask
        ):
            raise ValueError(
                "Atomic operand must fit the selected transfer size"
            )
        return value << self.shift_bits

    def extract(self, data: int) -> int:
        if (
            not isinstance(data, int)
            or isinstance(data, bool)
            or not 0 <= data < (1 << _DATA_WIDTH)
        ):
            raise ValueError(
                "Atomic data must fit the 512-bit DAT profile"
            )
        return (data >> self.shift_bits) & self.value_mask


@dataclass(frozen=True)
class ChiAtomicProfile:
    """Bounded LE, Normal-NC profile for returning non-snoop Atomics."""

    requester_node_id: int
    home_node_id: int
    data_width: int = 512
    outstanding_capacity: int = 4
    enabled_operations: frozenset[ChiAtomicOperation] = (
        _ALL_ATOMIC_OPERATIONS
    )

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        _require_node_id("home_node_id", self.home_node_id)
        if self.requester_node_id == self.home_node_id:
            raise ValueError("Requester and Home NodeIDs must differ")
        if self.data_width != 512:
            raise ValueError(
                "the returning Atomic profile requires a 512-bit DAT channel"
            )
        if (
            not isinstance(self.outstanding_capacity, int)
            or isinstance(self.outstanding_capacity, bool)
            or not 0
            < self.outstanding_capacity
            <= _MAX_REQUESTER_OUTSTANDING
        ):
            raise ValueError(
                "Atomic outstanding_capacity must be in 1..1024"
            )
        enabled = frozenset(self.enabled_operations)
        if (
            not enabled
            or any(
                not isinstance(operation, ChiAtomicOperation)
                for operation in enabled
            )
        ):
            raise ValueError(
                "enabled_operations must be a non-empty set of "
                "ChiAtomicOperation values"
            )
        object.__setattr__(self, "enabled_operations", enabled)

    @staticmethod
    def geometry(request: ChiAtomicRequest) -> ChiAtomicGeometry:
        return ChiAtomicGeometry.from_request(request)

    @staticmethod
    def line_address(request: ChiAtomicRequest) -> int:
        return ChiAtomicGeometry.from_request(request).line_address

    @staticmethod
    def byte_enable(request: ChiAtomicRequest) -> int:
        return ChiAtomicGeometry.from_request(request).byte_enable

    @staticmethod
    def critical_chunk_id(request: ChiAtomicRequest) -> int:
        return ChiAtomicGeometry.from_request(request).critical_chunk_id

    @staticmethod
    def position_value(request: ChiAtomicRequest, value: int) -> int:
        return ChiAtomicGeometry.from_request(request).position(value)

    @staticmethod
    def extract_value(request: ChiAtomicRequest, data: int) -> int:
        return ChiAtomicGeometry.from_request(request).extract(data)

    def explain_request(
        self,
        request: ChiAtomicRequest,
    ) -> tuple[str, ...]:
        try:
            operation = _operation_for_request(request)
        except TypeError:
            return ("expected AtomicSwap or AtomicLoad ADD",)
        reasons: list[str] = []
        if operation not in self.enabled_operations:
            reasons.append(
                f"Atomic {operation.value} is not enabled by this profile"
            )
        if request.size not in range(_ATOMIC_MAX_SIZE + 1):
            reasons.append(
                "Atomic profile requires Size=0..3 (1, 2, 4, or 8 bytes)"
            )
        elif request.address % (1 << request.size):
            reasons.append(
                "Atomic address must be naturally aligned to its "
                "transfer size"
            )
        if request.pas != 0:
            reasons.append(
                "Atomic profile requires the configured PAS=0 domain"
            )
        if request.memory_attributes != 0b0001:
            reasons.append(
                "Atomic profile requires Normal Non-cacheable "
                "MemAttr=0001"
            )
        if request.snoop_attribute:
            reasons.append("Atomic profile requires SnpAttr=0")
        if request.snoop_me:
            reasons.append("Atomic profile requires SnoopMe=0")
        if request.order != 0:
            reasons.append("Atomic profile requires Order=00")
        if not request.allow_retry:
            reasons.append("initial Atomic requires AllowRetry=1")
        if request.protocol_credit_type != 0:
            reasons.append("initial Atomic requires PCrdType=0")
        if request.endian:
            reasons.append("Atomic profile requires little-endian")
        if request.expect_completion_ack:
            reasons.append("returning Atomic does not use CompAck")
        if request.tag_operation != 0:
            reasons.append("Atomic profile requires TagOp=Invalid(0)")
        if request.trace_tag:
            reasons.append("Atomic profile requires TraceTag=0")
        return tuple(reasons)

    @staticmethod
    def explain_operand(
        request: ChiAtomicRequest,
        value: int,
    ) -> tuple[str, ...]:
        try:
            ChiAtomicGeometry.from_request(request).position(value)
        except (TypeError, ValueError) as error:
            return (str(error),)
        return ()


class ChiAtomicSwapProfile(ChiAtomicProfile):
    """Compatibility profile enabling only AtomicSwap."""

    def __init__(
        self,
        requester_node_id: int,
        home_node_id: int,
        data_width: int = 512,
        outstanding_capacity: int = 4,
    ) -> None:
        super().__init__(
            requester_node_id,
            home_node_id,
            data_width,
            outstanding_capacity,
            frozenset((ChiAtomicOperation.SWAP,)),
        )


class ChiAtomicLoadAddProfile(ChiAtomicProfile):
    """Thin profile enabling only AtomicLoad ADD."""

    def __init__(
        self,
        requester_node_id: int,
        home_node_id: int,
        data_width: int = 512,
        outstanding_capacity: int = 4,
    ) -> None:
        super().__init__(
            requester_node_id,
            home_node_id,
            data_width,
            outstanding_capacity,
            frozenset((ChiAtomicOperation.LOAD_ADD,)),
        )


@dataclass(frozen=True)
class ChiAtomicPending:
    """Retained request/operand, optionally bound to a Home DBID."""

    request: ChiAtomicRequest
    operand_value: int
    data_buffer_id: int | None = None

    def __post_init__(self) -> None:
        ChiAtomicGeometry.from_request(self.request).position(
            self.operand_value
        )
        if self.data_buffer_id is not None and (
            not isinstance(self.data_buffer_id, int)
            or isinstance(self.data_buffer_id, bool)
            or not 0 <= self.data_buffer_id < (1 << 12)
        ):
            raise ValueError("Atomic data_buffer_id must be 12-bit or None")

    @property
    def operation(self) -> ChiAtomicOperation:
        return _operation_for_request(self.request)

    @property
    def swap_value(self) -> int:
        """Compatibility projection for the original AtomicSwap API."""

        return self.operand_value

    @property
    def awaiting_grant(self) -> bool:
        return self.data_buffer_id is None

    @property
    def awaiting_completion(self) -> bool:
        return self.data_buffer_id is not None


@dataclass(frozen=True)
class ChiAtomicResult:
    request: ChiAtomicRequest
    operand_value: int
    original_value: int
    completion: ChiCompDataMessage

    def __post_init__(self) -> None:
        geometry = ChiAtomicGeometry.from_request(self.request)
        for name, value in (
            ("operand_value", self.operand_value),
            ("original_value", self.original_value),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= geometry.value_mask
            ):
                raise ValueError(
                    f"{name} must fit the selected Atomic transfer size"
                )
        if not isinstance(self.completion, ChiCompDataMessage):
            raise TypeError("Atomic result requires CompData")

    @property
    def operation(self) -> ChiAtomicOperation:
        return _operation_for_request(self.request)

    @property
    def swap_value(self) -> int:
        """Compatibility projection for the original AtomicSwap API."""

        return self.operand_value


@dataclass(frozen=True)
class ChiIssueAtomic:
    request: ChiAtomicRequest
    operand_value: int
    requester_line_is_invalid: bool

    def __post_init__(self) -> None:
        ChiAtomicPending(self.request, self.operand_value)
        if type(self.requester_line_is_invalid) is not bool:
            raise TypeError(
                "Atomic requester-line evidence must be bool"
            )

    @property
    def swap_value(self) -> int:
        """Compatibility projection for the original AtomicSwap API."""

        return self.operand_value


@dataclass(frozen=True)
class ChiAcceptAtomicDBIDResp:
    response: ChiDBIDRespMessage

    def __post_init__(self) -> None:
        if not isinstance(self.response, ChiDBIDRespMessage):
            raise TypeError("Atomic grant action requires DBIDResp")


@dataclass(frozen=True)
class ChiAcceptAtomicCompData:
    response: ChiCompDataMessage

    def __post_init__(self) -> None:
        if not isinstance(self.response, ChiCompDataMessage):
            raise TypeError("Atomic completion action requires CompData")


ChiAtomicRequesterAction: TypeAlias = (
    ChiIssueAtomic
    | ChiAcceptAtomicDBIDResp
    | ChiAcceptAtomicCompData
)


@dataclass(frozen=True)
class ChiAtomicRequesterState:
    pending: Mapping[int, ChiAtomicPending] = field(default_factory=dict)
    completed: tuple[ChiAtomicResult, ...] = ()
    issued_count: int = 0
    data_sent_count: int = 0

    def __post_init__(self) -> None:
        pending = dict(self.pending)
        if any(
            not isinstance(item, ChiAtomicPending)
            or transaction_id != item.request.transaction_id
            for transaction_id, item in pending.items()
        ):
            raise ValueError(
                "Atomic pending keys must match original TxnIDs"
            )
        completed = tuple(self.completed)
        if any(not isinstance(item, ChiAtomicResult) for item in completed):
            raise TypeError("Atomic completed entries require result values")
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
                "Atomic data count cannot exceed issued count"
            )
        object.__setattr__(self, "pending", MappingProxyType(pending))
        object.__setattr__(self, "completed", completed)


class ChiAtomicRequester(
    SemanticComponent[
        ChiAtomicRequesterAction,
        ChiAtomicRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]
):
    """Correlate original TxnID, Home DBID, operand DAT, and old value."""

    def __init__(self, name: str, profile: ChiAtomicProfile) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("Atomic requester requires a name")
        if not isinstance(profile, ChiAtomicProfile):
            raise TypeError("Atomic requester requires ChiAtomicProfile")
        self.name = name
        self.profile = profile
        self.semantics = SemanticFragment(
            f"{name}.semantics",
            constraints=(
                SemanticConstraint(
                    f"{name}.txn_dbid",
                    "DBIDResp echoes the original TxnID; operand DAT uses "
                    "the Home DBID and CompData returns on the original TxnID",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RELATION,
                ),
                SemanticConstraint(
                    f"{name}.operand_before_completion_wait",
                    "the Requester emits operand DAT immediately after a "
                    "valid DBIDResp and does not wait for CompData",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RELATION,
                ),
                SemanticConstraint(
                    f"{name}.snoop_me_precondition",
                    "this SnoopMe=0 slice admits an operation only with "
                    "caller-supplied evidence that the Requester line is "
                    "already Invalid",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RELATION,
                ),
            ),
            resources=(
                ResourceDecl(
                    f"{name}.outstanding",
                    ConstraintScope.INTERFACE,
                    capacity=profile.outstanding_capacity,
                    description="returning Atomic operations awaiting completion",
                    acquired_by=tuple(
                        operation.value
                        for operation in sorted(
                            profile.enabled_operations,
                            key=lambda item: item.value,
                        )
                    ),
                    released_by=("CompData_I",),
                ),
            ),
            sources=(
                "Arm IHI 0050 Issue H B2.3.3, B2.9.3, and B4.7.4",
            ),
        )

    def initial_state(self) -> ChiAtomicRequesterState:
        return ChiAtomicRequesterState()

    def is_quiescent(self, state: ChiAtomicRequesterState) -> bool:
        return (
            isinstance(state, ChiAtomicRequesterState)
            and not state.pending
        )

    def step(
        self,
        state: ChiAtomicRequesterState,
        action: ChiAtomicRequesterAction,
    ) -> SemanticStep[
        ChiAtomicRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        if not isinstance(state, ChiAtomicRequesterState):
            raise TypeError("Atomic requester requires its state type")
        if isinstance(action, ChiIssueAtomic):
            return self._issue(
                state,
                action.request,
                action.operand_value,
                action.requester_line_is_invalid,
            )
        if isinstance(action, ChiAcceptAtomicDBIDResp):
            return self._accept_grant(state, action.response)
        if isinstance(action, ChiAcceptAtomicCompData):
            return self._accept_completion(state, action.response)
        raise TypeError("unknown Atomic requester action")

    def _issue(
        self,
        state: ChiAtomicRequesterState,
        request: ChiAtomicRequest,
        operand_value: int,
        requester_line_is_invalid: bool,
    ) -> SemanticStep[
        ChiAtomicRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        reasons = (
            *self.profile.explain_request(request),
            *self.profile.explain_operand(request, operand_value),
        )
        if reasons:
            return self._fault(state, "request_profile", "; ".join(reasons))
        if not requester_line_is_invalid:
            return self._fault(
                state,
                "snoop_me_precondition",
                "SnoopMe=0 requires operation-specific evidence that the "
                "Requester line is already Invalid",
            )
        if request.transaction_id in state.pending:
            return self._fault(
                state,
                "duplicate_identity",
                "Atomic original TxnID is already outstanding",
            )
        if len(state.pending) >= self.profile.outstanding_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.outstanding",
                    ConstraintScope.INTERFACE,
                    available=0,
                    capacity=self.profile.outstanding_capacity,
                    reason="Atomic requester capacity is full",
                    location=self.name,
                ),
            )
        pending = dict(state.pending)
        pending[request.transaction_id] = ChiAtomicPending(
            request,
            operand_value,
        )
        return SemanticStep(
            ChiAtomicRequesterState(
                pending,
                state.completed,
                state.issued_count + 1,
                state.data_sent_count,
            )
        )

    def _accept_grant(
        self,
        state: ChiAtomicRequesterState,
        response: ChiDBIDRespMessage,
    ) -> SemanticStep[
        ChiAtomicRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        pending_item = state.pending.get(response.transaction_id)
        if pending_item is None:
            return self._fault(
                state,
                "unknown_grant",
                "DBIDResp does not match an outstanding Atomic",
            )
        if not pending_item.awaiting_grant:
            return self._fault(
                state,
                "replayed_grant",
                "Atomic has already consumed its DBIDResp",
            )
        profile_reasons = self.profile.explain_request(
            pending_item.request
        )
        if profile_reasons:
            return self._fault(
                state,
                "retained_request_profile",
                "; ".join(profile_reasons),
            )
        if response.response_error is not ChiRespErr.OK or response.response != 0:
            return self._fault(
                state,
                "grant_profile",
                "the returning Atomic DBIDResp requires RespErr=OK and Resp=0",
            )
        request = pending_item.request
        positioned = self.profile.position_value(
            request,
            pending_item.operand_value,
        )
        data = ChiNonCopyBackWrDataMessage(
            transaction_id=response.data_buffer_id,
            data=positioned,
            response=ChiRespCode.I,
            data_id=0,
            response_error=ChiRespErr.OK,
            byte_enable=self.profile.byte_enable(request),
            critical_chunk_id=self.profile.critical_chunk_id(request),
            trace_tag=response.trace_tag,
        )
        pending = dict(state.pending)
        pending[request.transaction_id] = ChiAtomicPending(
            request,
            pending_item.operand_value,
            response.data_buffer_id,
        )
        return SemanticStep(
            ChiAtomicRequesterState(
                pending,
                state.completed,
                state.issued_count,
                state.data_sent_count + 1,
            ),
            (data,),
        )

    def _accept_completion(
        self,
        state: ChiAtomicRequesterState,
        response: ChiCompDataMessage,
    ) -> SemanticStep[
        ChiAtomicRequesterState,
        ChiNonCopyBackWrDataMessage,
    ]:
        pending_item = state.pending.get(response.transaction_id)
        if pending_item is None:
            return self._fault(
                state,
                "unknown_completion",
                "CompData does not match an outstanding Atomic",
            )
        if not pending_item.awaiting_completion:
            return self._fault(
                state,
                "completion_before_grant",
                "Atomic CompData arrived before DBIDResp was consumed",
            )
        profile_reasons = self.profile.explain_request(
            pending_item.request
        )
        if profile_reasons:
            return self._fault(
                state,
                "retained_request_profile",
                "; ".join(profile_reasons),
            )
        reasons: list[str] = []
        if response.home_node_id != self.profile.home_node_id:
            reasons.append("CompData HomeNID is not the configured Home")
        if response.response_error is not ChiRespErr.OK:
            reasons.append("the returning Atomic completion requires RespErr=OK")
        if response.response != int(ChiRespCode.I):
            reasons.append("Atomic completion requires Resp=I")
        if response.data_id != 0:
            reasons.append("512-bit Atomic completion requires DataID=0")
        if response.critical_chunk_id != self.profile.critical_chunk_id(
            pending_item.request
        ):
            reasons.append(
                "Atomic completion CCID must equal original Addr[5:4]"
            )
        if response.copy_at_home:
            reasons.append("non-snoop Atomic completion requires CAH=0")
        if response.data >= (1 << 512):
            reasons.append("Atomic completion data exceeds 512 bits")
        if reasons:
            return self._fault(
                state,
                "completion_profile",
                "; ".join(reasons),
            )
        original_value = self.profile.extract_value(
            pending_item.request,
            response.data,
        )
        result = ChiAtomicResult(
            pending_item.request,
            pending_item.operand_value,
            original_value,
            response,
        )
        pending = dict(state.pending)
        del pending[response.transaction_id]
        return SemanticStep(
            ChiAtomicRequesterState(
                pending,
                state.completed + (result,),
                state.issued_count,
                state.data_sent_count,
            )
        )

    def _fault(
        self,
        state: ChiAtomicRequesterState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[
        ChiAtomicRequesterState,
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


# The operation-specific public names are thin views of the single lifecycle.
# Profiles remain distinct so direct participant use cannot silently admit an
# operation that the caller did not select.
ChiAcceptAtomicSwapCompData = ChiAcceptAtomicCompData
ChiAcceptAtomicSwapDBIDResp = ChiAcceptAtomicDBIDResp
ChiAtomicSwapRequester = ChiAtomicRequester
ChiAtomicSwapRequesterAction: TypeAlias = ChiAtomicRequesterAction
ChiAtomicSwapRequesterState = ChiAtomicRequesterState


class ChiAtomicSwapPending(ChiAtomicPending):
    """Compatibility constructor retaining the ``swap_value`` keyword."""

    def __init__(
        self,
        request: ChiAtomicSwapMessage,
        swap_value: int,
        data_buffer_id: int | None = None,
    ) -> None:
        super().__init__(request, swap_value, data_buffer_id)


class ChiAtomicSwapResult(ChiAtomicResult):
    """Compatibility constructor retaining the ``swap_value`` keyword."""

    def __init__(
        self,
        request: ChiAtomicSwapMessage,
        swap_value: int,
        original_value: int,
        completion: ChiCompDataMessage,
    ) -> None:
        super().__init__(
            request,
            swap_value,
            original_value,
            completion,
        )


class ChiIssueAtomicSwap(ChiIssueAtomic):
    """Compatibility action retaining the ``swap_value`` keyword."""

    def __init__(
        self,
        request: ChiAtomicSwapMessage,
        swap_value: int,
        requester_line_is_invalid: bool,
    ) -> None:
        super().__init__(
            request,
            swap_value,
            requester_line_is_invalid,
        )

ChiAcceptAtomicLoadAddCompData = ChiAcceptAtomicCompData
ChiAcceptAtomicLoadAddDBIDResp = ChiAcceptAtomicDBIDResp
ChiAtomicLoadAddPending = ChiAtomicPending
ChiAtomicLoadAddRequester = ChiAtomicRequester
ChiAtomicLoadAddRequesterAction: TypeAlias = ChiAtomicRequesterAction
ChiAtomicLoadAddRequesterState = ChiAtomicRequesterState
ChiAtomicLoadAddResult = ChiAtomicResult
ChiIssueAtomicLoadAdd = ChiIssueAtomic


__all__ = [
    "ChiAcceptAtomicCompData",
    "ChiAcceptAtomicDBIDResp",
    "ChiAcceptAtomicLoadAddCompData",
    "ChiAcceptAtomicLoadAddDBIDResp",
    "ChiAcceptAtomicSwapCompData",
    "ChiAcceptAtomicSwapDBIDResp",
    "ChiAtomicGeometry",
    "ChiAtomicLoadAddPending",
    "ChiAtomicLoadAddProfile",
    "ChiAtomicLoadAddRequester",
    "ChiAtomicLoadAddRequesterAction",
    "ChiAtomicLoadAddRequesterState",
    "ChiAtomicLoadAddResult",
    "ChiAtomicOperation",
    "ChiAtomicPending",
    "ChiAtomicProfile",
    "ChiAtomicRequest",
    "ChiAtomicRequester",
    "ChiAtomicRequesterAction",
    "ChiAtomicRequesterState",
    "ChiAtomicResult",
    "ChiAtomicSwapPending",
    "ChiAtomicSwapProfile",
    "ChiAtomicSwapRequester",
    "ChiAtomicSwapRequesterAction",
    "ChiAtomicSwapRequesterState",
    "ChiAtomicSwapResult",
    "ChiIssueAtomic",
    "ChiIssueAtomicLoadAdd",
    "ChiIssueAtomicSwap",
]
