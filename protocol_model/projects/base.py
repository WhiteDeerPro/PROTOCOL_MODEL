"""Lifecycle and inventory model for user-facing verification projects."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class ProjectPhase(str, Enum):
    CREATED = "CREATED"
    ELABORATED = "ELABORATED"
    EXECUTED = "EXECUTED"
    CHECKED = "CHECKED"
    REPORTED = "REPORTED"
    FAILED = "FAILED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class ComponentUse:
    name: str
    category: str
    implementation: str
    role: str


@dataclass(frozen=True)
class LifecycleEntry:
    phase: ProjectPhase
    summary: str


@dataclass(frozen=True)
class ProjectSnapshot:
    name: str
    phase: ProjectPhase
    components: tuple[ComponentUse, ...]
    state: Mapping[str, object]
    artifacts: tuple[str, ...]
    history: tuple[LifecycleEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", MappingProxyType(dict(self.state)))


class VerificationProject:
    """A test case owner from creation through evidence publication."""

    name: str

    def __init__(self, name: str, components: tuple[ComponentUse, ...]):
        self.name = name
        self.phase = ProjectPhase.CREATED
        self.components = components
        self.state: dict[str, object] = {}
        self.artifacts: list[str] = []
        self.history = [LifecycleEntry(self.phase, "project object created")]

    def transition(self, phase: ProjectPhase, summary: str) -> None:
        allowed = {
            ProjectPhase.CREATED: {ProjectPhase.ELABORATED, ProjectPhase.FAILED},
            ProjectPhase.ELABORATED: {ProjectPhase.EXECUTED, ProjectPhase.FAILED},
            ProjectPhase.EXECUTED: {ProjectPhase.CHECKED, ProjectPhase.FAILED},
            ProjectPhase.CHECKED: {ProjectPhase.REPORTED, ProjectPhase.CLOSED},
            ProjectPhase.REPORTED: {ProjectPhase.CLOSED},
            ProjectPhase.FAILED: {ProjectPhase.REPORTED, ProjectPhase.CLOSED},
            ProjectPhase.CLOSED: set(),
        }
        if phase not in allowed[self.phase]:
            raise RuntimeError(f"invalid project transition {self.phase.value} -> {phase.value}")
        self.phase = phase
        self.history.append(LifecycleEntry(phase, summary))

    def publish(self, *artifacts: str) -> None:
        self.artifacts.extend(artifacts)
        self.transition(ProjectPhase.REPORTED, f"published {len(artifacts)} artifacts")

    def close(self) -> None:
        self.transition(ProjectPhase.CLOSED, "project closed")

    def snapshot(self) -> ProjectSnapshot:
        return ProjectSnapshot(
            self.name,
            self.phase,
            self.components,
            self.state,
            tuple(self.artifacts),
            tuple(self.history),
        )
