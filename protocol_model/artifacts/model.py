"""Stable, protocol-independent records stored in run manifests."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping


RUN_SCHEMA = "protocol-model.run/v3"
CONSTRAINT_SCHEMA = "protocol-model.constraints/v2"


@dataclass(frozen=True)
class ArtifactRecord:
    kind: str
    path: str
    media_type: str
    case: str | None = None
    source: bool = False


@dataclass(frozen=True)
class ProtocolRecord:
    scope: str
    identity: str
    definition: str
    parameters: Mapping[str, object]
    lineage: tuple[str, ...] = ()
    metadata: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ConstraintEvidence:
    id: str
    source: str
    target: str
    rule: str
    foundation: str
    status: str
    instances: tuple[str, ...] = ()
    witness: str = ""


def json_value(value):
    """Convert semantic and report values without falling back to opaque str()."""

    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return json_value(value.value)
    if isinstance(value, Mapping):
        return {str(name): json_value(item) for name, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [json_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
