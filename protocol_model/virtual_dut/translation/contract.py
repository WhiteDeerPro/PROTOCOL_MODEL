"""Construction-time capability, effect, and bridge profile contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .signature import OperationSignature


_MISSING = object()


@dataclass(frozen=True)
class CapabilityGap:
    name: str
    expected: object
    observed: object | None
    observed_present: bool

    def describe(self) -> str:
        if not self.observed_present:
            return f"{self.name!r} requires {self.expected!r}, but is absent"
        return (
            f"{self.name!r} requires {self.expected!r}, "
            f"got {self.observed!r}"
        )


@dataclass(frozen=True)
class CapabilitySet:
    """A small exact-match capability algebra for V1 plan closure.

    Capability values should be immutable descriptive values.  Range or
    implication semantics are represented by an explicit stage in V1 rather
    than hidden inside comparison callbacks.
    """

    values: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        copied = dict(self.values)
        if any(not isinstance(name, str) or not name for name in copied):
            raise ValueError("capability names must be non-empty strings")
        object.__setattr__(self, "values", MappingProxyType(copied))

    @classmethod
    def of(cls, **values: object) -> "CapabilitySet":
        return cls(values)

    def missing(self, required: "CapabilitySet") -> tuple[CapabilityGap, ...]:
        gaps = []
        for name, expected in required.values.items():
            observed = self.values.get(name, _MISSING)
            if observed is _MISSING:
                gaps.append(CapabilityGap(name, expected, None, False))
            elif observed != expected:
                gaps.append(CapabilityGap(name, expected, observed, True))
        return tuple(gaps)

    def without(self, names: frozenset[str]) -> "CapabilitySet":
        return CapabilitySet(
            {name: value for name, value in self.values.items() if name not in names}
        )

    def updated(self, additions: "CapabilitySet") -> "CapabilitySet":
        values = dict(self.values)
        values.update(additions.values)
        return CapabilitySet(values)


@dataclass(frozen=True)
class CapabilityProjectionResult:
    capabilities: CapabilitySet | None
    gaps: tuple[CapabilityGap, ...] = ()

    @property
    def ok(self) -> bool:
        return self.capabilities is not None and not self.gaps


@dataclass(frozen=True)
class CapabilityProjection:
    """One directional requires/remove/provide transformation."""

    requires: CapabilitySet = field(default_factory=CapabilitySet)
    removes: frozenset[str] = frozenset()
    provides: CapabilitySet = field(default_factory=CapabilitySet)

    def __post_init__(self) -> None:
        if any(not isinstance(name, str) or not name for name in self.removes):
            raise ValueError("removed capability names must be non-empty strings")

    def apply(self, offered: CapabilitySet) -> CapabilityProjectionResult:
        if not isinstance(offered, CapabilitySet):
            raise TypeError("capability projection requires a CapabilitySet")
        gaps = offered.missing(self.requires)
        if gaps:
            return CapabilityProjectionResult(None, gaps)
        retained = offered.without(self.removes)
        conflicts = tuple(
            CapabilityGap(name, value, retained.values[name], True)
            for name, value in self.provides.values.items()
            if name in retained.values and retained.values[name] != value
        )
        if conflicts:
            return CapabilityProjectionResult(None, conflicts)
        return CapabilityProjectionResult(retained.updated(self.provides))


@dataclass(frozen=True)
class CapabilityRelation:
    """Request projection forward and completion projection backward."""

    request: CapabilityProjection = field(default_factory=CapabilityProjection)
    completion: CapabilityProjection = field(
        default_factory=CapabilityProjection
    )


class SemanticEffectKind(str, Enum):
    PRESERVE = "preserve"
    RECOMPUTE = "recompute"
    SPLIT = "split"
    AGGREGATE = "aggregate"
    REBIND = "rebind"
    SYNTHESIZE = "synthesize"
    DEFAULT = "default"
    WEAKEN = "weaken"
    DROP = "drop"
    REJECT = "reject"


@dataclass(frozen=True)
class SemanticEffect:
    property_name: str
    kind: SemanticEffectKind
    detail: str = ""
    rule: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.property_name, str) or not self.property_name:
            raise ValueError("semantic effect requires a property name")
        if not isinstance(self.kind, SemanticEffectKind):
            raise TypeError("semantic effect kind must be SemanticEffectKind")


class CompletionOrigin(str, Enum):
    DOWNSTREAM = "downstream"
    LOCAL_POLICY = "local_policy"
    LOCAL_RESOURCE_FAULT = "local_resource_fault"
    RESET_OR_CANCEL = "reset_or_cancel"
    MALFORMED_COMPLETION = "malformed_completion"
    MIXED = "mixed"


class EquivalenceLevel(str, Enum):
    OPERATION_EFFECT = "operation_effect"
    LINK_TRANSACTION_ORDER = "link_transaction_order"
    PIN_CYCLE = "pin_cycle"


class UnsupportedPolicy(str, Enum):
    REJECT = "reject"
    EXPLICIT_DEFAULT = "explicit_default"
    EXPLICIT_DROP = "explicit_drop"


class ResetCancelPolicy(str, Enum):
    CANCEL = "cancel"
    DRAIN = "drain"
    REPORT_FAULT = "report_fault"


class TranslationAccessMode(str, Enum):
    STREAMING_SEQUENTIAL = "streaming_sequential"
    MATERIALIZE_BLOCK = "materialize_block"
    RANDOM_ACCESS_REORDER = "random_access_reorder"


@dataclass(frozen=True)
class StageContract:
    capabilities: CapabilityRelation = field(default_factory=CapabilityRelation)
    semantic_effects: tuple[SemanticEffect, ...] = ()
    applicability_rule: str = ""
    completion_rule: str = ""
    preservation_obligations: tuple[str, ...] = ()
    provenance: str = ""

    def __post_init__(self) -> None:
        if any(not isinstance(item, SemanticEffect) for item in self.semantic_effects):
            raise TypeError("stage semantic effects must be SemanticEffect values")
        if any(
            not isinstance(item, str) or not item
            for item in self.preservation_obligations
        ):
            raise ValueError("preservation obligations must be non-empty strings")


@dataclass(frozen=True)
class BridgeProfile:
    """The construction promise selected for one concrete bridge."""

    name: str
    source: OperationSignature
    target: OperationSignature
    source_request_capabilities: CapabilitySet = field(
        default_factory=CapabilitySet
    )
    target_request_requirements: CapabilitySet = field(
        default_factory=CapabilitySet
    )
    target_completion_capabilities: CapabilitySet = field(
        default_factory=CapabilitySet
    )
    source_completion_requirements: CapabilitySet = field(
        default_factory=CapabilitySet
    )
    ordering: tuple[str, ...] = ()
    allowed_weakening: frozenset[str] = frozenset()
    equivalence: EquivalenceLevel = EquivalenceLevel.OPERATION_EFFECT
    unsupported_policy: UnsupportedPolicy = UnsupportedPolicy.REJECT
    reset_cancel_policy: ResetCancelPolicy = ResetCancelPolicy.REPORT_FAULT
    access_mode: TranslationAccessMode = (
        TranslationAccessMode.STREAMING_SEQUENTIAL
    )
    provenance: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("bridge profile requires a name")
        if not isinstance(self.source, OperationSignature) or not isinstance(
            self.target, OperationSignature
        ):
            raise TypeError("bridge profile requires operation signatures")
        if any(not isinstance(item, str) or not item for item in self.ordering):
            raise ValueError("ordering declarations must be non-empty strings")
        if any(
            not isinstance(item, str) or not item
            for item in self.allowed_weakening
        ):
            raise ValueError("allowed weakening properties must be non-empty")
