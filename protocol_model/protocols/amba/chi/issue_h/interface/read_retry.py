"""Requester-side lifecycle for the first ReadNoSnp Request-Retry slice."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import (
    ConstraintKind,
    ConstraintScope,
    ResourceDecl,
    SemanticConstraint,
    SemanticFault,
    SemanticFragment,
    SemanticStep,
    compose_fragments,
)

from ..representation import (
    ChiCompDataMessage,
    ChiPCrdReturnMessage,
    ChiPCrdGrantMessage,
    ChiReadNoSnpMessage,
    ChiRetryAckMessage,
)
from .read_no_snp import (
    ChiReadNoSnpComplete,
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpDirectProfile,
    ChiReadNoSnpIssue,
    ChiReadNoSnpLedgerState,
    ChiReadNoSnpResult,
)


class ChiReadNoSnpRetryPhase(str, Enum):
    """Requester knowledge about one retained operation."""

    INITIAL_IN_FLIGHT = "initial_in_flight"
    WAIT_RETRY_CREDIT = "wait_retry_credit"
    RETRIED_IN_FLIGHT = "retried_in_flight"


@dataclass(frozen=True)
class ChiReadNoSnpRetryEntry:
    """Original fields plus the currently transmitted request form."""

    original_request: ChiReadNoSnpMessage
    current_request: ChiReadNoSnpMessage
    phase: ChiReadNoSnpRetryPhase
    protocol_credit_type: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.original_request, ChiReadNoSnpMessage) or not isinstance(
            self.current_request, ChiReadNoSnpMessage
        ):
            raise TypeError("retry entry requires ReadNoSnp request forms")
        if not isinstance(self.phase, ChiReadNoSnpRetryPhase):
            raise TypeError("retry entry requires a known phase")
        if self.original_request.semantic_key != self.current_request.semantic_key:
            raise ValueError("minimal retry profile keeps one request identity")
        if self.protocol_credit_type is not None and (
            not isinstance(self.protocol_credit_type, int)
            or isinstance(self.protocol_credit_type, bool)
            or not 0 <= self.protocol_credit_type < 16
        ):
            raise ValueError("retry entry P-Credit type must be in 0..15")
        if self.phase is ChiReadNoSnpRetryPhase.INITIAL_IN_FLIGHT:
            if (
                self.current_request != self.original_request
                or self.protocol_credit_type is not None
            ):
                raise ValueError("initial retry entry must retain its request")
        elif self.phase is ChiReadNoSnpRetryPhase.WAIT_RETRY_CREDIT:
            if (
                self.current_request != self.original_request
                or self.protocol_credit_type is None
            ):
                raise ValueError(
                    "RetryAck phase requires the original request and PCrdType"
                )
        else:
            if self.protocol_credit_type is None or self.current_request != replace(
                self.original_request,
                allow_retry=False,
                protocol_credit_type=self.protocol_credit_type,
            ):
                raise ValueError(
                    "retried entry must contain the credited request form"
                )

    @property
    def request_key(self) -> int:
        return self.original_request.transaction_id


@dataclass(frozen=True)
class ChiReadNoSnpObserveRetryAck:
    response: ChiRetryAckMessage

    def __post_init__(self) -> None:
        if not isinstance(self.response, ChiRetryAckMessage):
            raise TypeError("RetryAck observation requires ChiRetryAckMessage")


@dataclass(frozen=True)
class ChiReadNoSnpObservePCrdGrant:
    response: ChiPCrdGrantMessage

    def __post_init__(self) -> None:
        if not isinstance(self.response, ChiPCrdGrantMessage):
            raise TypeError("P-Credit observation requires ChiPCrdGrantMessage")


@dataclass(frozen=True)
class ChiReadNoSnpRetry:
    request_key: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_key, int)
            or isinstance(self.request_key, bool)
            or self.request_key < 0
        ):
            raise ValueError("retry request key requires a transaction ID")


@dataclass(frozen=True)
class ChiReadNoSnpCancel:
    """Cancel one acknowledged request and return its matching P-Credit."""

    request_key: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.request_key, int)
            or isinstance(self.request_key, bool)
            or self.request_key < 0
        ):
            raise ValueError("cancel request key requires a transaction ID")


ChiReadNoSnpRetryAction = (
    ChiReadNoSnpIssue
    | ChiReadNoSnpObserveRetryAck
    | ChiReadNoSnpObservePCrdGrant
    | ChiReadNoSnpRetry
    | ChiReadNoSnpCancel
    | ChiReadNoSnpComplete
)
ChiReadNoSnpRetryEmission = (
    ChiReadNoSnpMessage | ChiPCrdReturnMessage | ChiReadNoSnpResult
)


@dataclass(frozen=True)
class ChiReadNoSnpRetryLedgerState:
    """Retained requests and transaction-independent P-Credit inventory."""

    entries: Mapping[int, ChiReadNoSnpRetryEntry]
    protocol_credits: Mapping[int, int] = field(default_factory=dict)
    completed: tuple[ChiReadNoSnpResult, ...] = ()

    def __post_init__(self) -> None:
        entries = dict(self.entries)
        if any(
            not isinstance(entry, ChiReadNoSnpRetryEntry) or key != entry.request_key
            for key, entry in entries.items()
        ):
            raise ValueError("retry ledger entries disagree with their identities")
        credits = dict(self.protocol_credits)
        if any(
            (
                not isinstance(key, int)
                or isinstance(key, bool)
                or not 0 <= key < 16
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
            )
            for key, count in credits.items()
        ):
            raise ValueError("retry ledger P-Credit inventory is malformed")
        if any(not isinstance(item, ChiReadNoSnpResult) for item in self.completed):
            raise TypeError("retry ledger completions require read results")
        object.__setattr__(self, "entries", MappingProxyType(entries))
        object.__setattr__(
            self, "protocol_credits", MappingProxyType(credits)
        )
        object.__setattr__(self, "completed", tuple(self.completed))

    @property
    def outstanding(self) -> Mapping[int, ChiReadNoSnpMessage]:
        return MappingProxyType(
            {key: entry.current_request for key, entry in self.entries.items()}
        )


class ChiReadNoSnpRetryLedger(ChiReadNoSnpDirectLedger):
    """Retain, credit, and re-send a restricted ReadNoSnp transaction.

    RetryAck is correlated using the Requester-scoped transaction identity.
    PCrdGrant is pooled by PCrdType for the configured Home/Requester
    interface, so a Grant can arrive before its RetryAck and is not
    permanently assigned to one TxnID.
    """

    def __init__(self, name: str, profile: ChiReadNoSnpDirectProfile) -> None:
        super().__init__(name, profile)
        if profile.outstanding_capacity > 1024:
            raise ValueError(
                "retry profile supports at most 1024 outstanding requests"
            )
        retry_semantics = SemanticFragment(
            f"{name}.retry_semantics",
            constraints=(
                SemanticConstraint(
                    f"{name}.retry_pair",
                    "a request is re-sent only after RetryAck and a matching "
                    "Home/PCrdType protocol credit are both available",
                    ConstraintScope.INTERFACE,
                    kind=ConstraintKind.RELATION,
                ),
            ),
            resources=(
                ResourceDecl(
                    f"{name}.protocol_credit",
                    ConstraintScope.INTERFACE,
                    description=(
                        "transaction-independent P-Credits held by Requester"
                    ),
                    acquired_by=("PCrdGrant",),
                    released_by=("credited ReadNoSnp", "PCrdReturn"),
                ),
            ),
            sources=("Arm IHI 0050 Issue H B2.5.6 and B2.10",),
        )
        self.semantics = compose_fragments(
            f"{name}.retry_lifecycle", self.semantics, retry_semantics
        )

    def initial_state(self) -> ChiReadNoSnpRetryLedgerState:
        return ChiReadNoSnpRetryLedgerState({})

    def is_quiescent(self, state: ChiReadNoSnpRetryLedgerState) -> bool:
        return (
            isinstance(state, ChiReadNoSnpRetryLedgerState)
            and not state.entries
            and not state.protocol_credits
        )

    def retryable_keys(
        self, state: ChiReadNoSnpRetryLedgerState
    ) -> tuple[int, ...]:
        self._require_retry_state(state)
        return tuple(
            key
            for key, entry in state.entries.items()
            if entry.phase is ChiReadNoSnpRetryPhase.WAIT_RETRY_CREDIT
            and entry.protocol_credit_type is not None
            and state.protocol_credits.get(
                entry.protocol_credit_type, 0
            )
            > 0
        )

    def step(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        action: ChiReadNoSnpRetryAction,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        self._require_retry_state(state)
        if isinstance(action, ChiReadNoSnpIssue):
            return self._retry_issue(state, action.request)
        if isinstance(action, ChiReadNoSnpObserveRetryAck):
            return self._observe_retry_ack(state, action.response)
        if isinstance(action, ChiReadNoSnpObservePCrdGrant):
            return self._observe_pcredit(state, action.response)
        if isinstance(action, ChiReadNoSnpRetry):
            return self._retry_request(state, action.request_key)
        if isinstance(action, ChiReadNoSnpCancel):
            return self._cancel_request(state, action.request_key)
        if isinstance(action, ChiReadNoSnpComplete):
            return self._retry_complete(state, action.response)
        raise TypeError("unknown ReadNoSnp retry-ledger action")

    def _retry_issue(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        request: ChiReadNoSnpMessage,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        base = ChiReadNoSnpLedgerState(state.outstanding, state.completed)
        transition = super()._issue(base, request)
        failed = self._base_failure(state, transition)
        if failed is not None:
            return failed
        entries = dict(state.entries)
        entries[request.transaction_id] = ChiReadNoSnpRetryEntry(
            request,
            request,
            ChiReadNoSnpRetryPhase.INITIAL_IN_FLIGHT,
        )
        return SemanticStep(
            ChiReadNoSnpRetryLedgerState(
                entries, state.protocol_credits, state.completed
            )
        )

    def _observe_retry_ack(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        response: ChiRetryAckMessage,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        entry = state.entries.get(response.transaction_id)
        if entry is None:
            return self._retry_fault(
                state,
                "unknown_retry_ack",
                "RetryAck has no retained request identity",
            )
        if entry.phase is not ChiReadNoSnpRetryPhase.INITIAL_IN_FLIGHT:
            return self._retry_fault(
                state,
                "duplicate_retry_ack",
                "RetryAck is only valid for the initial in-flight request",
            )
        entries = dict(state.entries)
        entries[response.transaction_id] = replace(
            entry,
            phase=ChiReadNoSnpRetryPhase.WAIT_RETRY_CREDIT,
            protocol_credit_type=response.protocol_credit_type,
        )
        return SemanticStep(
            ChiReadNoSnpRetryLedgerState(
                entries, state.protocol_credits, state.completed
            )
        )

    def _observe_pcredit(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        response: ChiPCrdGrantMessage,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        key = response.protocol_credit_type
        credits = dict(state.protocol_credits)
        credits[key] = credits.get(key, 0) + 1
        return SemanticStep(
            ChiReadNoSnpRetryLedgerState(state.entries, credits, state.completed)
        )

    def _retry_request(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        request_key: int,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        entry = state.entries.get(request_key)
        if entry is None:
            return self._retry_fault(
                state, "unknown_retry", "retry action has no retained request"
            )
        if (
            entry.phase is not ChiReadNoSnpRetryPhase.WAIT_RETRY_CREDIT
            or entry.protocol_credit_type is None
        ):
            return self._retry_fault(
                state, "retry_phase", "request has not received RetryAck"
            )
        credit_key = entry.protocol_credit_type
        available = state.protocol_credits.get(credit_key, 0)
        if available == 0:
            return self._retry_fault(
                state,
                "missing_pcredit",
                "request has no matching P-Credit for retry",
            )
        retried = replace(
            entry.original_request,
            allow_retry=False,
            protocol_credit_type=entry.protocol_credit_type,
        )
        entries = dict(state.entries)
        entries[request_key] = replace(
            entry,
            current_request=retried,
            phase=ChiReadNoSnpRetryPhase.RETRIED_IN_FLIGHT,
        )
        credits = dict(state.protocol_credits)
        if available == 1:
            del credits[credit_key]
        else:
            credits[credit_key] = available - 1
        return SemanticStep(
            ChiReadNoSnpRetryLedgerState(entries, credits, state.completed),
            (retried,),
        )

    def _cancel_request(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        request_key: int,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        entry = state.entries.get(request_key)
        if entry is None:
            return self._retry_fault(
                state, "unknown_cancel", "cancel action has no retained request"
            )
        if (
            entry.phase is not ChiReadNoSnpRetryPhase.WAIT_RETRY_CREDIT
            or entry.protocol_credit_type is None
        ):
            return self._retry_fault(
                state,
                "cancel_phase",
                "a request can return P-Credit only after RetryAck",
            )
        credit_key = entry.protocol_credit_type
        available = state.protocol_credits.get(credit_key, 0)
        if available == 0:
            return self._retry_fault(
                state,
                "cancel_missing_pcredit",
                "canceled request has no matching P-Credit to return",
            )
        returned = ChiPCrdReturnMessage(
            protocol_credit_type=entry.protocol_credit_type,
        )
        entries = dict(state.entries)
        del entries[request_key]
        credits = dict(state.protocol_credits)
        if available == 1:
            del credits[credit_key]
        else:
            credits[credit_key] = available - 1
        return SemanticStep(
            ChiReadNoSnpRetryLedgerState(entries, credits, state.completed),
            (returned,),
        )

    def _retry_complete(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        response: ChiCompDataMessage,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        entry = state.entries.get(response.transaction_id)
        if entry is not None and (
            entry.phase is ChiReadNoSnpRetryPhase.WAIT_RETRY_CREDIT
        ):
            return self._retry_fault(
                state,
                "completion_before_retry",
                "CompData cannot complete a request after RetryAck but before retry",
            )
        base = ChiReadNoSnpLedgerState(state.outstanding, state.completed)
        transition = super()._complete(base, response)
        failed = self._base_failure(state, transition)
        if failed is not None:
            return failed
        entries = dict(state.entries)
        del entries[response.transaction_id]
        result = transition.emissions[0]
        return SemanticStep(
            ChiReadNoSnpRetryLedgerState(
                entries, state.protocol_credits, transition.state.completed
            ),
            (result,),
        )

    @staticmethod
    def _require_retry_state(state: ChiReadNoSnpRetryLedgerState) -> None:
        if not isinstance(state, ChiReadNoSnpRetryLedgerState):
            raise TypeError("retry ledger requires ChiReadNoSnpRetryLedgerState")

    @staticmethod
    def _base_failure(state, transition):
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        if transition.blocked is not None:
            return SemanticStep(state, blocked=transition.blocked)
        return None

    def _retry_fault(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
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
    "ChiReadNoSnpCancel",
    "ChiReadNoSnpObservePCrdGrant",
    "ChiReadNoSnpObserveRetryAck",
    "ChiReadNoSnpRetry",
    "ChiReadNoSnpRetryAction",
    "ChiReadNoSnpRetryEmission",
    "ChiReadNoSnpRetryEntry",
    "ChiReadNoSnpRetryLedger",
    "ChiReadNoSnpRetryLedgerState",
    "ChiReadNoSnpRetryPhase",
]
