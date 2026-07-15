"""Typed translation stages and their runtime outcomes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar, Union

from .contract import CompletionOrigin, SemanticEffect, StageContract
from .signature import OperationSignature


ParentRequestT = TypeVar("ParentRequestT")
ParentResultT = TypeVar("ParentResultT")
ChildRequestT = TypeVar("ChildRequestT")
ChildResultT = TypeVar("ChildResultT")


class StageCardinality(str, Enum):
    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"


@dataclass(frozen=True)
class Applicability:
    accepted: bool
    reason: str = ""
    rule: str = ""

    def __post_init__(self) -> None:
        if self.accepted and self.reason:
            raise ValueError("accepted applicability cannot carry a rejection reason")
        if not self.accepted and not self.reason:
            raise ValueError("rejected applicability requires a reason")

    @classmethod
    def accept(cls) -> "Applicability":
        return cls(True)

    @classmethod
    def reject(cls, reason: str, *, rule: str = "") -> "Applicability":
        return cls(False, reason, rule)


@dataclass(frozen=True)
class LoweredOne(Generic[ChildRequestT]):
    child: ChildRequestT
    context: object | None = None


@dataclass(frozen=True)
class LocalCompletion(Generic[ParentResultT]):
    result: ParentResultT
    origin: CompletionOrigin = CompletionOrigin.LOCAL_POLICY
    rule: str = ""


@dataclass(frozen=True)
class Rejected:
    reason: str
    rule: str = ""
    semantic_effects: tuple[SemanticEffect, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("translation rejection requires a reason")


@dataclass(frozen=True)
class Expanded:
    count: int
    context: object | None = None
    fold_state: object | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.count, int)
            or isinstance(self.count, bool)
            or self.count <= 0
        ):
            raise ValueError("fan-out expansion count must be positive")


UnaryLowering = Union[
    LoweredOne[ChildRequestT],
    LocalCompletion[ParentResultT],
    Rejected,
]
FanoutBeginning = Union[
    Expanded,
    LocalCompletion[ParentResultT],
    Rejected,
]


class UnaryTranslationStage(
    ABC,
    Generic[
        ParentRequestT,
        ParentResultT,
        ChildRequestT,
        ChildResultT,
    ],
):
    """A typed 1→1 stage that can also complete or reject locally."""

    name: str
    source: OperationSignature
    target: OperationSignature
    contract: StageContract
    cardinality = StageCardinality.ONE_TO_ONE

    def applicable(self, parent: ParentRequestT) -> Applicability:
        return Applicability.accept()

    @abstractmethod
    def lower(
        self, parent: ParentRequestT
    ) -> UnaryLowering[ChildRequestT, ParentResultT]:
        raise NotImplementedError

    @abstractmethod
    def lift(
        self, context: object | None, child_result: ChildResultT
    ) -> ParentResultT:
        raise NotImplementedError


class FanoutTranslationStage(
    ABC,
    Generic[
        ParentRequestT,
        ParentResultT,
        ChildRequestT,
        ChildResultT,
    ],
):
    """A lazy indexed 1→N stage with incremental result folding."""

    name: str
    source: OperationSignature
    target: OperationSignature
    contract: StageContract
    cardinality = StageCardinality.ONE_TO_MANY

    def applicable(self, parent: ParentRequestT) -> Applicability:
        return Applicability.accept()

    @abstractmethod
    def begin(self, parent: ParentRequestT) -> FanoutBeginning[ParentResultT]:
        raise NotImplementedError

    @abstractmethod
    def child_at(self, context: object | None, index: int) -> ChildRequestT:
        raise NotImplementedError

    @abstractmethod
    def fold_one(
        self,
        context: object | None,
        fold_state: object | None,
        index: int,
        child_result: ChildResultT,
    ) -> object | None:
        raise NotImplementedError

    @abstractmethod
    def finish(
        self, context: object | None, fold_state: object | None
    ) -> ParentResultT:
        raise NotImplementedError


@dataclass(frozen=True)
class IdentityTranslationStage(
    UnaryTranslationStage[object, object, object, object]
):
    """An explicit transport-only identity relation for one operation form."""

    name: str
    signature: OperationSignature
    contract: StageContract = field(default_factory=StageContract)

    @property
    def source(self) -> OperationSignature:
        return self.signature

    @property
    def target(self) -> OperationSignature:
        return self.signature

    def lower(self, parent: object) -> LoweredOne[object]:
        return LoweredOne(parent)

    def lift(self, context: object | None, child_result: object) -> object:
        return child_result
