"""Backing-owning Home participant shared by returning CHI Atomics."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping, TypeAlias

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
from protocol_model.virtual_dut.backend.backing import (
    BackingCommitConflict,
    FullLineBackingCore,
    LineBackingState,
)

from ..interface.atomic import (
    ChiAtomicGeometry,
    ChiAtomicOperation,
    ChiAtomicProfile,
    ChiAtomicRequest,
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
_TRANSACTION_ID_LIMIT = 1 << 12
_MAX_REQUESTER_OUTSTANDING = 1 << 10


def _require_node_id(name: str, value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError(f"{name} must be a non-negative integer")


def _swap_value(
    original_value: int,
    operand_value: int,
    value_mask: int,
) -> int:
    del original_value
    return operand_value & value_mask


def _load_add_value(
    original_value: int,
    operand_value: int,
    value_mask: int,
) -> int:
    return (original_value + operand_value) & value_mask


_AtomicUpdate: TypeAlias = Callable[[int, int, int], int]
_ATOMIC_UPDATE_BY_REQUEST_TYPE: Mapping[type, _AtomicUpdate] = (
    MappingProxyType(
        {
            ChiAtomicSwapMessage: _swap_value,
            ChiAtomicLoadAddMessage: _load_add_value,
        }
    )
)


def _operation_for_request(
    request: ChiAtomicRequest,
) -> ChiAtomicOperation:
    if isinstance(request, ChiAtomicSwapMessage):
        return ChiAtomicOperation.SWAP
    if isinstance(request, ChiAtomicLoadAddMessage):
        return ChiAtomicOperation.LOAD_ADD
    raise TypeError(
        "Atomic Home requires AtomicSwap or AtomicLoad ADD"
    )


@dataclass(frozen=True)
class ChiAtomicHomePending:
    """One admitted returning Atomic holding the line and a Home DBID."""

    requester_node_id: int
    request: ChiAtomicRequest
    data_buffer_id: int
    expected_backing_version: int

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        ChiAtomicGeometry.from_request(self.request)
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
            raise ValueError("Atomic data_buffer_id must be 12-bit")

    @property
    def operation(self) -> ChiAtomicOperation:
        return _operation_for_request(self.request)


@dataclass(frozen=True)
class ChiAtomicHomeAcceptRequest:
    requester_node_id: int
    request: ChiAtomicRequest

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        ChiAtomicGeometry.from_request(self.request)


@dataclass(frozen=True)
class ChiAtomicHomeAcceptData:
    requester_node_id: int
    data: ChiNonCopyBackWrDataMessage

    def __post_init__(self) -> None:
        _require_node_id("requester_node_id", self.requester_node_id)
        if not isinstance(self.data, ChiNonCopyBackWrDataMessage):
            raise TypeError(
                "Atomic Home data action requires NonCopyBackWrData"
            )


ChiAtomicHomeAction: TypeAlias = (
    ChiAtomicHomeAcceptRequest | ChiAtomicHomeAcceptData
)
ChiAtomicHomeEmission: TypeAlias = (
    ChiDBIDRespMessage | ChiCompDataMessage
)


@dataclass(frozen=True)
class ChiAtomicHomeState:
    """One backing authority plus the live Atomic serialization points."""

    backing: LineBackingState
    pending_by_dbid: Mapping[int, ChiAtomicHomePending] = field(
        default_factory=dict
    )
    next_data_buffer_id: int = 0
    accepted_count: int = 0
    committed_count: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.backing, LineBackingState):
            raise TypeError(
                "Atomic Home backing requires LineBackingState"
            )
        pending = dict(self.pending_by_dbid)
        if any(
            not isinstance(item, ChiAtomicHomePending)
            or data_buffer_id != item.data_buffer_id
            for data_buffer_id, item in pending.items()
        ):
            raise ValueError(
                "Atomic Home pending keys must match granted DBIDs"
            )
        line_addresses = tuple(
            item.request.address - item.request.address % _CACHE_LINE_BYTES
            for item in pending.values()
        )
        if len(set(line_addresses)) != len(line_addresses):
            raise ValueError(
                "the Atomic Home profile reserves one operation "
                "per line"
            )
        original_identities = tuple(
            (
                item.requester_node_id,
                item.request.transaction_id,
            )
            for item in pending.values()
        )
        if len(set(original_identities)) != len(original_identities):
            raise ValueError(
                "one Requester Atomic original TxnID can have only one "
                "live Home transaction"
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
                "Atomic committed count cannot exceed accepted count"
            )
        object.__setattr__(
            self,
            "pending_by_dbid",
            MappingProxyType(pending),
        )


class ChiAtomicHomeNode(
    SemanticComponent[
        ChiAtomicHomeAction,
        ChiAtomicHomeState,
        ChiAtomicHomeEmission,
    ]
):
    """Execute one old-value read and masked replacement in one transition."""

    def __init__(
        self,
        name: str,
        profile: ChiAtomicProfile,
        *,
        backing_core: FullLineBackingCore,
        transaction_capacity: int = 4,
        initial_data_buffer_id: int = 0x200,
    ) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("Atomic Home requires a name")
        if not isinstance(profile, ChiAtomicProfile):
            raise TypeError("Atomic Home requires ChiAtomicProfile")
        if not isinstance(backing_core, FullLineBackingCore):
            raise TypeError("Atomic Home requires FullLineBackingCore")
        if backing_core.line_bytes != _CACHE_LINE_BYTES:
            raise ValueError("Atomic requires 64-byte backing lines")
        if (
            not isinstance(transaction_capacity, int)
            or isinstance(transaction_capacity, bool)
            or not 0
            < transaction_capacity
            <= _MAX_REQUESTER_OUTSTANDING
        ):
            raise ValueError("transaction_capacity must be in 1..1024")
        if (
            not isinstance(initial_data_buffer_id, int)
            or isinstance(initial_data_buffer_id, bool)
            or not 0 <= initial_data_buffer_id < _TRANSACTION_ID_LIMIT
        ):
            raise ValueError("initial_data_buffer_id must be 12-bit")
        self.name = name
        self.profile = profile
        self.backing_core = backing_core
        self.transaction_capacity = transaction_capacity
        self.initial_data_buffer_id = initial_data_buffer_id
        self.semantics = SemanticFragment(
            f"{name}.semantics",
            constraints=(
                SemanticConstraint(
                    f"{name}.atomic_rmw",
                    "the returned original value and masked replacement "
                    "derive from one pre-commit line version",
                    ConstraintScope.VIRTUAL_DUT,
                    kind=ConstraintKind.RELATION,
                ),
                SemanticConstraint(
                    f"{name}.same_line_serialization",
                    "one admitted Atomic holds its 64-byte line until "
                    "valid operand DAT commits; rejected transitions do not "
                    "release the reservation",
                    ConstraintScope.VIRTUAL_DUT,
                    kind=ConstraintKind.RELATION,
                ),
            ),
            resources=(
                ResourceDecl(
                    f"{name}.data_buffer",
                    ConstraintScope.VIRTUAL_DUT,
                    capacity=transaction_capacity,
                    description="Home DBIDs for returning Atomic operand data",
                    acquired_by=tuple(
                        operation.value
                        for operation in sorted(
                            profile.enabled_operations,
                            key=lambda item: item.value,
                        )
                    ),
                    released_by=("NonCopyBackWrData",),
                ),
            ),
            sources=(
                "Arm IHI 0050 Issue H B2.3.3, B2.9.6, and B4.2.5",
            ),
        )

    def initial_state(self) -> ChiAtomicHomeState:
        return ChiAtomicHomeState(
            self.backing_core.initial_state(),
            next_data_buffer_id=self.initial_data_buffer_id,
        )

    def is_quiescent(self, state: ChiAtomicHomeState) -> bool:
        return (
            isinstance(state, ChiAtomicHomeState)
            and not state.pending_by_dbid
        )

    def step(
        self,
        state: ChiAtomicHomeState,
        action: ChiAtomicHomeAction,
    ) -> SemanticStep[
        ChiAtomicHomeState,
        ChiAtomicHomeEmission,
    ]:
        if not isinstance(state, ChiAtomicHomeState):
            raise TypeError("Atomic Home requires its state type")
        if isinstance(action, ChiAtomicHomeAcceptRequest):
            return self._accept_request(
                state,
                action.requester_node_id,
                action.request,
            )
        if isinstance(action, ChiAtomicHomeAcceptData):
            return self._accept_data(
                state,
                action.requester_node_id,
                action.data,
            )
        raise TypeError("unknown Atomic Home action")

    def _accept_request(
        self,
        state: ChiAtomicHomeState,
        requester_node_id: int,
        request: ChiAtomicRequest,
    ) -> SemanticStep[
        ChiAtomicHomeState,
        ChiAtomicHomeEmission,
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
                "Atomic request came from another Requester NodeID",
            )
        if any(
            item.requester_node_id == requester_node_id
            and item.request.transaction_id == request.transaction_id
            for item in state.pending_by_dbid.values()
        ):
            return self._fault(
                state,
                "duplicate_identity",
                "Atomic original TxnID is already live for this "
                "Requester",
            )
        line_address = self.profile.line_address(request)
        if any(
            self.profile.line_address(item.request) == line_address
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
                        "the Atomic Home profile serializes "
                        "same-line operations"
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
                    reason="Atomic Home DBID capacity is full",
                    location=self.name,
                ),
            )
        try:
            self.backing_core.read_line(
                state.backing,
                line_address,
            )
        except KeyError:
            return self._fault(
                state,
                "backing_address",
                f"Home has no backing line at {line_address:#x}",
            )
        except (TypeError, ValueError) as error:
            return self._fault(
                state,
                "backing_state",
                str(error),
            )
        record = state.backing.line_at(line_address)
        if record is None:
            raise RuntimeError(
                "validated Atomic backing line disappeared before admission"
            )
        data_buffer_id = self._next_free_dbid(state)
        pending = dict(state.pending_by_dbid)
        pending[data_buffer_id] = ChiAtomicHomePending(
            requester_node_id,
            request,
            data_buffer_id,
            record.version,
        )
        response = ChiDBIDRespMessage(
            transaction_id=request.transaction_id,
            data_buffer_id=data_buffer_id,
        )
        return SemanticStep(
            ChiAtomicHomeState(
                state.backing,
                pending,
                (data_buffer_id + 1) % _TRANSACTION_ID_LIMIT,
                state.accepted_count + 1,
                state.committed_count,
            ),
            (response,),
        )

    def _accept_data(
        self,
        state: ChiAtomicHomeState,
        requester_node_id: int,
        data: ChiNonCopyBackWrDataMessage,
    ) -> SemanticStep[
        ChiAtomicHomeState,
        ChiAtomicHomeEmission,
    ]:
        pending_item = state.pending_by_dbid.get(data.transaction_id)
        if pending_item is None:
            return self._fault(
                state,
                "unknown_data_buffer",
                "Atomic operand DAT does not select a live Home DBID",
            )
        if pending_item.requester_node_id != requester_node_id:
            return self._fault(
                state,
                "data_requester",
                "Atomic operand DAT came from another Requester",
            )
        request = pending_item.request
        profile_reasons = self.profile.explain_request(request)
        if profile_reasons:
            return self._fault(
                state,
                "retained_request_profile",
                "; ".join(profile_reasons),
            )
        geometry = self.profile.geometry(request)
        reasons: list[str] = []
        if data.response is not ChiRespCode.I:
            reasons.append("Atomic NonCopyBackWrData requires Resp=I")
        if data.response_error is not ChiRespErr.OK:
            reasons.append(
                "the returning Atomic operand DAT requires RespErr=OK"
            )
        if data.data_id != 0:
            reasons.append("512-bit Atomic operand DAT requires DataID=0")
        if data.critical_chunk_id != geometry.critical_chunk_id:
            reasons.append(
                "Atomic operand DAT CCID must equal original Addr[5:4]"
            )
        if data.data >= (1 << 512):
            reasons.append("Atomic operand DAT exceeds 512 bits")
        if data.byte_enable != geometry.byte_enable:
            reasons.append(
                "Atomic operand DAT requires every byte in the exact "
                "transfer window enabled and all other lanes disabled"
            )
        if data.data & ~geometry.positioned_mask:
            reasons.append(
                "Atomic operand DAT carries nonzero data outside its "
                "transfer window"
            )
        if reasons:
            return self._fault(
                state,
                "data_profile",
                "; ".join(reasons),
            )
        line_address = geometry.line_address
        current = state.backing.line_at(line_address)
        if (
            current is None
            or current.version != pending_item.expected_backing_version
        ):
            return self._fault(
                state,
                "backing_version",
                "the backing line changed while Atomic held its DBID",
            )
        original_value = geometry.extract(current.data)
        operand_value = geometry.extract(data.data)
        update = _ATOMIC_UPDATE_BY_REQUEST_TYPE.get(type(request))
        if update is None:
            return self._fault(
                state,
                "request_operation",
                "Home has no operation implementation for this Atomic REQ",
            )
        replacement_value = update(
            original_value,
            operand_value,
            geometry.value_mask,
        )
        try:
            prepared = self.backing_core.prepare_masked_write(
                state.backing,
                line_address,
                geometry.position(replacement_value),
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
                state,
                "backing_commit",
                str(error),
            )
        completion = ChiCompDataMessage(
            transaction_id=request.transaction_id,
            data=geometry.position(original_value),
            data_id=0,
            home_node_id=self.profile.home_node_id,
            response_error=ChiRespErr.OK,
            response=ChiRespCode.I,
            data_buffer_id=0,
            copy_at_home=False,
            critical_chunk_id=geometry.critical_chunk_id,
        )
        pending = dict(state.pending_by_dbid)
        del pending[data.transaction_id]
        return SemanticStep(
            ChiAtomicHomeState(
                mutation.state,
                pending,
                state.next_data_buffer_id,
                state.accepted_count,
                state.committed_count + 1,
            ),
            (completion,),
        )

    def _next_free_dbid(self, state: ChiAtomicHomeState) -> int:
        candidate = state.next_data_buffer_id
        for _ in range(_TRANSACTION_ID_LIMIT):
            if candidate not in state.pending_by_dbid:
                return candidate
            candidate = (candidate + 1) % _TRANSACTION_ID_LIMIT
        raise RuntimeError(
            "validated Atomic Home capacity has no free DBID"
        )

    def _fault(
        self,
        state: ChiAtomicHomeState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[
        ChiAtomicHomeState,
        ChiAtomicHomeEmission,
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


# Operation-specific public names remain thin views of the one Home runtime.
ChiAtomicSwapHomeAcceptData = ChiAtomicHomeAcceptData
ChiAtomicSwapHomeAcceptRequest = ChiAtomicHomeAcceptRequest
ChiAtomicSwapHomeAction: TypeAlias = ChiAtomicHomeAction
ChiAtomicSwapHomeEmission: TypeAlias = ChiAtomicHomeEmission
ChiAtomicSwapHomeNode = ChiAtomicHomeNode
ChiAtomicSwapHomePending = ChiAtomicHomePending
ChiAtomicSwapHomeState = ChiAtomicHomeState

ChiAtomicLoadAddHomeAcceptData = ChiAtomicHomeAcceptData
ChiAtomicLoadAddHomeAcceptRequest = ChiAtomicHomeAcceptRequest
ChiAtomicLoadAddHomeAction: TypeAlias = ChiAtomicHomeAction
ChiAtomicLoadAddHomeEmission: TypeAlias = ChiAtomicHomeEmission
ChiAtomicLoadAddHomeNode = ChiAtomicHomeNode
ChiAtomicLoadAddHomePending = ChiAtomicHomePending
ChiAtomicLoadAddHomeState = ChiAtomicHomeState


__all__ = [
    "ChiAtomicHomeAcceptData",
    "ChiAtomicHomeAcceptRequest",
    "ChiAtomicHomeAction",
    "ChiAtomicHomeEmission",
    "ChiAtomicHomeNode",
    "ChiAtomicHomePending",
    "ChiAtomicHomeState",
    "ChiAtomicLoadAddHomeAcceptData",
    "ChiAtomicLoadAddHomeAcceptRequest",
    "ChiAtomicLoadAddHomeAction",
    "ChiAtomicLoadAddHomeEmission",
    "ChiAtomicLoadAddHomeNode",
    "ChiAtomicLoadAddHomePending",
    "ChiAtomicLoadAddHomeState",
    "ChiAtomicSwapHomeAcceptData",
    "ChiAtomicSwapHomeAcceptRequest",
    "ChiAtomicSwapHomeAction",
    "ChiAtomicSwapHomeEmission",
    "ChiAtomicSwapHomeNode",
    "ChiAtomicSwapHomePending",
    "ChiAtomicSwapHomeState",
]
