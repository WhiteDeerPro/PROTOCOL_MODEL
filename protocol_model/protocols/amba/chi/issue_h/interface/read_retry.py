"""Requester-side lifecycle for the first ReadNoSnp Request-Retry slice."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
from .request_retry import (
    ChiRequestRetryContract,
    ChiRequestRetryContractError,
    ChiRequestRetryEntry,
    ChiRequestRetryPhase,
    ChiRequestRetryRequesterState,
)


ChiReadNoSnpRetryPhase = ChiRequestRetryPhase


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
        return self._contract_state(state).retryable_transaction_ids(
            home_node_id=self.profile.home_node_id
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
        try:
            contract = ChiRequestRetryContract.retain_initial(
                self._contract_state(state),
                request,
                home_node_id=self.profile.home_node_id,
            )
        except ChiRequestRetryContractError as error:
            return self._contract_fault(state, error)
        return SemanticStep(
            self._project_contract(contract, state.completed)
        )

    def _observe_retry_ack(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        response: ChiRetryAckMessage,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        try:
            contract = ChiRequestRetryContract.observe_retry_ack(
                self._contract_state(state),
                response,
                home_node_id=self.profile.home_node_id,
            )
        except ChiRequestRetryContractError as error:
            return self._contract_fault(state, error)
        return SemanticStep(
            self._project_contract(contract, state.completed)
        )

    def _observe_pcredit(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        response: ChiPCrdGrantMessage,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        contract = ChiRequestRetryContract.observe_pcredit(
            self._contract_state(state),
            response,
            home_node_id=self.profile.home_node_id,
        )
        return SemanticStep(
            self._project_contract(contract, state.completed)
        )

    def _retry_request(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        request_key: int,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        try:
            contract, retried = ChiRequestRetryContract.credited_reissue(
                self._contract_state(state),
                request_key,
            )
        except ChiRequestRetryContractError as error:
            return self._contract_fault(state, error)
        return SemanticStep(
            self._project_contract(contract, state.completed),
            (retried,),
        )

    def _cancel_request(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        request_key: int,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        try:
            contract, returned = ChiRequestRetryContract.cancel(
                self._contract_state(state),
                request_key,
            )
        except ChiRequestRetryContractError as error:
            return self._contract_fault(state, error)
        return SemanticStep(
            self._project_contract(contract, state.completed),
            (returned,),
        )

    def _retry_complete(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        response: ChiCompDataMessage,
    ) -> SemanticStep[ChiReadNoSnpRetryLedgerState, ChiReadNoSnpRetryEmission]:
        try:
            contract = ChiRequestRetryContract.retire(
                self._contract_state(state),
                response.transaction_id,
            )
        except ChiRequestRetryContractError as error:
            return self._contract_fault(state, error)
        base = ChiReadNoSnpLedgerState(state.outstanding, state.completed)
        transition = super()._complete(base, response)
        failed = self._base_failure(state, transition)
        if failed is not None:
            return failed
        result = transition.emissions[0]
        return SemanticStep(
            self._project_contract(
                contract,
                transition.state.completed,
            ),
            (result,),
        )

    def _contract_state(
        self,
        state: ChiReadNoSnpRetryLedgerState,
    ) -> ChiRequestRetryRequesterState[ChiReadNoSnpMessage]:
        return ChiRequestRetryRequesterState(
            {
                transaction_id: ChiRequestRetryEntry(
                    entry.original_request,
                    entry.current_request,
                    self.profile.home_node_id,
                    entry.phase,
                    entry.protocol_credit_type,
                )
                for transaction_id, entry in state.entries.items()
            },
            {
                (self.profile.home_node_id, credit_type): count
                for credit_type, count in state.protocol_credits.items()
            },
        )

    def _project_contract(
        self,
        contract: ChiRequestRetryRequesterState[ChiReadNoSnpMessage],
        completed: tuple[ChiReadNoSnpResult, ...],
    ) -> ChiReadNoSnpRetryLedgerState:
        if any(
            home_node_id != self.profile.home_node_id
            for home_node_id, _credit_type in contract.protocol_credits
        ) or any(
            entry.home_node_id != self.profile.home_node_id
            for entry in contract.entries.values()
        ):
            raise ValueError(
                "direct ReadNoSnp facade received another Home identity"
            )
        return ChiReadNoSnpRetryLedgerState(
            {
                transaction_id: ChiReadNoSnpRetryEntry(
                    entry.original_request,
                    entry.current_request,
                    entry.phase,
                    entry.protocol_credit_type,
                )
                for transaction_id, entry in contract.entries.items()
            },
            {
                credit_type: count
                for (_home_node_id, credit_type), count
                in contract.protocol_credits.items()
            },
            completed,
        )

    def _contract_fault(
        self,
        state: ChiReadNoSnpRetryLedgerState,
        error: ChiRequestRetryContractError,
    ) -> SemanticStep[
        ChiReadNoSnpRetryLedgerState,
        ChiReadNoSnpRetryEmission,
    ]:
        return self._retry_fault(state, error.code, error.reason)

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
