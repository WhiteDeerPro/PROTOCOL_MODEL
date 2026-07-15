"""Small, inspectable semantic declarations shared by every protocol scope."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class ConstraintScope(str, Enum):
    """The smallest scope at which a constraint can be decided."""

    EVENT = "event"
    LINK = "link"
    VIRTUAL_DUT = "virtual_dut"
    SYSTEM = "system"


class ConstraintKind(str, Enum):
    SAFETY = "safety"
    RELATION = "relation"
    RESOURCE = "resource"
    PROGRESS = "progress"


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
