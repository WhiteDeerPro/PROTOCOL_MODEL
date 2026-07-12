"""Graphviz views of concrete protocol causality."""

from __future__ import annotations

import json
from typing import Iterable

from protocol_model.core import CanonicalEvent
from protocol_model.engine import ExecutionTrace


def _quoted(value: str) -> str:
    return json.dumps(value)


def _compact_hex(value: object, width: int) -> str:
    raw = format(int(value), f"0{(width + 3) // 4}x")
    shown = f"{raw[:2]}..{raw[-2:]}" if len(raw) > 4 else raw
    return f"0x{shown} '{width}"


def _compact_event(
    event: CanonicalEvent, *, address_width: int = 32, data_width: int = 64
) -> str:
    channel = event.kind.split("_", 1)[0]
    parts = [channel]
    if event.key is not None:
        parts.append(f"id={event.key}")
    for name in ("addr", "len", "size", "burst", "data", "strb", "resp", "last"):
        if name not in event.payload:
            continue
        value = event.payload[name]
        if name == "addr":
            parts.append(f"addr={_compact_hex(value, address_width)}")
        elif name == "data":
            parts.append(f"data={_compact_hex(value, data_width)}")
        elif name == "last":
            if value:
                parts.append("LAST")
        else:
            parts.append(f"{name}={value}")
    return "\n".join((" ".join(parts[:2]), " ".join(parts[2:])))


def format_correlated_dot(
    events: Iterable[CanonicalEvent],
    *,
    descriptor_kind: str,
    data_kind: str,
    completion_kind: str,
    title: str = "Correlated burst transaction",
) -> str:
    """Render the semantic join, not incidental monitor callback order."""

    events = tuple(events)
    descriptors = [i for i, event in enumerate(events) if event.kind == descriptor_kind]
    data = [i for i, event in enumerate(events) if event.kind == data_kind]
    completions = [i for i, event in enumerate(events) if event.kind == completion_kind]
    lines = [
        "digraph protocol_causality {",
        "  rankdir=TB;",
        f"  label={_quoted(title)};",
        '  labelloc="t";',
        '  graph [nodesep=0.35, ranksep=0.55, splines=polyline];',
        '  node [shape=box, fontname="monospace", margin="0.08,0.05"];',
    ]
    for index, event in enumerate(events):
        lines.append(f"  e{index} [label={_quoted(_compact_event(event))}];")
    for left, right in zip(data, data[1:]):
        lines.append(f'  e{left} -> e{right} [label="next beat"];')
    if descriptors and data:
        join = "join0"
        lines.append(f'  {join} [shape=diamond, label="AW/W join"];')
        lines.append(f'  e{descriptors[0]} -> {join} [label="descriptor"];')
        lines.append(f'  e{data[-1]} -> {join} [label="complete burst"];')
        if completions:
            lines.append(f'  {join} -> e{completions[0]} [label="B obligation"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def format_execution_dot(
    trace: ExecutionTrace[CanonicalEvent],
    *,
    title: str = "Protocol execution",
    address_width: int = 32,
    data_width: int = 64,
) -> str:
    lines = [
        "digraph protocol_execution {",
        "  rankdir=TB;",
        f"  label={_quoted(title)};",
        '  labelloc="t";',
        '  graph [nodesep=0.35, ranksep=0.55, splines=polyline, newrank=true];',
        '  node [shape=box, fontname="monospace", margin="0.08,0.05"];',
    ]
    colors = {"AW": "lightblue", "W": "lightblue", "B": "lightblue", "AR": "lightgreen", "R": "lightgreen"}
    for index, event in enumerate(trace.events):
        channel = event.kind.split("_", 1)[0]
        color = colors.get(channel, "white")
        lines.append(
            f"  e{index} [style=filled, fillcolor={_quoted(color)}, "
            f"label={_quoted(f'[{index}] ' + _compact_event(event, address_width=address_width, data_width=data_width))}];"
        )
    for step in trace.steps:
        if len(step) > 1:
            lines.append(
                "  { rank=same; " + "; ".join(f"e{node}" for node in step) + "; }"
            )
    for before, after in sorted(trace.causal_graph.edges):
        lines.append(f"  e{before} -> e{after};")
    lines.append("}")
    return "\n".join(lines) + "\n"
