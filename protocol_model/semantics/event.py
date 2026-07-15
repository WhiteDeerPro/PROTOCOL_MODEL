"""Canonical events and executable field domains."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from random import Random
from types import MappingProxyType
from typing import Callable, Generic, Hashable, Mapping, TypeVar


ValueT = TypeVar("ValueT")


@dataclass(frozen=True)
class CanonicalEvent:
    kind: str
    key: Hashable = None
    payload: Mapping[str, object] = field(default_factory=dict)
    source: str = "model"
    clock: str | None = None
    timestamp: int | float | None = None
    sequence: int | None = None
    trace_index: int | None = None

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("canonical event requires a kind")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @property
    def semantic_identity(self) -> tuple[object, ...]:
        return self.kind, self.key, tuple(sorted(self.payload.items()))

    def short(self) -> str:
        fields = ", ".join(
            f"{name}={value!r}" for name, value in self.payload.items()
        )
        suffix = f", {fields}" if fields else ""
        return f"{self.kind}(key={self.key!r}{suffix})"


class ValueDomain(ABC, Generic[ValueT]):
    @abstractmethod
    def sample(self, rng: Random) -> ValueT:
        raise NotImplementedError

    @abstractmethod
    def contains(self, value: object) -> bool:
        raise NotImplementedError

    def explain(self, value: object) -> str | None:
        return None if self.contains(value) else f"{value!r} is outside {self!r}"


@dataclass(frozen=True)
class IntDomain(ValueDomain[int]):
    minimum: int
    maximum: int
    alignment: int = 1

    def __post_init__(self) -> None:
        if self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        if self.alignment <= 0:
            raise ValueError("alignment must be positive")
        first = ((self.minimum + self.alignment - 1) // self.alignment) * self.alignment
        if first > self.maximum:
            raise ValueError("domain contains no aligned integer")

    def sample(self, rng: Random) -> int:
        first = ((self.minimum + self.alignment - 1) // self.alignment) * self.alignment
        count = (self.maximum - first) // self.alignment + 1
        return first + rng.randrange(count) * self.alignment

    def contains(self, value: object) -> bool:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and self.minimum <= value <= self.maximum
            and value % self.alignment == 0
        )

    def explain(self, value: object) -> str | None:
        if not isinstance(value, int) or isinstance(value, bool):
            return f"expected integer, got {value!r}"
        if not self.minimum <= value <= self.maximum:
            return f"{value} is outside [{self.minimum}, {self.maximum}]"
        if value % self.alignment:
            return f"{value} is not aligned to {self.alignment}"
        return None


@dataclass(frozen=True)
class NaturalDomain(ValueDomain[int]):
    sample_maximum: int = 16

    def __post_init__(self) -> None:
        if self.sample_maximum < 0:
            raise ValueError("sample maximum must be non-negative")

    def sample(self, rng: Random) -> int:
        return rng.randint(0, self.sample_maximum)

    def contains(self, value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class BitVectorDomain(IntDomain):
    width: int = 1

    def __init__(self, width: int):
        if width <= 0:
            raise ValueError("bit-vector width must be positive")
        object.__setattr__(self, "width", width)
        object.__setattr__(self, "minimum", 0)
        object.__setattr__(self, "maximum", (1 << width) - 1)
        object.__setattr__(self, "alignment", 1)


@dataclass(frozen=True)
class EnumDomain(ValueDomain[ValueT]):
    values: tuple[ValueT, ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("enum domain cannot be empty")
        if len(set(self.values)) != len(self.values):
            raise ValueError("enum domain values must be unique")

    def sample(self, rng: Random) -> ValueT:
        return rng.choice(self.values)

    def contains(self, value: object) -> bool:
        return value in self.values


@dataclass(frozen=True)
class ConstantDomain(ValueDomain[ValueT]):
    value: ValueT

    def sample(self, rng: Random) -> ValueT:
        return self.value

    def contains(self, value: object) -> bool:
        return value == self.value


@dataclass(frozen=True)
class EventConstraint:
    name: str
    predicate: Callable[[CanonicalEvent], bool]
    reason: str

    def __post_init__(self) -> None:
        if not self.name or not self.reason:
            raise ValueError("event constraint requires name and reason")
