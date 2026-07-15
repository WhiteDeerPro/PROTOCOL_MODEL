"""Parent/child identity and fan-out obligation accounting."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, order=True)
class TokenRef:
    """Executor-local identity; it is intentionally unrelated to a wire ID."""

    kind: str
    serial: int

    def __post_init__(self) -> None:
        if self.kind not in {"parent", "child"}:
            raise ValueError("translation token kind must be parent or child")
        if (
            not isinstance(self.serial, int)
            or isinstance(self.serial, bool)
            or self.serial < 0
        ):
            raise ValueError("translation token serial must be non-negative")


@dataclass(frozen=True)
class ChildLineage:
    """A child obligation and its parent, independent of transport ownership."""

    parent: TokenRef
    child: TokenRef
    child_index: int

    def __post_init__(self) -> None:
        if self.parent.kind != "parent" or self.child.kind != "child":
            raise ValueError("child lineage requires parent and child token kinds")
        if (
            not isinstance(self.child_index, int)
            or isinstance(self.child_index, bool)
            or self.child_index < 0
        ):
            raise ValueError("child index must be non-negative")


@dataclass(frozen=True)
class ChildOwner:
    """An issued child's lineage plus the egress binding that owns it."""

    lineage: ChildLineage
    egress_binding: str

    def __post_init__(self) -> None:
        if not isinstance(self.lineage, ChildLineage):
            raise TypeError("child owner requires ChildLineage")
        if not isinstance(self.egress_binding, str) or not self.egress_binding:
            raise ValueError("child owner requires a non-empty egress binding")

    @property
    def parent(self) -> TokenRef:
        return self.lineage.parent

    @property
    def child(self) -> TokenRef:
        return self.lineage.child

    @property
    def child_index(self) -> int:
        return self.lineage.child_index


@dataclass(frozen=True)
class FanoutLedger:
    """Lifecycle accounting for one parent-to-children expansion.

    V1 issues child indexes in order.  ``total`` is semantic work, while the
    number of live ``inflight`` owners is runtime concurrency.  No capacity
    limit is stored here.
    """

    parent: TokenRef
    total: int
    issued: int = 0
    completed: int = 0
    inflight: tuple[ChildLineage, ...] = ()

    def __post_init__(self) -> None:
        if self.parent.kind != "parent":
            raise ValueError("fan-out ledger requires a parent token")
        for name in ("total", "issued", "completed"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"fan-out {name} must be an integer")
        if self.total <= 0:
            raise ValueError("fan-out total must be positive")
        if not 0 <= self.completed <= self.issued <= self.total:
            raise ValueError("fan-out counts require completed <= issued <= total")
        if len(self.inflight) != self.issued - self.completed:
            raise ValueError("fan-out inflight count does not match lifecycle counts")
        if any(lineage.parent != self.parent for lineage in self.inflight):
            raise ValueError("fan-out child owner belongs to another parent")
        indexes = tuple(lineage.child_index for lineage in self.inflight)
        if len(set(indexes)) != len(indexes):
            raise ValueError("fan-out inflight child indexes must be unique")
        tokens = tuple(lineage.child for lineage in self.inflight)
        if len(set(tokens)) != len(tokens):
            raise ValueError("fan-out inflight child tokens must be unique")
        if any(index >= self.issued for index in indexes):
            raise ValueError("fan-out inflight child must already be issued")

    @property
    def remaining(self) -> int:
        return self.total - self.completed

    @property
    def can_issue(self) -> bool:
        return self.issued < self.total

    @property
    def can_finish(self) -> bool:
        return self.completed == self.total and not self.inflight

    def issue(self, lineage: ChildLineage) -> "FanoutLedger":
        if not self.can_issue:
            raise ValueError("fan-out ledger has no unissued child obligation")
        if not isinstance(lineage, ChildLineage):
            raise TypeError("fan-out issue requires ChildLineage")
        if lineage.parent != self.parent:
            raise ValueError("issued child belongs to another parent")
        if lineage.child_index != self.issued:
            raise ValueError(
                f"next fan-out child index is {self.issued}, "
                f"got {lineage.child_index}"
            )
        return replace(
            self,
            issued=self.issued + 1,
            inflight=self.inflight + (lineage,),
        )

    def complete(self, lineage: ChildLineage) -> "FanoutLedger":
        if not isinstance(lineage, ChildLineage):
            raise TypeError("fan-out completion requires ChildLineage")
        try:
            index = self.inflight.index(lineage)
        except ValueError as error:
            raise ValueError("child completion has no inflight obligation") from error
        inflight = list(self.inflight)
        del inflight[index]
        return replace(
            self,
            completed=self.completed + 1,
            inflight=tuple(inflight),
        )

    def require_finished(self) -> None:
        if not self.can_finish:
            raise ValueError(
                "fan-out parent cannot finish before every child completes"
            )
