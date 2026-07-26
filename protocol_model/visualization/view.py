"""Shared metadata describing what a visualization projection means."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .policy import DiagramDetail


class ViewKind(str, Enum):
    """Finite semantic kinds used by current and near-term projectors."""

    TOPOLOGY = "topology"
    INTERCONNECT_INTERFACE_MAP = "interconnect_interface_map"
    VIRTUAL_DUT_STRUCTURE = "virtual_dut_structure"
    INTERFACE_CHANNEL = "interface_channel"
    SIGNAL_TIMING = "signal_timing"
    SEMANTIC_TIMELINE = "semantic_timeline"
    TRANSACTION_SEQUENCE = "transaction_sequence"
    ROUTE_CORRELATION = "route_correlation"
    CAUSAL_GRAPH = "causal_graph"
    STATE_SNAPSHOT = "state_snapshot"
    REPORT_INDEX = "report_index"


class ViewScope(str, Enum):
    """The smallest model boundary needed to produce a view."""

    INTERFACE = "interface"
    TRANSPORT_LINK = "transport_link"
    VIRTUAL_DUT = "virtual_dut"
    SYSTEM = "system"
    SCENARIO = "scenario"


class EvidenceBasis(str, Enum):
    """Where the facts in a view came from."""

    DECLARED = "declared"
    RESOLVED = "resolved"
    OBSERVED = "observed"


class ProjectionIntent(str, Enum):
    """Whether a view repeats facts, analyzes them, or explains a design."""

    DIRECT = "direct"
    DERIVED = "derived"
    EXPLANATORY = "explanatory"


class TimeBasis(str, Enum):
    """Meaning of horizontal position or ordering in a view."""

    NONE = "none"
    CLOCK_TICK = "clock_tick"
    TIMESTAMP = "timestamp"
    MODEL_STEP = "model_step"
    EVENT_INDEX = "event_index"
    CAUSAL_RANK = "causal_rank"


@dataclass(frozen=True)
class ViewDescriptor:
    """Orthogonal metadata for one concrete source/rendered projection.

    ``detail`` is a presentation selection.  It must not change the model
    facts retained by the typed view from which a renderer is invoked.
    """

    view_kind: ViewKind
    scope: ViewScope
    evidence_basis: EvidenceBasis
    source_schema: str
    projection_intent: ProjectionIntent = ProjectionIntent.DIRECT
    time_basis: TimeBasis = TimeBasis.NONE
    detail: DiagramDetail = DiagramDetail.STANDARD

    def __post_init__(self) -> None:
        object.__setattr__(self, "view_kind", ViewKind(self.view_kind))
        object.__setattr__(self, "scope", ViewScope(self.scope))
        object.__setattr__(
            self, "evidence_basis", EvidenceBasis(self.evidence_basis)
        )
        object.__setattr__(
            self, "projection_intent", ProjectionIntent(self.projection_intent)
        )
        object.__setattr__(self, "time_basis", TimeBasis(self.time_basis))
        object.__setattr__(self, "detail", DiagramDetail(self.detail))
        if not isinstance(self.source_schema, str) or not self.source_schema:
            raise ValueError("view descriptor requires a source schema")


__all__ = [
    "EvidenceBasis",
    "ProjectionIntent",
    "TimeBasis",
    "ViewDescriptor",
    "ViewKind",
    "ViewScope",
]
