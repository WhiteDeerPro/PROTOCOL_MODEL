"""Finite Home behavior for the first executable CHI Request-Retry flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Callable, Mapping

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticStep,
)

from ..interface import (
    ChiRequestRetryContract,
    ChiRequestRetryContractError,
    ChiRequestRetryHomeState,
    ChiRetryDebt,
)
from ..representation import (
    ChiCompDataMessage,
    ChiPCrdReturnMessage,
    ChiPCrdGrantMessage,
    ChiReadNoSnpMessage,
    ChiRetryAckMessage,
)
from .direct_home import (
    ChiDirectHomeAccept,
    ChiDirectHomeNode,
    ChiDirectHomeService,
    ChiDirectHomeState,
)

@dataclass(frozen=True)
class ChiRetryHomeGrant:
    """Allocate one available Home slot to the oldest retry debt."""


@dataclass(frozen=True)
class ChiRetryHomeReturn:
    """Consume one PCrdReturn and release its reserved Home slot."""

    request: ChiPCrdReturnMessage

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiPCrdReturnMessage):
            raise TypeError("Home P-Credit return requires ChiPCrdReturnMessage")


ChiRetryHomeAction = (
    ChiDirectHomeAccept
    | ChiDirectHomeService
    | ChiRetryHomeGrant
    | ChiRetryHomeReturn
)
ChiRetryHomeEmission = ChiRetryAckMessage | ChiPCrdGrantMessage | ChiCompDataMessage


@dataclass(frozen=True)
class ChiRetryHomeState(ChiDirectHomeState):
    """Accepted work plus protocol-credit obligations and reservations."""

    retry_debts: tuple[ChiRetryDebt, ...] = ()
    reserved_by_requester_and_type: Mapping[tuple[int, int], int] = field(
        default_factory=dict
    )
    retry_ack_count: int = 0
    grant_count: int = 0
    retried_accept_count: int = 0
    returned_credit_count: int = 0

    def __post_init__(self) -> None:
        debts = tuple(self.retry_debts)
        if any(not isinstance(item, ChiRetryDebt) for item in debts):
            raise TypeError("retry debts require ChiRetryDebt values")
        reservations = dict(self.reserved_by_requester_and_type)
        if any(
            (
                not isinstance(key, tuple)
                or len(key) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                    for value in key
                )
                or key[1] >= 16
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
            )
            for key, count in reservations.items()
        ):
            raise ValueError("Home P-Credit reservations are malformed")
        for name, value in (
            ("retry_ack_count", self.retry_ack_count),
            ("grant_count", self.grant_count),
            ("retried_accept_count", self.retried_accept_count),
            ("returned_credit_count", self.returned_credit_count),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        reserved_count = sum(reservations.values())
        if self.retry_ack_count != self.grant_count + len(debts):
            raise ValueError(
                "RetryAck count must equal granted credits plus retry debts"
            )
        if self.grant_count != (
            self.retried_accept_count
            + self.returned_credit_count
            + reserved_count
        ):
            raise ValueError(
                "P-Credit grants must equal retried, returned, and reserved slots"
            )
        object.__setattr__(self, "retry_debts", debts)
        object.__setattr__(
            self,
            "reserved_by_requester_and_type",
            MappingProxyType(reservations),
        )

    @property
    def reserved_count(self) -> int:
        return sum(self.reserved_by_requester_and_type.values())

    @property
    def retry_contract(self) -> ChiRequestRetryHomeState:
        """Project the legacy direct-Home facade onto the shared contract."""

        return ChiRequestRetryHomeState(
            self.retry_debts,
            self.reserved_by_requester_and_type,
            self.retry_ack_count,
            self.grant_count,
            self.retried_accept_count,
            self.returned_credit_count,
        )


ChiRetryAdmissionPolicy = Callable[
    [ChiReadNoSnpMessage, ChiRetryHomeState], int | None
]


class ChiRetryHomeNode(ChiDirectHomeNode):
    """A direct Home that can reject an initial request and reserve a retry.

    ``retry_policy`` returns a 4-bit P-Credit type when an otherwise valid
    initial request is to receive RetryAck, or ``None`` when normal admission
    should be attempted.  The function is expected to be side-effect free.
    A full unreserved request FIFO also produces RetryAck using
    ``default_credit_type``.

    A Grant reserves a real request slot.  A later ``AllowRetry=0`` request
    consumes any reservation with the same Requester NodeID and PCrdType; the
    reservation is deliberately not bound to the RetryAck TxnID.
    """

    def __init__(
        self,
        name,
        profile,
        data_policy,
        *,
        request_capacity: int = 4,
        default_credit_type: int = 0,
        retry_policy: ChiRetryAdmissionPolicy | None = None,
    ) -> None:
        super().__init__(
            name,
            profile,
            data_policy,
            request_capacity=request_capacity,
        )
        if (
            not isinstance(default_credit_type, int)
            or isinstance(default_credit_type, bool)
            or not 0 <= default_credit_type < 16
        ):
            raise ValueError("default P-Credit type must be in 0..15")
        if retry_policy is not None and not callable(retry_policy):
            raise TypeError("retry policy must be callable")
        self.default_credit_type = default_credit_type
        self.retry_policy = retry_policy

    def initial_state(self) -> ChiRetryHomeState:
        return ChiRetryHomeState()

    def is_quiescent(self, state: ChiRetryHomeState) -> bool:
        return (
            isinstance(state, ChiRetryHomeState)
            and not state.pending
            and not state.retry_debts
            and not state.reserved_by_requester_and_type
        )

    def step(
        self,
        state: ChiRetryHomeState,
        action: ChiRetryHomeAction,
    ) -> SemanticStep[ChiRetryHomeState, ChiRetryHomeEmission]:
        if not isinstance(state, ChiRetryHomeState):
            raise TypeError("retry Home requires ChiRetryHomeState")
        invariant = self._retry_invariant(state)
        if invariant is not None:
            return invariant
        if isinstance(action, ChiDirectHomeAccept):
            return self._retry_accept(state, action.request)
        if isinstance(action, ChiRetryHomeGrant):
            return self._grant(state)
        if isinstance(action, ChiRetryHomeReturn):
            return self._return_credit(state, action.request)
        if isinstance(action, ChiDirectHomeService):
            return self._retry_service(state)
        raise TypeError("unknown retry Home action")

    def _retry_accept(
        self,
        state: ChiRetryHomeState,
        request: ChiReadNoSnpMessage,
    ) -> SemanticStep[ChiRetryHomeState, ChiRetryHomeEmission]:
        reason = self._request_reason(request)
        if reason is not None:
            return self._retry_fault(state, "request", reason)
        if any(
            item.semantic_key == request.semantic_key for item in state.pending
        ):
            return self._retry_fault(
                state,
                "duplicate_identity",
                "the Home already holds this request identity",
            )

        if not request.allow_retry:
            try:
                retry = ChiRequestRetryContract.consume_reservation(
                    state.retry_contract,
                    requester_id=self.profile.requester_node_id,
                    protocol_credit_type=request.protocol_credit_type,
                )
            except ChiRequestRetryContractError as error:
                return self._retry_fault(
                    state,
                    error.code,
                    error.reason,
                )
            return SemanticStep(
                ChiRetryHomeState(
                    state.pending + (request,),
                    state.accepted_count + 1,
                    state.completed_count,
                    retry.retry_debts,
                    retry.reservations,
                    retry.retry_ack_count,
                    retry.grant_count,
                    retry.consumed_count,
                    retry.returned_count,
                )
            )

        if request.protocol_credit_type != 0:
            return self._retry_fault(
                state,
                "initial_credit_type",
                "initial retryable request requires PCrdType=0",
            )
        credit_type = (
            None
            if self.retry_policy is None
            else self.retry_policy(request, state)
        )
        if credit_type is None and (
            state.depth + state.reserved_count < self.request_capacity
        ):
            return SemanticStep(
                ChiRetryHomeState(
                    state.pending + (request,),
                    state.accepted_count + 1,
                    state.completed_count,
                    state.retry_debts,
                    state.reserved_by_requester_and_type,
                    state.retry_ack_count,
                    state.grant_count,
                    state.retried_accept_count,
                    state.returned_credit_count,
                )
            )
        if credit_type is None:
            credit_type = self.default_credit_type
        if (
            not isinstance(credit_type, int)
            or isinstance(credit_type, bool)
            or not 0 <= credit_type < 16
        ):
            return self._retry_fault(
                state,
                "retry_policy",
                "retry policy returned a P-Credit type outside 0..15",
            )
        try:
            retry, response = ChiRequestRetryContract.record_retry(
                state.retry_contract,
                requester_id=self.profile.requester_node_id,
                transaction_id=request.transaction_id,
                protocol_credit_type=credit_type,
            )
        except ChiRequestRetryContractError as error:
            return self._retry_fault(
                state,
                error.code,
                error.reason,
            )
        return SemanticStep(
            ChiRetryHomeState(
                state.pending,
                state.accepted_count,
                state.completed_count,
                retry.retry_debts,
                retry.reservations,
                retry.retry_ack_count,
                retry.grant_count,
                retry.consumed_count,
                retry.returned_count,
            ),
            (response,),
        )

    def _grant(
        self, state: ChiRetryHomeState
    ) -> SemanticStep[ChiRetryHomeState, ChiRetryHomeEmission]:
        if not state.retry_debts:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.retry_debt",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    reason="Home has no RetryAck awaiting P-Credit",
                    location=self.name,
                ),
            )
        if state.depth + state.reserved_count >= self.request_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.retry_reservation_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.request_capacity,
                    reason="Home has no request slot to reserve for a retry",
                    location=self.name,
                ),
            )
        retry, _debt, grant = ChiRequestRetryContract.grant_oldest(
            state.retry_contract
        )
        return SemanticStep(
            ChiRetryHomeState(
                state.pending,
                state.accepted_count,
                state.completed_count,
                retry.retry_debts,
                retry.reservations,
                retry.retry_ack_count,
                retry.grant_count,
                retry.consumed_count,
                retry.returned_count,
            ),
            (grant,),
        )

    def _return_credit(
        self,
        state: ChiRetryHomeState,
        request: ChiPCrdReturnMessage,
    ) -> SemanticStep[ChiRetryHomeState, ChiRetryHomeEmission]:
        try:
            retry = ChiRequestRetryContract.return_reservation(
                state.retry_contract,
                request,
                requester_id=self.profile.requester_node_id,
            )
        except ChiRequestRetryContractError as error:
            return self._retry_fault(
                state,
                error.code,
                error.reason,
            )
        return SemanticStep(
            ChiRetryHomeState(
                state.pending,
                state.accepted_count,
                state.completed_count,
                retry.retry_debts,
                retry.reservations,
                retry.retry_ack_count,
                retry.grant_count,
                retry.consumed_count,
                retry.returned_count,
            )
        )

    def _retry_service(
        self, state: ChiRetryHomeState
    ) -> SemanticStep[ChiRetryHomeState, ChiRetryHomeEmission]:
        base = ChiDirectHomeState(
            state.pending, state.accepted_count, state.completed_count
        )
        transition = super()._service(base)
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        if transition.blocked is not None:
            return SemanticStep(state, blocked=transition.blocked)
        candidate = transition.state
        return SemanticStep(
            ChiRetryHomeState(
                candidate.pending,
                candidate.accepted_count,
                candidate.completed_count,
                state.retry_debts,
                state.reserved_by_requester_and_type,
                state.retry_ack_count,
                state.grant_count,
                state.retried_accept_count,
                state.returned_credit_count,
            ),
            transition.emissions,
        )

    def _request_reason(self, request: ChiReadNoSnpMessage) -> str | None:
        if request.order != 0 or request.expect_completion_ack:
            return "request is outside the direct-Home read profile"
        requested_bytes = 1 << request.size
        if (
            requested_bytes > self.profile.data_bytes
            or request.address % self.profile.data_bytes + requested_bytes
            > self.profile.data_bytes
        ):
            return "request does not fit one DAT payload chunk"
        return None

    def _retry_invariant(
        self, state: ChiRetryHomeState
    ) -> SemanticStep[ChiRetryHomeState, ChiRetryHomeEmission] | None:
        if state.depth + state.reserved_count > self.request_capacity:
            return self._retry_fault(
                state,
                "capacity",
                "accepted requests plus P-Credit reservations exceed capacity",
            )
        debt_keys = tuple(item.request_key for item in state.retry_debts)
        if len(set(debt_keys)) != len(debt_keys):
            return self._retry_fault(
                state, "retry_debt", "duplicate Home retry debt identity"
            )
        return None

    def _retry_fault(
        self,
        state: ChiRetryHomeState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiRetryHomeState, ChiRetryHomeEmission]:
        transition = super()._fault(
            ChiDirectHomeState(
                state.pending, state.accepted_count, state.completed_count
            ),
            suffix,
            reason,
        )
        return SemanticStep(state, fault=transition.fault)


__all__ = [
    "ChiRetryAdmissionPolicy",
    "ChiRetryDebt",
    "ChiRetryHomeAction",
    "ChiRetryHomeEmission",
    "ChiRetryHomeGrant",
    "ChiRetryHomeNode",
    "ChiRetryHomeReturn",
    "ChiRetryHomeState",
]
