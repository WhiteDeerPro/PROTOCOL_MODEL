"""Typed, protocol-independent transaction time-space projections.

The types in this module are presentation IR.  Callers supply lifelines,
events, state changes, and causal edges explicitly; the module does not infer
protocol rules or happens-before relations from names, channels, or time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
import json
from math import isfinite
from types import MappingProxyType

from protocol_model.semantics import CausalGraph, PartialOrderViolation

from .policy import DiagramDetail
from .view import (
    EvidenceBasis,
    ProjectionIntent,
    TimeBasis,
    ViewDescriptor,
    ViewKind,
    ViewScope,
)


TIME_SPACE_VIEW_SCHEMA = "protocol-model.transaction-time-space-view/v1"

_TIME_SPACE_VIEW_KINDS = frozenset(
    (
        ViewKind.TRANSACTION_SEQUENCE,
        ViewKind.SEMANTIC_TIMELINE,
        ViewKind.CAUSAL_GRAPH,
    )
)

_MESSAGE_CHANNEL_STYLES = MappingProxyType(
    {
        "req": ("#2563a8", "REQ · request"),
        "request": ("#2563a8", "REQ · request"),
        "snp": ("#c46a00", "SNP · snoop"),
        "snoop": ("#c46a00", "SNP · snoop"),
        "rsp": ("#247148", "RSP · response/credit"),
        "response": ("#247148", "RSP · response/credit"),
        "dat": ("#7c4aa5", "DAT · data/copyback"),
        "data": ("#7c4aa5", "DAT · data/copyback"),
    }
)
_DEFAULT_MESSAGE_STYLE = ("#475569", "other message")
_MESSAGE_LEGEND_ORDER = tuple(
    _MESSAGE_CHANNEL_STYLES[channel]
    for channel in ("req", "snp", "rsp", "dat")
)


class MessageObservationPoint(str, Enum):
    """How one retained message occurrence enters a semantic timeline."""

    EXCHANGE = "exchange"
    ACCEPTANCE = "acceptance"


def _require_text(value: object, subject: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{subject} must be a non-empty string")


def _require_optional_text(value: object, subject: str) -> None:
    if value is not None:
        _require_text(value, subject)


def _require_time(value: object, subject: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{subject} must be an integer")
    if value < 0:
        raise ValueError(f"{subject} must be non-negative")


def _freeze_json_value(value: object, subject: str) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{subject} must not contain non-finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{subject} keys must be non-empty strings")
            frozen[key] = _freeze_json_value(item, f"{subject}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (tuple, list)):
        return tuple(
            _freeze_json_value(item, f"{subject}[{index}]")
            for index, item in enumerate(value)
        )
    raise TypeError(f"{subject} must contain only JSON-compatible values")


def _freeze_display_fields(
    fields: Mapping[str, object],
) -> Mapping[str, object]:
    if not isinstance(fields, Mapping):
        raise TypeError("display_fields must be a mapping")
    frozen = _freeze_json_value(fields, "display_fields")
    assert isinstance(frozen, Mapping)
    return frozen


def _plain_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json_value(item) for item in value]
    return value


@dataclass(frozen=True)
class TimeSpaceLifeline:
    """One explicitly declared participant column."""

    ref: str
    label: str
    kind: str = "participant"
    display_fields: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.ref, "lifeline ref")
        _require_text(self.label, "lifeline label")
        _require_text(self.kind, "lifeline kind")
        object.__setattr__(
            self,
            "display_fields",
            _freeze_display_fields(self.display_fields),
        )


@dataclass(frozen=True)
class TimeSpaceMessage:
    """One message occurrence positioned between two declared lifelines."""

    event_ref: str
    operation_ref: str
    source: str
    destination: str
    time: int
    label: str
    lane: str | None = None
    channel: str | None = None
    display_fields: Mapping[str, object] = field(default_factory=dict)
    observation_point: MessageObservationPoint = (
        MessageObservationPoint.EXCHANGE
    )

    def __post_init__(self) -> None:
        _require_text(self.event_ref, "message event_ref")
        _require_text(self.operation_ref, "message operation_ref")
        _require_text(self.source, "message source")
        _require_text(self.destination, "message destination")
        _require_time(self.time, "message time")
        _require_text(self.label, "message label")
        _require_optional_text(self.lane, "message lane")
        _require_optional_text(self.channel, "message channel")
        try:
            observation_point = MessageObservationPoint(
                self.observation_point
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                "message observation_point must be exchange or acceptance"
            ) from error
        object.__setattr__(
            self,
            "display_fields",
            _freeze_display_fields(self.display_fields),
        )
        object.__setattr__(
            self,
            "observation_point",
            observation_point,
        )


@dataclass(frozen=True)
class TimeSpaceStateChange:
    """One explicitly observed or declared state transition."""

    event_ref: str
    operation_ref: str
    lifeline: str
    time: int
    before: str
    after: str
    label: str
    display_fields: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.event_ref, "state-change event_ref")
        _require_text(self.operation_ref, "state-change operation_ref")
        _require_text(self.lifeline, "state-change lifeline")
        _require_time(self.time, "state-change time")
        _require_text(self.before, "state-change before")
        _require_text(self.after, "state-change after")
        _require_text(self.label, "state-change label")
        object.__setattr__(
            self,
            "display_fields",
            _freeze_display_fields(self.display_fields),
        )


@dataclass(frozen=True)
class TimeSpaceCausalEdge:
    """One caller-supplied happens-before edge and its stated reason."""

    source_event_ref: str
    destination_event_ref: str
    reason: str

    def __post_init__(self) -> None:
        _require_text(self.source_event_ref, "causal source_event_ref")
        _require_text(
            self.destination_event_ref,
            "causal destination_event_ref",
        )
        _require_text(self.reason, "causal reason")


@dataclass(frozen=True)
class TransactionTimeSpaceView:
    """Immutable transaction events prepared for several renderings.

    ``EVENT_INDEX`` represents a total observation order and therefore
    requires a unique time for every event.  ``MODEL_STEP`` permits multiple
    events at one step.  In either basis, explicit causal edges may remain at
    one model step but cannot point to an earlier time.
    """

    name: str
    lifelines: tuple[TimeSpaceLifeline, ...]
    messages: tuple[TimeSpaceMessage, ...]
    state_changes: tuple[TimeSpaceStateChange, ...] = ()
    causal_edges: tuple[TimeSpaceCausalEdge, ...] = ()
    time_basis: TimeBasis = TimeBasis.EVENT_INDEX
    scope: ViewScope = ViewScope.SCENARIO
    evidence_basis: EvidenceBasis = EvidenceBasis.OBSERVED

    def __post_init__(self) -> None:
        _require_text(self.name, "time-space view name")
        lifelines = tuple(self.lifelines)
        messages = tuple(self.messages)
        state_changes = tuple(self.state_changes)
        causal_edges = tuple(self.causal_edges)
        if not lifelines:
            raise ValueError("time-space view requires at least one lifeline")
        if any(not isinstance(item, TimeSpaceLifeline) for item in lifelines):
            raise TypeError("lifelines require TimeSpaceLifeline values")
        if any(not isinstance(item, TimeSpaceMessage) for item in messages):
            raise TypeError("messages require TimeSpaceMessage values")
        if any(
            not isinstance(item, TimeSpaceStateChange)
            for item in state_changes
        ):
            raise TypeError(
                "state_changes require TimeSpaceStateChange values"
            )
        if any(
            not isinstance(item, TimeSpaceCausalEdge)
            for item in causal_edges
        ):
            raise TypeError(
                "causal_edges require TimeSpaceCausalEdge values"
            )
        if not messages and not state_changes:
            raise ValueError("time-space view requires at least one event")

        time_basis = TimeBasis(self.time_basis)
        if time_basis not in {TimeBasis.EVENT_INDEX, TimeBasis.MODEL_STEP}:
            raise ValueError(
                "transaction time-space view requires event_index or "
                "model_step time basis"
            )
        scope = ViewScope(self.scope)
        evidence_basis = EvidenceBasis(self.evidence_basis)

        lifeline_refs = tuple(item.ref for item in lifelines)
        if len(set(lifeline_refs)) != len(lifeline_refs):
            raise ValueError("time-space lifeline refs must be unique")
        known_lifelines = set(lifeline_refs)
        for message in messages:
            if (
                message.source not in known_lifelines
                or message.destination not in known_lifelines
            ):
                raise ValueError(
                    f"message {message.event_ref!r} references an unknown "
                    "lifeline"
                )
        for change in state_changes:
            if change.lifeline not in known_lifelines:
                raise ValueError(
                    f"state change {change.event_ref!r} references an "
                    "unknown lifeline"
                )

        events = (*messages, *state_changes)
        event_refs = tuple(item.event_ref for item in events)
        if len(set(event_refs)) != len(event_refs):
            raise ValueError("time-space event refs must be unique")
        if time_basis is TimeBasis.EVENT_INDEX:
            event_times = tuple(item.time for item in events)
            if len(set(event_times)) != len(event_times):
                raise ValueError(
                    "event_index time basis requires unique event times"
                )
        event_time = {item.event_ref: item.time for item in events}
        edge_keys: set[tuple[str, str]] = set()
        for edge in causal_edges:
            key = (edge.source_event_ref, edge.destination_event_ref)
            if key in edge_keys:
                raise ValueError("time-space causal edges must be unique")
            edge_keys.add(key)
            if (
                edge.source_event_ref not in event_time
                or edge.destination_event_ref not in event_time
            ):
                raise ValueError("causal edge references an unknown event")
            if (
                event_time[edge.source_event_ref]
                > event_time[edge.destination_event_ref]
            ):
                raise ValueError("causal edge cannot point to an earlier time")
        try:
            CausalGraph.from_edges(event_refs, edge_keys)
        except PartialOrderViolation as error:
            raise ValueError(f"invalid causal edges: {error}") from error

        object.__setattr__(self, "lifelines", lifelines)
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "state_changes", state_changes)
        object.__setattr__(self, "causal_edges", causal_edges)
        object.__setattr__(self, "time_basis", time_basis)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "evidence_basis", evidence_basis)

    def descriptor(
        self,
        *,
        view_kind: ViewKind = ViewKind.TRANSACTION_SEQUENCE,
        detail: DiagramDetail = DiagramDetail.STANDARD,
    ) -> ViewDescriptor:
        """Describe one rendering without changing the retained IR."""

        view_kind = ViewKind(view_kind)
        if view_kind not in _TIME_SPACE_VIEW_KINDS:
            raise ValueError("unsupported transaction time-space view kind")
        return ViewDescriptor(
            view_kind=view_kind,
            scope=self.scope,
            evidence_basis=self.evidence_basis,
            source_schema=TIME_SPACE_VIEW_SCHEMA,
            projection_intent=ProjectionIntent.DIRECT,
            time_basis=self.time_basis,
            detail=detail,
        )

    def to_dict(
        self,
        *,
        view_kind: ViewKind = ViewKind.TRANSACTION_SEQUENCE,
    ) -> dict[str, object]:
        """Return a detached, JSON-serializable representation."""

        descriptor = self.descriptor(view_kind=view_kind)
        return {
            "schema": TIME_SPACE_VIEW_SCHEMA,
            "descriptor": {
                "view_kind": descriptor.view_kind.value,
                "scope": descriptor.scope.value,
                "evidence_basis": descriptor.evidence_basis.value,
                "source_schema": descriptor.source_schema,
                "projection_intent": descriptor.projection_intent.value,
                "time_basis": descriptor.time_basis.value,
                "detail": descriptor.detail.value,
            },
            "name": self.name,
            "lifelines": [
                {
                    "ref": item.ref,
                    "label": item.label,
                    "kind": item.kind,
                    "display_fields": _plain_json_value(
                        item.display_fields
                    ),
                }
                for item in self.lifelines
            ],
            "messages": [
                {
                    "event_ref": item.event_ref,
                    "operation_ref": item.operation_ref,
                    "source": item.source,
                    "destination": item.destination,
                    "time": item.time,
                    "label": item.label,
                    "lane": item.lane,
                    "channel": item.channel,
                    "observation_point": item.observation_point.value,
                    "display_fields": _plain_json_value(
                        item.display_fields
                    ),
                }
                for item in self.messages
            ],
            "state_changes": [
                {
                    "event_ref": item.event_ref,
                    "operation_ref": item.operation_ref,
                    "lifeline": item.lifeline,
                    "time": item.time,
                    "before": item.before,
                    "after": item.after,
                    "label": item.label,
                    "display_fields": _plain_json_value(
                        item.display_fields
                    ),
                }
                for item in self.state_changes
            ],
            "causal_edges": [
                {
                    "source_event_ref": item.source_event_ref,
                    "destination_event_ref": item.destination_event_ref,
                    "reason": item.reason,
                }
                for item in self.causal_edges
            ],
        }


def _dot_quote(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _display_suffix(fields: Mapping[str, object]) -> str:
    if not fields:
        return ""

    def render(value: object) -> str:
        if isinstance(value, str):
            return value
        return json.dumps(_plain_json_value(value), ensure_ascii=False)

    rendered = "\n".join(
        f"{key}={render(value)}"
        for key, value in fields.items()
    )
    return f"\n{rendered}"


def _presentation_suffix(fields: Mapping[str, object]) -> str:
    summary = fields.get("summary")
    if isinstance(summary, str):
        return f"\n{summary}" if summary else ""
    return _display_suffix(fields)


def _state_presentation(change: TimeSpaceStateChange) -> str:
    summary = change.display_fields.get("summary")
    if isinstance(summary, str) and summary:
        return summary
    return (
        f"{_wrapped_state(change.before)}\n→\n"
        f"{_wrapped_state(change.after)}"
    )


def _compact_ref(value: str) -> str:
    parts = value.split(":")
    return ":".join(parts[-2:]) if len(parts) > 2 else value


def _wrapped_state(value: str) -> str:
    return value.replace(" | ", "\n")


def _message_label(message: TimeSpaceMessage) -> str:
    qualifiers = []
    for value in (message.channel, message.lane):
        if value is not None and value.lower() not in {
            item.lower() for item in qualifiers
        }:
            qualifiers.append(value)
    lane_text = " · ".join(value.upper() for value in qualifiers)
    heading = message.label + (f" · {lane_text}" if lane_text else "")
    return (
        f"{heading} [{_timeline_event_token(message.event_ref)}]"
        f"{_presentation_suffix(message.display_fields)}"
    )


def _message_style(message: TimeSpaceMessage) -> tuple[str, str]:
    """Return a presentation-only color and legend label for one channel."""

    for value in (message.channel, message.lane):
        if value is None:
            continue
        style = _MESSAGE_CHANNEL_STYLES.get(value.casefold())
        if style is not None:
            return style
    return _DEFAULT_MESSAGE_STYLE


def _time_space_legend(view: TransactionTimeSpaceView) -> str:
    present_styles = set()
    for message in view.messages:
        present_styles.add(_message_style(message))
    styles = [
        style for style in _MESSAGE_LEGEND_ORDER if style in present_styles
    ]
    if _DEFAULT_MESSAGE_STYLE in present_styles:
        styles.append(_DEFAULT_MESSAGE_STYLE)
    cells = [
        (
            f'<TD BORDER="1" COLOR="{color}" BGCOLOR="{color}" '
            'WIDTH="12"></TD>'
            f'<TD ALIGN="LEFT">{label}</TD>'
        )
        for color, label in styles
    ]
    if view.state_changes:
        cells.append(
            '<TD BORDER="1" COLOR="#a87d21" BGCOLOR="#fff7dd" '
            'WIDTH="12"></TD><TD ALIGN="LEFT">state change</TD>'
        )
    return (
        "<<TABLE BORDER=\"0\" CELLBORDER=\"0\" CELLSPACING=\"5\" "
        "CELLPADDING=\"2\"><TR><TD><B>Legend</B></TD>"
        + "".join(cells)
        + "</TR></TABLE>>"
    )


def transaction_time_space_dot(view: TransactionTimeSpaceView) -> str:
    """Render explicit events as a Graphviz time-space swimlane diagram."""

    if not isinstance(view, TransactionTimeSpaceView):
        raise TypeError("time-space renderer requires TransactionTimeSpaceView")
    times = sorted(
        {
            item.time
            for item in (*view.messages, *view.state_changes)
        }
    )
    lifeline_index = {
        lifeline.ref: index
        for index, lifeline in enumerate(view.lifelines)
    }
    time_index = {time: index for index, time in enumerate(times)}
    state_by_position: dict[
        tuple[str, int], list[TimeSpaceStateChange]
    ] = {}
    for change in view.state_changes:
        state_by_position.setdefault(
            (change.lifeline, change.time), []
        ).append(change)
    lines = [
        "digraph transaction_time_space {",
        "  rankdir=TB;",
        f"  label={_dot_quote(view.name + ' · transaction time-space')};",
        '  labelloc="t";',
        '  graph [bgcolor="white", nodesep=0.7, ranksep=0.72, '
        'splines=line, pad=0.2, newrank=true, forcelabels=true];',
        '  node [fontname="sans-serif", fontsize=10];',
        '  edge [fontname="sans-serif", fontsize=9];',
        '  time_header [shape=plaintext, group="time", label="time"];',
    ]
    for index, lifeline in enumerate(view.lifelines):
        label = (
            f"{lifeline.label}\n{lifeline.kind} · {lifeline.ref}"
            f"{_display_suffix(lifeline.display_fields)}"
        )
        lines.append(
            f"  lifeline_{index} [shape=box, style=\"rounded,filled\", "
            f'group="lifeline_{index}", '
            f'fillcolor="#eef5ff", color="#3169a8", '
            f"label={_dot_quote(label)}];"
        )
    lines.append(
        "  { rank=same; time_header; "
        + "; ".join(
            f"lifeline_{index}" for index in range(len(view.lifelines))
        )
        + "; }"
    )

    for row, time in enumerate(times):
        lines.append(
            f"  time_{row} [shape=plaintext, "
            'group="time", '
            f"label={_dot_quote(f'{view.time_basis.value} {time}')}];"
        )
        point_ids = []
        for column, lifeline in enumerate(view.lifelines):
            point = f"point_{column}_{row}"
            point_ids.append(point)
            changes = state_by_position.get((lifeline.ref, time), ())
            if changes:
                badges = []
                tooltips = []
                for change in changes:
                    badge = change.display_fields.get("badge")
                    badges.append(
                        str(badge)
                        if isinstance(badge, str) and badge
                        else _state_presentation(change)
                    )
                    tooltips.append(
                        f"{change.event_ref}: "
                        f"{_state_presentation(change)}"
                    )
                lines.append(
                    f"  {point} [shape=point, width=0.10, height=0.10, "
                    f'group="lifeline_{column}", '
                    'fixedsize=true, color="#a87d21", '
                    'fillcolor="#fff7dd", style=filled, '
                    'fontname="sans-serif", fontcolor="#7a5410", '
                    'fontsize=8, label="", '
                    f"xlabel={_dot_quote(chr(10).join(badges))}, "
                    f"tooltip={_dot_quote(chr(10).join(tooltips))}];"
                )
            else:
                lines.append(
                    f"  {point} [shape=point, width=0.07, height=0.07, "
                    f'group="lifeline_{column}", '
                    'fixedsize=true, color="#64748b", label=""];'
                )
        lines.append(
            "  { rank=same; time_"
            + str(row)
            + "; "
            + "; ".join(point_ids)
            + "; }"
        )
        lines.append(
            "  time_"
            + str(row)
            + " -> "
            + " -> ".join(point_ids)
            + " [style=invis, weight=100];"
        )

    for column in range(len(view.lifelines)):
        path = [f"lifeline_{column}"] + [
            f"point_{column}_{row}" for row in range(len(times))
        ]
        lines.append(
            "  "
            + " -> ".join(path)
            + ' [arrowhead=none, style=dashed, color="#94a3b8", '
            'weight=20];'
        )

    for message in view.messages:
        source = lifeline_index[message.source]
        destination = lifeline_index[message.destination]
        row = time_index[message.time]
        color, _legend_label = _message_style(message)
        lines.append(
            f"  point_{source}_{row} -> point_{destination}_{row} "
            f'[constraint=false, color="{color}", fontcolor="{color}", '
            'penwidth=1.7, '
            f"xlabel={_dot_quote(_message_label(message))}];"
        )

    lines.extend(
        (
            f"  legend [shape=plain, label={_time_space_legend(view)}];",
            '  boundary [shape=note, color="#777777", '
            'label="Semantic event position only\\n'
            'not pins, cycles, or RTL timing"];',
            "  { rank=same; legend; boundary; }",
            (
                f"  point_0_{len(times) - 1} -> legend "
                '[style=invis, minlen=1];'
            ),
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def _event_records(
    view: TransactionTimeSpaceView,
) -> tuple[tuple[str, int, str, str, str], ...]:
    records: list[tuple[str, int, str, str, str]] = []
    for message in view.messages:
        location = f"{message.source} → {message.destination}"
        qualifiers = " · ".join(
            value
            for value in (message.channel, message.lane)
            if value is not None
        )
        details = message.label
        if qualifiers:
            details += f"\n{qualifiers}"
        details += _presentation_suffix(message.display_fields)
        records.append(
            (
                message.event_ref,
                message.time,
                message.operation_ref,
                location,
                details,
            )
        )
    for change in view.state_changes:
        records.append(
            (
                change.event_ref,
                change.time,
                change.operation_ref,
                change.lifeline,
                f"{change.label}\n{_state_presentation(change)}",
            )
        )
    return tuple(sorted(records, key=lambda item: (item[1], item[0])))


def transaction_causal_dot(view: TransactionTimeSpaceView) -> str:
    """Render only caller-supplied causal edges; no edge is inferred."""

    if not isinstance(view, TransactionTimeSpaceView):
        raise TypeError("causal renderer requires TransactionTimeSpaceView")
    records = _event_records(view)
    if view.causal_edges:
        referenced = {
            event_ref
            for edge in view.causal_edges
            for event_ref in (
                edge.source_event_ref,
                edge.destination_event_ref,
            )
        }
        records = tuple(
            record for record in records if record[0] in referenced
        )
    event_ids = {
        event_ref: f"event_{index}"
        for index, (event_ref, *_rest) in enumerate(records)
    }
    lines = [
        "digraph transaction_causality {",
        "  rankdir=TB;",
        f"  label={_dot_quote(view.name + ' · explicit causality')};",
        '  labelloc="t";',
        '  graph [bgcolor="white", nodesep=0.45, ranksep=0.72, '
        'splines=polyline, pad=0.2];',
        '  node [shape=box, style="rounded,filled", '
        'fillcolor="#eef5ff", color="#3169a8", '
        'fontname="sans-serif", fontsize=10];',
        '  edge [color="#3169a8", fontname="sans-serif", fontsize=9];',
    ]
    for event_ref, time, operation_ref, location, details in records:
        label = (
            f"[{view.time_basis.value} {time}] {details}\n"
            f"event={_compact_ref(event_ref)} · "
            f"op={_compact_ref(operation_ref)}\n{location}"
        )
        lines.append(
            f"  {event_ids[event_ref]} [label={_dot_quote(label)}];"
        )
    for edge in view.causal_edges:
        lines.append(
            f"  {event_ids[edge.source_event_ref]} -> "
            f"{event_ids[edge.destination_event_ref]} "
            f"[label={_dot_quote(edge.reason)}];"
        )
    if not view.causal_edges:
        lines.append(
            '  note [shape=note, fillcolor="#fff7dd", color="#a87d21", '
            'label="No explicit causal edge supplied\\n'
            '没有提供显式因果边"];'
        )
    lines.extend(
        (
            '  boundary [shape=note, fillcolor="white", color="#777777", '
            'label="Edges are supplied evidence\\n'
            'time proximity does not infer causality"];',
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def _wave_cells(cells: list[list[str]]) -> tuple[str, list[str]]:
    wave = []
    data = []
    for values in cells:
        if values:
            wave.append("=")
            data.append(" | ".join(values))
        else:
            wave.append("0")
    return "".join(wave), data


def _timeline_event_token(event_ref: str) -> str:
    parts = event_ref.split(":")
    if len(parts) >= 2 and parts[-2] == "message":
        return "m" + parts[-1]
    if len(parts) >= 3 and parts[-3] == "state":
        return "s" + parts[-2]
    return _compact_ref(event_ref)


def _accepted_semantic_wavejson(
    view: TransactionTimeSpaceView,
    times: list[int],
) -> dict[str, object]:
    time_columns = {time: index for index, time in enumerate(times)}
    signal: list[object] = [
        {
            "name": view.time_basis.value.upper().replace("_", " "),
            "wave": "=" * len(times),
            "data": [str(time) for time in times],
        }
    ]
    for lifeline in view.lifelines:
        lanes: dict[str, list[list[str]]] = {}

        def add(lane_name: str, time: int, label: str) -> None:
            lane = lanes.setdefault(
                lane_name,
                [[] for _time in times],
            )
            lane[time_columns[time]].append(label)

        for message in view.messages:
            if message.destination != lifeline.ref:
                continue
            channel = message.channel or message.lane or "MESSAGE"
            label = (
                f"{_timeline_event_token(message.event_ref)} "
                f"{message.label}"
            )
            add(f"{lifeline.ref} · {channel}", message.time, label)
        for change in view.state_changes:
            if change.lifeline != lifeline.ref:
                continue
            badge = change.display_fields.get("badge")
            label = (
                str(badge)
                if isinstance(badge, str) and badge
                else _state_presentation(change)
            )
            add(
                f"{lifeline.ref} · STATE",
                change.time,
                f"{_timeline_event_token(change.event_ref)} {label}",
            )

        for lane_name, cells in lanes.items():
            wave, data = _wave_cells(cells)
            signal.append(
                {
                    "name": lane_name,
                    "wave": wave,
                    "data": data,
                }
            )

    basis_label = view.time_basis.value.replace("_", " ")
    return {
        "signal": signal,
        "head": {
            "text": f"{view.name} · accepted semantic events",
        },
        "foot": {
            "text": (
                f"1 column = 1 observed {basis_label} slot · "
                "SEMANTIC EVENTS ONLY · NOT PINS/CYCLES/RTL"
            ),
        },
        "config": {
            "hscale": 4 if len(times) <= 12 else (3 if len(times) <= 20 else 2),
        },
    }


def transaction_semantic_wavejson(
    view: TransactionTimeSpaceView,
) -> dict[str, object]:
    """Render an event-level WaveJSON timeline, not a pin waveform."""

    if not isinstance(view, TransactionTimeSpaceView):
        raise TypeError(
            "semantic timeline renderer requires TransactionTimeSpaceView"
        )
    times = sorted(
        {
            item.time
            for item in (*view.messages, *view.state_changes)
        }
    )
    if view.messages and all(
        message.observation_point is MessageObservationPoint.ACCEPTANCE
        for message in view.messages
    ):
        return _accepted_semantic_wavejson(view, times)
    time_columns = {time: index for index, time in enumerate(times)}
    signal: list[object] = [
        {
            "name": view.time_basis.value.upper().replace("_", " "),
            "wave": "=" * len(times),
            "data": [str(time) for time in times],
        }
    ]

    for lifeline in view.lifelines:
        lanes: dict[str, list[list[str]]] = {}

        def add(lane_name: str, time: int, label: str) -> None:
            lane = lanes.setdefault(
                lane_name,
                [[] for _time in times],
            )
            lane[time_columns[time]].append(label)

        for message in view.messages:
            qualifier_items = []
            for item in (message.channel, message.lane):
                if item is not None and item.lower() not in {
                    value.lower() for value in qualifier_items
                }:
                    qualifier_items.append(item)
            qualifiers = " · ".join(qualifier_items)
            lane_base = qualifiers or "MESSAGE"
            fields = _presentation_suffix(message.display_fields).replace(
                "\n", " · "
            )
            accept_only = (
                message.observation_point
                is MessageObservationPoint.ACCEPTANCE
            )
            if accept_only:
                if message.destination == lifeline.ref:
                    add(
                        f"{lane_base} / accept",
                        message.time,
                        f"{message.label} ← {message.source} · "
                        f"{_compact_ref(message.event_ref)}{fields}",
                    )
                continue
            if message.source == message.destination == lifeline.ref:
                add(
                    f"{lane_base} / self",
                    message.time,
                    f"{message.label} · {message.event_ref}{fields}",
                )
            else:
                if message.source == lifeline.ref:
                    add(
                        f"{lane_base} / tx",
                        message.time,
                        f"{message.label} → {message.destination} · "
                        f"{message.event_ref}{fields}",
                    )
                if message.destination == lifeline.ref:
                    add(
                        f"{lane_base} / rx",
                        message.time,
                        f"{message.label} ← {message.source} · "
                        f"{message.event_ref}{fields}",
                    )
        for change in view.state_changes:
            if change.lifeline == lifeline.ref:
                badge = change.display_fields.get("badge")
                state_text = (
                    badge
                    if isinstance(badge, str) and badge
                    else _state_presentation(change)
                )
                add(
                    "STATE",
                    change.time,
                    f"{state_text} · "
                    f"{_compact_ref(change.event_ref)}",
                )

        rows: list[object] = []
        if not lanes:
            rows.append(
                {
                    "name": "EVENT",
                    "wave": "0" * len(times),
                }
            )
        else:
            for lane_name, cells in lanes.items():
                wave, data = _wave_cells(cells)
                rows.append(
                    {
                        "name": lane_name,
                        "wave": wave,
                        "data": data,
                    }
                )
        signal.append([f"{lifeline.label} ({lifeline.ref})", *rows])

    basis_label = view.time_basis.value.replace("_", " ")
    return {
        "signal": signal,
        "head": {
            "text": f"{view.name} · semantic transaction timeline",
        },
        "foot": {
            "text": (
                f"1 column = 1 observed {basis_label} slot · "
                "SEMANTIC EVENTS ONLY · NOT PINS/CYCLES/RTL"
            ),
        },
        "config": {
            "hscale": 4 if len(times) <= 12 else (3 if len(times) <= 20 else 2),
        },
    }


__all__ = [
    "MessageObservationPoint",
    "TIME_SPACE_VIEW_SCHEMA",
    "TimeSpaceCausalEdge",
    "TimeSpaceLifeline",
    "TimeSpaceMessage",
    "TimeSpaceStateChange",
    "TransactionTimeSpaceView",
    "transaction_causal_dot",
    "transaction_semantic_wavejson",
    "transaction_time_space_dot",
]
