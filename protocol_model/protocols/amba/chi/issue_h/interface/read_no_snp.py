"""A direct-Home, single-DAT-flit ReadNoSnp transaction ledger."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

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

from ..representation import ChiCompDataMessage, ChiReadNoSnpMessage


@dataclass(frozen=True)
class ChiReadNoSnpDirectProfile:
    """Restricted profile used by the first closed read lifecycle."""

    requester_node_id: int
    home_node_id: int
    data_width: int = 128
    outstanding_capacity: int = 8

    def __post_init__(self) -> None:
        for name, value in (
            ("requester_node_id", self.requester_node_id),
            ("home_node_id", self.home_node_id),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.requester_node_id == self.home_node_id:
            raise ValueError("Requester and Home Node IDs must differ")
        if self.data_width not in (128, 256, 512):
            raise ValueError("data_width must be 128, 256, or 512 bits")
        if (
            not isinstance(self.outstanding_capacity, int)
            or isinstance(self.outstanding_capacity, bool)
            or self.outstanding_capacity <= 0
        ):
            raise ValueError("outstanding capacity must be positive")

    @property
    def data_bytes(self) -> int:
        return self.data_width // 8

    def expected_data_id(self, address: int) -> int:
        chunk = (address % 64) // self.data_bytes
        return chunk if self.data_width == 128 else chunk * 2


@dataclass(frozen=True)
class ChiReadNoSnpIssue:
    request: ChiReadNoSnpMessage

    def __post_init__(self) -> None:
        if not isinstance(self.request, ChiReadNoSnpMessage):
            raise TypeError("ReadNoSnp issue requires ChiReadNoSnpMessage")


@dataclass(frozen=True)
class ChiReadNoSnpComplete:
    response: ChiCompDataMessage

    def __post_init__(self) -> None:
        if not isinstance(self.response, ChiCompDataMessage):
            raise TypeError("ReadNoSnp completion requires ChiCompDataMessage")


ChiReadNoSnpAction = ChiReadNoSnpIssue | ChiReadNoSnpComplete


@dataclass(frozen=True)
class ChiReadNoSnpResult:
    request: ChiReadNoSnpMessage
    response: ChiCompDataMessage

    @property
    def data(self) -> int:
        return self.response.data


@dataclass(frozen=True)
class ChiReadNoSnpLedgerState:
    outstanding: Mapping[int, ChiReadNoSnpMessage]
    completed: tuple[ChiReadNoSnpResult, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "outstanding", MappingProxyType(dict(self.outstanding))
        )


class ChiReadNoSnpDirectLedger(
    SemanticComponent[
        ChiReadNoSnpAction,
        ChiReadNoSnpLedgerState,
        ChiReadNoSnpResult,
    ]
):
    """Correlate one-request/one-CompData direct-Home happy paths.

    The subset fixes ``Order=00`` and ``ExpCompAck=0`` so no ReadReceipt,
    protocol RSP, or CompAck is expected.  The Home accepts the initial
    ``AllowRetry=1`` request instead of choosing RetryAck.  This ledger checks
    protocol lifecycle only; REQ and DAT L-Credits remain transport state.
    """

    def __init__(self, name: str, profile: ChiReadNoSnpDirectProfile) -> None:
        if not name:
            raise ValueError("ReadNoSnp ledger requires a name")
        if not isinstance(profile, ChiReadNoSnpDirectProfile):
            raise TypeError("ReadNoSnp ledger requires its direct profile")
        self.name = name
        self.profile = profile
        self.semantics = SemanticFragment(
            f"{name}.semantics",
            constraints=(
                SemanticConstraint(
                    f"{name}.correlation",
                    "CompData transaction identity matches an outstanding "
                    "ReadNoSnp on this configured interface",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RELATION,
                ),
            ),
            resources=(
                ResourceDecl(
                    f"{name}.outstanding",
                    ConstraintScope.INTERFACE,
                    capacity=profile.outstanding_capacity,
                    description="accepted ReadNoSnp requests awaiting CompData",
                    acquired_by=("ReadNoSnp",),
                    released_by=("CompData",),
                ),
            ),
            sources=("Arm IHI 0050 Issue H B2.3.1.2 and B2.5.1.4",),
        )

    def initial_state(self) -> ChiReadNoSnpLedgerState:
        return ChiReadNoSnpLedgerState({})

    def is_quiescent(self, state: ChiReadNoSnpLedgerState) -> bool:
        return isinstance(state, ChiReadNoSnpLedgerState) and not state.outstanding

    def step(
        self,
        state: ChiReadNoSnpLedgerState,
        action: ChiReadNoSnpAction,
    ) -> SemanticStep[ChiReadNoSnpLedgerState, ChiReadNoSnpResult]:
        if not isinstance(state, ChiReadNoSnpLedgerState):
            raise TypeError("ReadNoSnp ledger requires its state type")
        if isinstance(action, ChiReadNoSnpIssue):
            return self._issue(state, action.request)
        if isinstance(action, ChiReadNoSnpComplete):
            return self._complete(state, action.response)
        raise TypeError("unknown ReadNoSnp ledger action")

    def _issue(
        self,
        state: ChiReadNoSnpLedgerState,
        request: ChiReadNoSnpMessage,
    ) -> SemanticStep[ChiReadNoSnpLedgerState, ChiReadNoSnpResult]:
        reasons: list[str] = []
        if request.order != 0:
            reasons.append("direct profile requires Order=00")
        if request.expect_completion_ack:
            reasons.append("direct profile requires ExpCompAck=0")
        if not request.allow_retry:
            reasons.append("an initial ReadNoSnp must set AllowRetry")
        if request.protocol_credit_type != 0:
            reasons.append("initial ReadNoSnp requires PCrdType=0")
        requested_bytes = 1 << request.size
        offset = request.address % self.profile.data_bytes
        if requested_bytes > self.profile.data_bytes:
            reasons.append("direct profile supports one DAT flit per request")
        if offset + requested_bytes > self.profile.data_bytes:
            reasons.append("request crosses the selected DAT payload chunk")
        if reasons:
            return self._fault(state, "request_profile", "; ".join(reasons))
        key = request.transaction_id
        if key in state.outstanding:
            return self._fault(
                state,
                "duplicate_identity",
                f"ReadNoSnp identity {key!r} is already outstanding",
            )
        if len(state.outstanding) >= self.profile.outstanding_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"{self.name}.outstanding",
                    ConstraintScope.INTERFACE,
                    available=0,
                    capacity=self.profile.outstanding_capacity,
                    reason="ReadNoSnp outstanding capacity is full",
                    location=self.name,
                ),
            )
        outstanding = dict(state.outstanding)
        outstanding[key] = request
        return SemanticStep(
            ChiReadNoSnpLedgerState(outstanding, state.completed)
        )

    def _complete(
        self,
        state: ChiReadNoSnpLedgerState,
        response: ChiCompDataMessage,
    ) -> SemanticStep[ChiReadNoSnpLedgerState, ChiReadNoSnpResult]:
        key = response.transaction_id
        request = state.outstanding.get(key)
        if request is None:
            return self._fault(
                state,
                "unknown_completion",
                f"CompData identity {key!r} has no outstanding request",
            )
        reasons: list[str] = []
        if response.home_node_id != self.profile.home_node_id:
            reasons.append("CompData HomeNID is not the configured Home")
        if response.response_error != 0 or response.response != 0:
            reasons.append("direct happy path requires successful CompData_I")
        expected_data_id = self.profile.expected_data_id(request.address)
        if response.data_id != expected_data_id:
            reasons.append(
                f"CompData DataID must be {expected_data_id} for this address"
            )
        if response.data >= (1 << self.profile.data_width):
            reasons.append("CompData payload exceeds the configured DAT width")
        if reasons:
            return self._fault(state, "completion_profile", "; ".join(reasons))
        outstanding = dict(state.outstanding)
        del outstanding[key]
        result = ChiReadNoSnpResult(request, response)
        return SemanticStep(
            ChiReadNoSnpLedgerState(
                outstanding, state.completed + (result,)
            ),
            (result,),
        )

    def _fault(
        self,
        state: ChiReadNoSnpLedgerState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiReadNoSnpLedgerState, ChiReadNoSnpResult]:
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
    "ChiReadNoSnpAction",
    "ChiReadNoSnpComplete",
    "ChiReadNoSnpDirectLedger",
    "ChiReadNoSnpDirectProfile",
    "ChiReadNoSnpIssue",
    "ChiReadNoSnpLedgerState",
    "ChiReadNoSnpResult",
]
