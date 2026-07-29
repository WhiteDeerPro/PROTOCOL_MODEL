"""A finite direct-Home behavior for the first ReadNoSnp lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)

from ..interface import ChiReadNoSnpDirectProfile
from ..representation import ChiCompDataMessage, ChiReadNoSnpMessage


ChiHomeDataPolicy = Callable[[ChiReadNoSnpMessage], int]


@dataclass(frozen=True)
class ChiDirectHomeAccept:
    request: ChiReadNoSnpMessage

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiReadNoSnpMessage):
            raise TypeError("direct Home accepts ChiReadNoSnpMessage")


@dataclass(frozen=True)
class ChiDirectHomeService:
    """Give the Home one explicit opportunity to complete its FIFO head."""


ChiDirectHomeAction = ChiDirectHomeAccept | ChiDirectHomeService


@dataclass(frozen=True)
class ChiDirectHomeState:
    pending: tuple[ChiReadNoSnpMessage, ...] = ()
    accepted_count: int = 0
    completed_count: int = 0

    @property
    def depth(self) -> int:
        return len(self.pending)


class ChiDirectHomeNode(
    SemanticComponent[
        ChiDirectHomeAction,
        ChiDirectHomeState,
        ChiCompDataMessage,
    ]
):
    """Accept ReadNoSnp requests and explicitly emit direct CompData.

    This typed behavior remains separate from ``VirtualDutBackend``.  A
    ``ChiParticipantBinding`` can associate it with the REQ/DAT transport
    ports of a concrete VirtualDut, without creating a CHI-specific DUT
    subclass or pretending that one unidirectional port owns the Home state.

    ``data_policy`` is a reference-data function and is expected to be free of
    externally visible side effects.  Stateful latency, memory mutation, or
    device effects belong in an explicit participant backend state instead of
    this response-value callback.
    """

    def __init__(
        self,
        name: str,
        profile: ChiReadNoSnpDirectProfile,
        data_policy: ChiHomeDataPolicy,
        *,
        request_capacity: int = 4,
    ) -> None:
        if not name:
            raise ValueError("direct Home node requires a name")
        if not isinstance(profile, ChiReadNoSnpDirectProfile):
            raise TypeError("direct Home requires a ReadNoSnp direct profile")
        if not callable(data_policy):
            raise TypeError("direct Home data policy must be callable")
        if (
            not isinstance(request_capacity, int)
            or isinstance(request_capacity, bool)
            or request_capacity <= 0
        ):
            raise ValueError("direct Home request capacity must be positive")
        self.name = name
        self.profile = profile
        self.data_policy = data_policy
        self.request_capacity = request_capacity

    def initial_state(self) -> ChiDirectHomeState:
        return ChiDirectHomeState()

    def is_quiescent(self, state: ChiDirectHomeState) -> bool:
        return isinstance(state, ChiDirectHomeState) and not state.pending

    def step(
        self,
        state: ChiDirectHomeState,
        action: ChiDirectHomeAction,
    ) -> SemanticStep[ChiDirectHomeState, ChiCompDataMessage]:
        if not isinstance(state, ChiDirectHomeState):
            raise TypeError("direct Home requires ChiDirectHomeState")
        if isinstance(action, ChiDirectHomeAccept):
            return self._accept(state, action.request)
        if isinstance(action, ChiDirectHomeService):
            return self._service(state)
        raise TypeError("unknown direct Home action")

    def _accept(
        self,
        state: ChiDirectHomeState,
        request: ChiReadNoSnpMessage,
    ) -> SemanticStep[ChiDirectHomeState, ChiCompDataMessage]:
        if (
            request.order != 0
            or request.expect_completion_ack
            or request.exclusive
            or not request.allow_retry
            or request.protocol_credit_type != 0
        ):
            return self._fault(
                state,
                "profile",
                "request is outside the direct-Home happy-path profile",
            )
        requested_bytes = 1 << request.size
        if (
            requested_bytes > self.profile.data_bytes
            or request.address % self.profile.data_bytes + requested_bytes
            > self.profile.data_bytes
        ):
            return self._fault(
                state,
                "packetization",
                "request does not fit one DAT payload chunk",
            )
        if any(
            item.semantic_key == request.semantic_key for item in state.pending
        ):
            return self._fault(
                state,
                "duplicate_identity",
                "the Home already holds this request identity",
            )
        if state.depth >= self.request_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.request_slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.request_capacity,
                    reason="direct Home request FIFO is full",
                    location=self.name,
                ),
            )
        return SemanticStep(
            ChiDirectHomeState(
                state.pending + (request,),
                state.accepted_count + 1,
                state.completed_count,
            )
        )

    def _service(
        self, state: ChiDirectHomeState
    ) -> SemanticStep[ChiDirectHomeState, ChiCompDataMessage]:
        if not state.pending:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.pending_request",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.request_capacity,
                    reason="direct Home has no request to service",
                    location=self.name,
                ),
            )
        request = state.pending[0]
        data = self.data_policy(request)
        if (
            not isinstance(data, int)
            or isinstance(data, bool)
            or not 0 <= data < (1 << self.profile.data_width)
        ):
            return self._fault(
                state,
                "data_policy",
                "Home data policy returned a payload outside DAT width",
            )
        response = ChiCompDataMessage(
            transaction_id=request.transaction_id,
            home_node_id=self.profile.home_node_id,
            data=data,
            data_id=self.profile.expected_data_id(request.address),
            response_error=0,
            response=0,
            data_buffer_id=0,
        )
        candidate = ChiDirectHomeState(
            state.pending[1:],
            state.accepted_count,
            state.completed_count + 1,
        )
        return SemanticStep(candidate, (response,))

    def _fault(
        self,
        state: ChiDirectHomeState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiDirectHomeState, ChiCompDataMessage]:
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
    "ChiDirectHomeAccept",
    "ChiDirectHomeAction",
    "ChiDirectHomeNode",
    "ChiDirectHomeService",
    "ChiDirectHomeState",
    "ChiHomeDataPolicy",
]
