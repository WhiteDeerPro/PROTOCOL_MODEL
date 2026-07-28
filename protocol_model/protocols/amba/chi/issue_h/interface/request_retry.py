"""Issue-H Request-Retry and P-Credit transaction contracts.

This module owns the protocol-local correlation and credit conservation shared
by opcode-specific requester and Home participants.  It deliberately knows
nothing about cache state, directory state, backing storage, packets, routes,
or scheduler policy.  Home P-Credits are pooled by ``(Requester, PCrdType)``:
after a grant, the Home state intentionally does not bind that reservation to
one TxnID.  Exact delivered-request generation and replay checks therefore
belong to a composition that can also see Requester retained state and packet
provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import Generic, Mapping, TypeVar

from ..representation import (
    ChiPCrdGrantMessage,
    ChiPCrdReturnMessage,
    ChiRetryAckMessage,
)


_RequestT = TypeVar("_RequestT")


def _require_node_id(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative NodeID")


def _require_transaction_id(value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < (1 << 12)
    ):
        raise ValueError("transaction_id must be a 12-bit integer")


def _require_credit_type(value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < 16
    ):
        raise ValueError("protocol_credit_type must be in 0..15")


class ChiRequestRetryContractError(ValueError):
    """Typed rejection from a pure Request-Retry contract operation."""

    def __init__(self, code: str, reason: str) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("Request-Retry error requires a code")
        if not isinstance(reason, str) or not reason:
            raise ValueError("Request-Retry error requires a reason")
        self.code = code
        self.reason = reason
        super().__init__(reason)


class ChiRequestRetryPhase(str, Enum):
    """Requester knowledge about one retained request."""

    INITIAL_IN_FLIGHT = "initial_in_flight"
    WAIT_RETRY_CREDIT = "wait_retry_credit"
    RETRIED_IN_FLIGHT = "retried_in_flight"


@dataclass(frozen=True)
class ChiRequestRetryEntry(Generic[_RequestT]):
    """One retained request and its current transmitted form."""

    original_request: _RequestT
    current_request: _RequestT
    home_node_id: int
    phase: ChiRequestRetryPhase = ChiRequestRetryPhase.INITIAL_IN_FLIGHT
    protocol_credit_type: int | None = None

    def __post_init__(self) -> None:
        _require_node_id("retry Home", self.home_node_id)
        try:
            original_id = self.original_request.transaction_id  # type: ignore[attr-defined]
            current_id = self.current_request.transaction_id  # type: ignore[attr-defined]
            original_allow_retry = self.original_request.allow_retry  # type: ignore[attr-defined]
            original_credit_type = self.original_request.protocol_credit_type  # type: ignore[attr-defined]
        except AttributeError as error:
            raise TypeError(
                "retry entry requests require TxnID, AllowRetry, and PCrdType"
            ) from error
        _require_transaction_id(original_id)
        if current_id != original_id:
            raise ValueError("retry entry keeps one requester transaction identity")
        if type(original_allow_retry) is not bool:
            raise TypeError("request AllowRetry must be bool")
        _require_credit_type(original_credit_type)
        phase = ChiRequestRetryPhase(self.phase)
        credit_type = self.protocol_credit_type
        if credit_type is not None:
            _require_credit_type(credit_type)
        if phase is ChiRequestRetryPhase.INITIAL_IN_FLIGHT:
            if (
                self.current_request != self.original_request
                or not original_allow_retry
                or original_credit_type != 0
                or credit_type is not None
            ):
                raise ValueError(
                    "initial retry entry requires the original retryable request"
                )
        elif phase is ChiRequestRetryPhase.WAIT_RETRY_CREDIT:
            if (
                self.current_request != self.original_request
                or credit_type is None
            ):
                raise ValueError(
                    "RetryAck phase requires the original request and PCrdType"
                )
        elif (
            credit_type is None
            or self.current_request
            != replace(
                self.original_request,
                allow_retry=False,
                protocol_credit_type=credit_type,
            )
        ):
            raise ValueError(
                "retried entry requires the credited form of the original request"
            )
        object.__setattr__(self, "phase", phase)

    @property
    def transaction_id(self) -> int:
        return self.original_request.transaction_id  # type: ignore[attr-defined]


@dataclass(frozen=True)
class ChiRequestRetryRequesterState(Generic[_RequestT]):
    """Retained requests and credits keyed by ``(HomeNID, PCrdType)``."""

    entries: Mapping[int, ChiRequestRetryEntry[_RequestT]] = field(
        default_factory=dict
    )
    protocol_credits: Mapping[tuple[int, int], int] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        entries = dict(self.entries)
        if any(
            not isinstance(entry, ChiRequestRetryEntry)
            or transaction_id != entry.transaction_id
            for transaction_id, entry in entries.items()
        ):
            raise ValueError(
                "requester retry entries disagree with their transaction keys"
            )
        credits = dict(self.protocol_credits)
        for key, count in credits.items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError(
                    "requester P-Credit key must be (HomeNID, PCrdType)"
                )
            _require_node_id("P-Credit Home", key[0])
            _require_credit_type(key[1])
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
            ):
                raise ValueError("requester P-Credit count must be positive")
        object.__setattr__(self, "entries", MappingProxyType(entries))
        object.__setattr__(
            self,
            "protocol_credits",
            MappingProxyType(credits),
        )

    def retryable_transaction_ids(
        self,
        *,
        home_node_id: int | None = None,
    ) -> tuple[int, ...]:
        if home_node_id is not None:
            _require_node_id("retry Home", home_node_id)
        return tuple(
            transaction_id
            for transaction_id, entry in self.entries.items()
            if (
                entry.phase is ChiRequestRetryPhase.WAIT_RETRY_CREDIT
                and entry.protocol_credit_type is not None
                and (
                    home_node_id is None
                    or entry.home_node_id == home_node_id
                )
                and self.protocol_credits.get(
                    (entry.home_node_id, entry.protocol_credit_type),
                    0,
                )
                > 0
            )
        )

    @property
    def credit_count(self) -> int:
        return sum(self.protocol_credits.values())


@dataclass(frozen=True)
class ChiRetryDebt:
    """One RetryAck for which a Home still owes a matching P-Credit."""

    requester_id: int
    transaction_id: int
    protocol_credit_type: int

    def __post_init__(self) -> None:
        _require_node_id("retry requester", self.requester_id)
        _require_transaction_id(self.transaction_id)
        _require_credit_type(self.protocol_credit_type)

    @property
    def request_key(self) -> tuple[int, int]:
        return self.requester_id, self.transaction_id

    @property
    def credit_key(self) -> tuple[int, int]:
        return self.requester_id, self.protocol_credit_type


@dataclass(frozen=True)
class ChiRequestRetryHomeState:
    """Home obligations, reservations, and conservation counters."""

    retry_debts: tuple[ChiRetryDebt, ...] = ()
    reservations: Mapping[tuple[int, int], int] = field(default_factory=dict)
    retry_ack_count: int = 0
    grant_count: int = 0
    consumed_count: int = 0
    returned_count: int = 0

    def __post_init__(self) -> None:
        debts = tuple(self.retry_debts)
        if any(not isinstance(item, ChiRetryDebt) for item in debts):
            raise TypeError("Home retry debts require ChiRetryDebt values")
        debt_keys = tuple(item.request_key for item in debts)
        if len(set(debt_keys)) != len(debt_keys):
            raise ValueError("Home retry debts contain a duplicate request")
        reservations = dict(self.reservations)
        for key, count in reservations.items():
            if not isinstance(key, tuple) or len(key) != 2:
                raise ValueError(
                    "Home reservation key must be (RequesterNID, PCrdType)"
                )
            _require_node_id("reservation requester", key[0])
            _require_credit_type(key[1])
            if (
                not isinstance(count, int)
                or isinstance(count, bool)
                or count <= 0
            ):
                raise ValueError("Home reservation count must be positive")
        for name, value in (
            ("retry_ack_count", self.retry_ack_count),
            ("grant_count", self.grant_count),
            ("consumed_count", self.consumed_count),
            ("returned_count", self.returned_count),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer")
        if self.retry_ack_count != self.grant_count + len(debts):
            raise ValueError(
                "RetryAck count must equal grants plus outstanding debts"
            )
        if self.grant_count != (
            self.consumed_count
            + self.returned_count
            + sum(reservations.values())
        ):
            raise ValueError(
                "P-Credit grants must equal consumed, returned, and reserved"
            )
        object.__setattr__(self, "retry_debts", debts)
        object.__setattr__(
            self,
            "reservations",
            MappingProxyType(reservations),
        )

    @property
    def reserved_count(self) -> int:
        return sum(self.reservations.values())


class ChiRequestRetryContract:
    """Pure operations over the shared Request-Retry value states."""

    @staticmethod
    def retain_initial(
        state: ChiRequestRetryRequesterState[_RequestT],
        request: _RequestT,
        *,
        home_node_id: int,
    ) -> ChiRequestRetryRequesterState[_RequestT]:
        _require_node_id("retry Home", home_node_id)
        try:
            transaction_id = request.transaction_id  # type: ignore[attr-defined]
            allow_retry = request.allow_retry  # type: ignore[attr-defined]
            credit_type = request.protocol_credit_type  # type: ignore[attr-defined]
        except AttributeError as error:
            raise TypeError(
                "retained request requires TxnID, AllowRetry, and PCrdType"
            ) from error
        _require_transaction_id(transaction_id)
        if not allow_retry or credit_type != 0:
            raise ChiRequestRetryContractError(
                "initial_request",
                "initial request requires AllowRetry=1 and PCrdType=0",
            )
        if transaction_id in state.entries:
            raise ChiRequestRetryContractError(
                "duplicate_request",
                "requester already retains this retry transaction",
            )
        entries = dict(state.entries)
        entries[transaction_id] = ChiRequestRetryEntry(
            request,
            request,
            home_node_id,
        )
        return ChiRequestRetryRequesterState(
            entries,
            state.protocol_credits,
        )

    @staticmethod
    def observe_retry_ack(
        state: ChiRequestRetryRequesterState[_RequestT],
        response: ChiRetryAckMessage,
        *,
        home_node_id: int,
    ) -> ChiRequestRetryRequesterState[_RequestT]:
        if not isinstance(response, ChiRetryAckMessage):
            raise TypeError("RetryAck observation requires ChiRetryAckMessage")
        entry = state.entries.get(response.transaction_id)
        if entry is None or entry.home_node_id != home_node_id:
            raise ChiRequestRetryContractError(
                "unknown_retry_ack",
                "RetryAck has no retained request for this Home",
            )
        if entry.phase is not ChiRequestRetryPhase.INITIAL_IN_FLIGHT:
            raise ChiRequestRetryContractError(
                "duplicate_retry_ack",
                "RetryAck is valid only for an initial in-flight request",
            )
        entries = dict(state.entries)
        entries[response.transaction_id] = replace(
            entry,
            phase=ChiRequestRetryPhase.WAIT_RETRY_CREDIT,
            protocol_credit_type=response.protocol_credit_type,
        )
        return ChiRequestRetryRequesterState(
            entries,
            state.protocol_credits,
        )

    @staticmethod
    def observe_pcredit(
        state: ChiRequestRetryRequesterState[_RequestT],
        response: ChiPCrdGrantMessage,
        *,
        home_node_id: int,
    ) -> ChiRequestRetryRequesterState[_RequestT]:
        if not isinstance(response, ChiPCrdGrantMessage):
            raise TypeError("P-Credit observation requires ChiPCrdGrantMessage")
        _require_node_id("P-Credit Home", home_node_id)
        credits = dict(state.protocol_credits)
        key = home_node_id, response.protocol_credit_type
        credits[key] = credits.get(key, 0) + 1
        return ChiRequestRetryRequesterState(state.entries, credits)

    @staticmethod
    def credited_reissue(
        state: ChiRequestRetryRequesterState[_RequestT],
        transaction_id: int,
    ) -> tuple[ChiRequestRetryRequesterState[_RequestT], _RequestT]:
        _require_transaction_id(transaction_id)
        entry = state.entries.get(transaction_id)
        if entry is None:
            raise ChiRequestRetryContractError(
                "unknown_retry",
                "retry action has no retained request",
            )
        if (
            entry.phase is not ChiRequestRetryPhase.WAIT_RETRY_CREDIT
            or entry.protocol_credit_type is None
        ):
            raise ChiRequestRetryContractError(
                "retry_phase",
                "request has not received RetryAck",
            )
        credit_key = entry.home_node_id, entry.protocol_credit_type
        available = state.protocol_credits.get(credit_key, 0)
        if available == 0:
            raise ChiRequestRetryContractError(
                "missing_pcredit",
                "request has no matching P-Credit",
            )
        retried = replace(
            entry.original_request,
            allow_retry=False,
            protocol_credit_type=entry.protocol_credit_type,
        )
        entries = dict(state.entries)
        entries[transaction_id] = replace(
            entry,
            current_request=retried,
            phase=ChiRequestRetryPhase.RETRIED_IN_FLIGHT,
        )
        credits = dict(state.protocol_credits)
        if available == 1:
            del credits[credit_key]
        else:
            credits[credit_key] = available - 1
        return ChiRequestRetryRequesterState(entries, credits), retried

    @staticmethod
    def retire(
        state: ChiRequestRetryRequesterState[_RequestT],
        transaction_id: int,
    ) -> ChiRequestRetryRequesterState[_RequestT]:
        _require_transaction_id(transaction_id)
        entry = state.entries.get(transaction_id)
        if entry is None:
            raise ChiRequestRetryContractError(
                "unknown_completion",
                "completion has no retained retry request",
            )
        if entry.phase is ChiRequestRetryPhase.WAIT_RETRY_CREDIT:
            raise ChiRequestRetryContractError(
                "completion_before_retry",
                "completion cannot follow RetryAck before credited reissue",
            )
        entries = dict(state.entries)
        del entries[transaction_id]
        return ChiRequestRetryRequesterState(
            entries,
            state.protocol_credits,
        )

    @staticmethod
    def cancel(
        state: ChiRequestRetryRequesterState[_RequestT],
        transaction_id: int,
    ) -> tuple[
        ChiRequestRetryRequesterState[_RequestT],
        ChiPCrdReturnMessage,
    ]:
        """Cancel one acknowledged request and return its matching credit."""

        _require_transaction_id(transaction_id)
        entry = state.entries.get(transaction_id)
        if entry is None:
            raise ChiRequestRetryContractError(
                "unknown_cancel",
                "cancel action has no retained request",
            )
        if (
            entry.phase is not ChiRequestRetryPhase.WAIT_RETRY_CREDIT
            or entry.protocol_credit_type is None
        ):
            raise ChiRequestRetryContractError(
                "cancel_phase",
                "request can return P-Credit only after RetryAck",
            )
        credit_key = entry.home_node_id, entry.protocol_credit_type
        available = state.protocol_credits.get(credit_key, 0)
        if available == 0:
            raise ChiRequestRetryContractError(
                "cancel_missing_pcredit",
                "canceled request has no matching P-Credit to return",
            )
        entries = dict(state.entries)
        del entries[transaction_id]
        credits = dict(state.protocol_credits)
        if available == 1:
            del credits[credit_key]
        else:
            credits[credit_key] = available - 1
        return (
            ChiRequestRetryRequesterState(entries, credits),
            ChiPCrdReturnMessage(
                protocol_credit_type=entry.protocol_credit_type,
            ),
        )

    @staticmethod
    def record_retry(
        state: ChiRequestRetryHomeState,
        *,
        requester_id: int,
        transaction_id: int,
        protocol_credit_type: int,
    ) -> tuple[ChiRequestRetryHomeState, ChiRetryAckMessage]:
        debt = ChiRetryDebt(
            requester_id,
            transaction_id,
            protocol_credit_type,
        )
        if any(item.request_key == debt.request_key for item in state.retry_debts):
            raise ChiRequestRetryContractError(
                "duplicate_retry_debt",
                "Home already owes a P-Credit for this requester transaction",
            )
        candidate = ChiRequestRetryHomeState(
            state.retry_debts + (debt,),
            state.reservations,
            state.retry_ack_count + 1,
            state.grant_count,
            state.consumed_count,
            state.returned_count,
        )
        return candidate, ChiRetryAckMessage(
            transaction_id=transaction_id,
            protocol_credit_type=protocol_credit_type,
        )

    @staticmethod
    def grant_oldest(
        state: ChiRequestRetryHomeState,
    ) -> tuple[
        ChiRequestRetryHomeState,
        ChiRetryDebt,
        ChiPCrdGrantMessage,
    ]:
        if not state.retry_debts:
            raise ChiRequestRetryContractError(
                "missing_retry_debt",
                "Home has no RetryAck awaiting P-Credit",
            )
        debt = state.retry_debts[0]
        reservations = dict(state.reservations)
        reservations[debt.credit_key] = (
            reservations.get(debt.credit_key, 0) + 1
        )
        candidate = ChiRequestRetryHomeState(
            state.retry_debts[1:],
            reservations,
            state.retry_ack_count,
            state.grant_count + 1,
            state.consumed_count,
            state.returned_count,
        )
        return candidate, debt, ChiPCrdGrantMessage(
            protocol_credit_type=debt.protocol_credit_type,
        )

    @staticmethod
    def consume_reservation(
        state: ChiRequestRetryHomeState,
        *,
        requester_id: int,
        protocol_credit_type: int,
    ) -> ChiRequestRetryHomeState:
        key = requester_id, protocol_credit_type
        available = state.reservations.get(key, 0)
        if available == 0:
            raise ChiRequestRetryContractError(
                "missing_reservation",
                "credited request has no matching Home reservation",
            )
        reservations = dict(state.reservations)
        if available == 1:
            del reservations[key]
        else:
            reservations[key] = available - 1
        return ChiRequestRetryHomeState(
            state.retry_debts,
            reservations,
            state.retry_ack_count,
            state.grant_count,
            state.consumed_count + 1,
            state.returned_count,
        )

    @staticmethod
    def return_reservation(
        state: ChiRequestRetryHomeState,
        request: ChiPCrdReturnMessage,
        *,
        requester_id: int,
    ) -> ChiRequestRetryHomeState:
        if not isinstance(request, ChiPCrdReturnMessage):
            raise TypeError("P-Credit return requires ChiPCrdReturnMessage")
        key = requester_id, request.protocol_credit_type
        available = state.reservations.get(key, 0)
        if available == 0:
            raise ChiRequestRetryContractError(
                "pcredit_return_reservation",
                "PCrdReturn has no matching Home reservation",
            )
        reservations = dict(state.reservations)
        if available == 1:
            del reservations[key]
        else:
            reservations[key] = available - 1
        return ChiRequestRetryHomeState(
            state.retry_debts,
            reservations,
            state.retry_ack_count,
            state.grant_count,
            state.consumed_count,
            state.returned_count + 1,
        )


__all__ = [
    "ChiRequestRetryContract",
    "ChiRequestRetryContractError",
    "ChiRequestRetryEntry",
    "ChiRequestRetryHomeState",
    "ChiRequestRetryPhase",
    "ChiRequestRetryRequesterState",
    "ChiRetryDebt",
]
