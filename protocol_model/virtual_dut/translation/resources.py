"""Concrete translation capacity pools, leases, and analysis projection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics.model import ConstraintScope, ResourceDecl


class ResourceKind(str, Enum):
    PARENT = "parent"
    EXECUTION = "execution"
    BUFFER = "buffer"
    CORRELATION = "correlation"


class ResourceUnit(str, Enum):
    TRANSACTION = "transaction"
    CHILD = "child"
    ENTRY = "entry"
    BYTE = "byte"


@dataclass(frozen=True)
class CapacityPoolDecl:
    name: str
    kind: ResourceKind
    unit: ResourceUnit
    capacity: int
    description: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("capacity pool requires a name")
        if not isinstance(self.kind, ResourceKind):
            raise TypeError("capacity pool kind must be ResourceKind")
        if not isinstance(self.unit, ResourceUnit):
            raise TypeError("capacity pool unit must be ResourceUnit")
        if (
            not isinstance(self.capacity, int)
            or isinstance(self.capacity, bool)
            or self.capacity <= 0
        ):
            raise ValueError("capacity pool limit must be positive")

    def resource_decl(self) -> ResourceDecl:
        """Project the single capacity fact into system-visible metadata."""

        return ResourceDecl(
            self.name,
            ConstraintScope.VIRTUAL_DUT,
            self.capacity,
            self.description,
            acquired_by=(f"{self.name}.acquire",),
            released_by=(f"{self.name}.release",),
        )


@dataclass(frozen=True)
class CapacityLease:
    pool: str
    serial: int
    amount: int
    owner: object

    def __post_init__(self) -> None:
        if not isinstance(self.pool, str) or not self.pool:
            raise ValueError("capacity lease requires a pool name")
        if (
            not isinstance(self.serial, int)
            or isinstance(self.serial, bool)
            or self.serial < 0
        ):
            raise ValueError("capacity lease serial must be non-negative")
        if (
            not isinstance(self.amount, int)
            or isinstance(self.amount, bool)
            or self.amount <= 0
        ):
            raise ValueError("capacity lease amount must be positive")


@dataclass(frozen=True)
class CapacityPoolState:
    leases: Mapping[int, CapacityLease]
    next_serial: int = 0
    peak_usage: int = 0
    cumulative_acquisitions: int = 0
    cumulative_amount: int = 0

    def __post_init__(self) -> None:
        leases = dict(self.leases)
        if any(serial != lease.serial for serial, lease in leases.items()):
            raise ValueError("capacity state keys must match lease serials")
        if (
            not isinstance(self.next_serial, int)
            or isinstance(self.next_serial, bool)
            or self.next_serial < 0
        ):
            raise ValueError("next capacity lease serial must be non-negative")
        for name in (
            "peak_usage",
            "cumulative_acquisitions",
            "cumulative_amount",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"capacity {name} must be non-negative")
        usage = sum(lease.amount for lease in leases.values())
        if leases and self.next_serial <= max(leases):
            raise ValueError(
                "next capacity lease serial must exceed every live lease serial"
            )
        if self.cumulative_acquisitions < len(leases):
            raise ValueError(
                "capacity cumulative acquisitions cannot be below live leases"
            )
        if self.cumulative_amount < usage:
            raise ValueError(
                "capacity cumulative amount cannot be below live usage"
            )
        if usage > self.peak_usage:
            raise ValueError("capacity peak usage cannot be below live usage")
        if self.peak_usage > self.cumulative_amount:
            raise ValueError(
                "capacity peak usage cannot exceed cumulative acquired amount"
            )
        object.__setattr__(self, "leases", MappingProxyType(leases))

    @property
    def usage(self) -> int:
        return sum(lease.amount for lease in self.leases.values())


class CapacityFailureKind(str, Enum):
    FULL = "full"
    UNKNOWN_LEASE = "unknown_lease"
    OWNER_MISMATCH = "owner_mismatch"
    POOL_MISMATCH = "pool_mismatch"


@dataclass(frozen=True)
class CapacityFailure:
    kind: CapacityFailureKind
    pool: str
    usage: int
    limit: int
    owner: object
    reason: str
    lease_serial: int | None = None


@dataclass(frozen=True)
class CapacityAcquireResult:
    state: CapacityPoolState
    lease: CapacityLease | None = None
    failure: CapacityFailure | None = None

    @property
    def ok(self) -> bool:
        return self.lease is not None and self.failure is None


@dataclass(frozen=True)
class CapacityReleaseResult:
    state: CapacityPoolState
    failure: CapacityFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None


class CapacityPool:
    """Immutable-state acquire/release operations for one declared pool."""

    def __init__(self, declaration: CapacityPoolDecl) -> None:
        if not isinstance(declaration, CapacityPoolDecl):
            raise TypeError("capacity pool requires a declaration")
        self.declaration = declaration

    def initial_state(self) -> CapacityPoolState:
        return CapacityPoolState({}, peak_usage=0)

    def acquire(
        self,
        state: CapacityPoolState,
        owner: object,
        *,
        amount: int = 1,
    ) -> CapacityAcquireResult:
        self.validate_state(state)
        if (
            not isinstance(amount, int)
            or isinstance(amount, bool)
            or amount <= 0
        ):
            raise ValueError("capacity acquisition amount must be positive")
        if state.usage + amount > self.declaration.capacity:
            return CapacityAcquireResult(
                state,
                failure=CapacityFailure(
                    CapacityFailureKind.FULL,
                    self.declaration.name,
                    state.usage,
                    self.declaration.capacity,
                    owner,
                    "capacity pool cannot satisfy the requested lease",
                ),
            )
        lease = CapacityLease(
            self.declaration.name,
            state.next_serial,
            amount,
            owner,
        )
        leases = dict(state.leases)
        leases[lease.serial] = lease
        usage = state.usage + amount
        return CapacityAcquireResult(
            CapacityPoolState(
                leases,
                state.next_serial + 1,
                max(state.peak_usage, usage),
                state.cumulative_acquisitions + 1,
                state.cumulative_amount + amount,
            ),
            lease=lease,
        )

    def release(
        self,
        state: CapacityPoolState,
        lease: CapacityLease,
        *,
        owner: object,
    ) -> CapacityReleaseResult:
        self.validate_state(state)
        if not isinstance(lease, CapacityLease):
            raise TypeError("capacity release requires a lease")
        if lease.pool != self.declaration.name:
            return self._release_failure(
                state,
                CapacityFailureKind.POOL_MISMATCH,
                owner,
                "lease belongs to another capacity pool",
                lease.serial,
            )
        current = state.leases.get(lease.serial)
        if current is None or current != lease:
            return self._release_failure(
                state,
                CapacityFailureKind.UNKNOWN_LEASE,
                owner,
                "capacity lease is not active",
                lease.serial,
            )
        if current.owner != owner:
            return self._release_failure(
                state,
                CapacityFailureKind.OWNER_MISMATCH,
                owner,
                "capacity lease is owned by another token",
                lease.serial,
            )
        leases = dict(state.leases)
        del leases[lease.serial]
        return CapacityReleaseResult(
            CapacityPoolState(
                leases,
                state.next_serial,
                state.peak_usage,
                state.cumulative_acquisitions,
                state.cumulative_amount,
            )
        )

    def _release_failure(
        self,
        state: CapacityPoolState,
        kind: CapacityFailureKind,
        owner: object,
        reason: str,
        lease_serial: int,
    ) -> CapacityReleaseResult:
        return CapacityReleaseResult(
            state,
            CapacityFailure(
                kind,
                self.declaration.name,
                state.usage,
                self.declaration.capacity,
                owner,
                reason,
                lease_serial,
            ),
        )

    def validate_state(self, state: CapacityPoolState) -> None:
        if not isinstance(state, CapacityPoolState):
            raise TypeError("capacity pool requires CapacityPoolState")
        if any(
            lease.pool != self.declaration.name
            for lease in state.leases.values()
        ):
            raise ValueError("capacity state contains a lease from another pool")
        if state.usage > self.declaration.capacity:
            raise ValueError("capacity state exceeds the declared limit")
