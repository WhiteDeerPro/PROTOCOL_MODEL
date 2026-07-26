"""Small, inspectable semantic declarations shared by every protocol scope."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class ConstraintScope(str, Enum):
    """The smallest scope at which a constraint can be decided."""

    EVENT = "event"
    TRANSPORT = "transport"
    INTERFACE = "interface"
    VIRTUAL_DUT = "virtual_dut"
    SYSTEM = "system"


class ConstraintKind(str, Enum):
    SAFETY = "safety"
    RELATION = "relation"
    RESOURCE = "resource"
    PROGRESS = "progress"


class ResourceExhaustionPolicy(str, Enum):
    """How an executable boundary handles an unsatisfied resource demand.

    ``BLOCK`` means the triggering action was not accepted and may be retried.
    ``ERROR_COMPLETION`` accepts the action but completes it with an ordinary
    protocol-visible error.  ``FAULT`` reports a model/use-contract violation.
    The latter two are therefore not forms of backpressure.
    """

    BLOCK = "block"
    ERROR_COMPLETION = "error_completion"
    FAULT = "fault"


@dataclass(frozen=True)
class ResourceDemand:
    """Typed reason why an executable transition cannot accept an action."""

    resource: str
    scope: ConstraintScope
    required: int = 1
    available: int | None = None
    capacity: int | None = None
    reason: str = ""
    location: str = ""

    def __post_init__(self) -> None:
        if not self.resource:
            raise ValueError("resource demand requires a resource name")
        if not isinstance(self.scope, ConstraintScope):
            raise TypeError("resource demand requires a constraint scope")
        if (
            not isinstance(self.required, int)
            or isinstance(self.required, bool)
            or self.required <= 0
        ):
            raise ValueError("resource demand required amount must be positive")
        if self.available is not None and (
            not isinstance(self.available, int)
            or isinstance(self.available, bool)
            or self.available < 0
        ):
            raise ValueError("resource demand available amount must be non-negative")
        if self.capacity is not None and (
            not isinstance(self.capacity, int)
            or isinstance(self.capacity, bool)
            or self.capacity <= 0
        ):
            raise ValueError("resource demand capacity must be positive")
        if (
            self.available is not None
            and self.capacity is not None
            and self.available > self.capacity
        ):
            raise ValueError("resource demand availability exceeds capacity")
        if self.available is not None and self.available >= self.required:
            raise ValueError("resource demand must describe an unsatisfied request")


@dataclass(frozen=True)
class SemanticConstraint:
    name: str
    rule: str
    scope: ConstraintScope
    kind: ConstraintKind = ConstraintKind.SAFETY
    targets: tuple[str, ...] = ()
    foundation: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.rule:
            raise ValueError("semantic constraint requires name and rule")

    def namespaced(self, prefix: str) -> "SemanticConstraint":
        return replace(
            self,
            name=f"{prefix}.{self.name}",
            targets=tuple(f"{prefix}.{target}" for target in self.targets),
        )


@dataclass(frozen=True)
class ResourceDecl:
    name: str
    scope: ConstraintScope
    capacity: int | None = None
    description: str = ""
    acquired_by: tuple[str, ...] = ()
    released_by: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("resource requires a name")
        if self.capacity is not None and self.capacity <= 0:
            raise ValueError("resource capacity must be positive")
        if bool(self.acquired_by) != bool(self.released_by):
            raise ValueError(
                "a dynamic resource lifecycle requires both acquire and release transitions"
            )

    def namespaced(self, prefix: str) -> "ResourceDecl":
        return replace(
            self,
            name=f"{prefix}.{self.name}",
            acquired_by=tuple(
                f"{prefix}.{transition}" for transition in self.acquired_by
            ),
            released_by=tuple(
                f"{prefix}.{transition}" for transition in self.released_by
            ),
        )


@dataclass(frozen=True)
class ObligationDecl:
    """A progress obligation visible to system-level wait-for analysis."""

    name: str
    scope: ConstraintScope
    opened_by: str
    discharged_by: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name or not self.opened_by or not self.discharged_by:
            raise ValueError(
                "obligation requires name, opening transition, and discharge transition"
            )

    def namespaced(self, prefix: str) -> "ObligationDecl":
        return replace(
            self,
            name=f"{prefix}.{self.name}",
            opened_by=f"{prefix}.{self.opened_by}",
            discharged_by=f"{prefix}.{self.discharged_by}",
        )
