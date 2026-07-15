"""Derive the AXI4 example guide and visual evidence from run results."""

from __future__ import annotations

import html
import json
from itertools import groupby
from typing import Callable, Iterable

from protocol_model import AtomicFrame, CanonicalEvent, ReadyValidSignals

from common import AXI4_CHANNELS, ExecutionMode
from execution import ExampleRun


THEME_LABELS = {
    "lifecycle": ("Lifecycle", "事务生命周期"),
    "geometry": ("Geometry", "burst 与字节几何"),
    "ordering/interleave": ("Ordering / interleave", "顺序与交织"),
    "observation/reset": ("Observation / reset", "采样与复位"),
    "exclusive/profile": ("Exclusive / profile", "独占访问与 profile"),
}


def _groups(runs: tuple[ExampleRun, ...]):
    return tuple(
        (theme, tuple(items))
        for theme, items in groupby(runs, key=lambda item: item.case.theme)
    )


def _status(run: ExampleRun) -> str:
    if not run.expectation_met:
        return (
            f"MISMATCH · {run.case.expected_verdict.value}"
            f"→{run.actual_verdict.value}"
        )
    if run.case.expected_verdict.value == "PASS":
        return "LEGAL · PASS"
    return "EXPECTED · REJECT"


def _status_colors(run: ExampleRun) -> tuple[str, str]:
    if not run.expectation_met:
        return "#FCE8E6", "#A93226"
    if run.case.expected_verdict.value == "PASS":
        return "#E8F5ED", "#176B45"
    return "#FFF1DE", "#9A5B13"


def _theme_rows(runs: tuple[ExampleRun, ...]):
    """Make slide-like rows while keeping the layout useful as cases grow.

    With five themes, the two themes containing the most cases share one row
    and the remaining three share another.  Keeping the taller cards together
    avoids pairing one tall card with an otherwise short row.  Other theme
    counts fall back to stable rows of at most three cards.
    """

    groups = _groups(runs)
    if len(groups) == 5:
        largest = {
            index
            for index, _ in sorted(
                enumerate(groups),
                key=lambda pair: (-len(pair[1][1]), pair[0]),
            )[:2]
        }
        return (
            tuple(group for index, group in enumerate(groups) if index in largest),
            tuple(group for index, group in enumerate(groups) if index not in largest),
        )
    return tuple(
        tuple(groups[start : start + 3])
        for start in range(0, len(groups), 3)
    )


def _stat_cell(
    value: int,
    label_en: str,
    label_zh: str,
    *,
    background: str,
    foreground: str,
) -> str:
    return (
        f'<TD WIDTH="278" HEIGHT="94" BGCOLOR="{background}" '
        f'ALIGN="LEFT" VALIGN="MIDDLE">'
        f'<FONT COLOR="{foreground}" POINT-SIZE="29"><B>{value}</B></FONT>'
        f'<BR ALIGN="LEFT"/><FONT COLOR="{foreground}" POINT-SIZE="10">'
        f'<B>{html.escape(label_en.upper())}</B></FONT>'
        f'<BR ALIGN="LEFT"/><FONT COLOR="{foreground}" POINT-SIZE="10">'
        f'{html.escape(label_zh)}</FONT><BR ALIGN="LEFT"/></TD>'
    )


def _theme_table(
    theme: str,
    theme_runs: tuple[ExampleRun, ...],
    *,
    index: int,
    total: int,
) -> str:
    en, zh = THEME_LABELS[theme]
    rows = [
        '<TR><TD COLSPAN="2" WIDTH="388" HEIGHT="57" '
        'BGCOLOR="#173D59" ALIGN="LEFT" VALIGN="MIDDLE">'
        f'<FONT COLOR="#9FC5DB" POINT-SIZE="9"><B>THEME {index:02d} / '
        f'{total:02d} · {len(theme_runs)} CASES</B></FONT>'
        '<BR ALIGN="LEFT"/><FONT COLOR="white" POINT-SIZE="13"><B>'
        f'{html.escape(en)}  /  {html.escape(zh)}'
        '</B></FONT></TD></TR>'
    ]
    for case_index, run in enumerate(theme_runs, start=1):
        background, foreground = _status_colors(run)
        case_background = "#FFFFFF" if case_index % 2 else "#F7FAFC"
        rows.append(
            f'<TR><TD WIDTH="258" HEIGHT="31" ALIGN="LEFT" '
            f'BGCOLOR="{case_background}">'
            f'<FONT COLOR="#8192A1" POINT-SIZE="9">{case_index:02d}</FONT>'
            f'<FONT COLOR="#233746" POINT-SIZE="10">  '
            f'{html.escape(run.case.name)}</FONT></TD>'
            f'<TD WIDTH="130" ALIGN="CENTER" BGCOLOR="{background}">'
            f'<FONT COLOR="{foreground}" POINT-SIZE="9"><B>'
            f'{html.escape(_status(run))}</B></FONT></TD></TR>'
        )
    return (
        '<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="1" '
        'CELLPADDING="7" BGCOLOR="#D9E3EA">'
        + "".join(rows)
        + "</TABLE>"
    )


def coverage_dot(runs: tuple[ExampleRun, ...]) -> str:
    """Create a publication-ready overview from the executed example runs."""

    groups = _groups(runs)
    legal = sum(run.case.expected_verdict.value == "PASS" for run in runs)
    expected_rejects = len(runs) - legal
    met = sum(run.expectation_met for run in runs)
    evidence_status = (
        f"ALL {met} DECLARED EXPECTATIONS MET"
        if met == len(runs)
        else f"{met} OF {len(runs)} DECLARED EXPECTATIONS MET"
    )

    lines = [
        "digraph axi4_example_coverage {",
        "  rankdir=TB;",
        '  graph [bgcolor="#F4F7F9", nodesep=0.28, ranksep=0.34, '
        'pad=0.28, margin=0, outputorder="edgesfirst", newrank=true];',
        '  node [shape=plain, fontname="Noto Sans CJK SC"];',
        '  edge [color="#F4F7F9", arrowsize=0];',
        '  hero [label=<<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0" '
        'CELLPADDING="0" WIDTH="1190"><TR><TD ALIGN="LEFT">'
        '<FONT COLOR="#1674A8" POINT-SIZE="10"><B>PROTOCOL MODEL  /  '
        '可执行证据</B></FONT></TD></TR><TR><TD HEIGHT="49" ALIGN="LEFT">'
        '<FONT COLOR="#102C40" POINT-SIZE="27"><B>AXI4 EXECUTABLE EXAMPLES</B>'
        '</FONT></TD></TR><TR><TD ALIGN="LEFT">'
        '<FONT COLOR="#587181" POINT-SIZE="12">'
        '从实际模型运行结果派生的场景总览  ·  '
        'An executable view of protocol behavior</FONT></TD></TR>'
        '</TABLE>>];',
    ]
    stat_cells = "".join(
        (
            _stat_cell(
                len(runs),
                "executed scenarios",
                "已执行场景",
                background="#1674A8",
                foreground="#FFFFFF",
            ),
            _stat_cell(
                len(groups),
                "behavior themes",
                "行为主题",
                background="#E5EFF5",
                foreground="#173D59",
            ),
            _stat_cell(
                legal,
                "legal-path cases",
                "合法路径",
                background="#E2F2E8",
                foreground="#176B45",
            ),
            _stat_cell(
                expected_rejects,
                "expected rejects",
                "预期拒绝",
                background="#FCEBD7",
                foreground="#9A5B13",
            ),
        )
    )
    lines.append(
        '  stats [label=<<TABLE BORDER="0" CELLBORDER="0" '
        f'CELLSPACING="10" CELLPADDING="12"><TR>{stat_cells}</TR></TABLE>>];'
    )

    tables_for_theme = {}
    for index, (theme, theme_runs) in enumerate(groups, start=1):
        tables_for_theme[theme] = _theme_table(
            theme,
            theme_runs,
            index=index,
            total=len(groups),
        )

    theme_rows = _theme_rows(runs)
    row_nodes = []
    for row_index, row in enumerate(theme_rows, start=1):
        node = f"theme_row{row_index}"
        row_nodes.append(node)
        cards = "".join(
            '<TD VALIGN="TOP" ALIGN="CENTER">'
            + tables_for_theme[theme]
            + "</TD>"
            for theme, _theme_runs in row
        )
        lines.append(
            f'  {node} [label=<<TABLE BORDER="0" CELLBORDER="0" '
            f'CELLSPACING="10" CELLPADDING="0"><TR>{cards}</TR></TABLE>>];'
        )

    lines.extend(
        (
            '  footer [label=<<TABLE BORDER="0" CELLBORDER="0" '
            'CELLSPACING="0" CELLPADDING="0" WIDTH="1190">'
            '<TR><TD HEIGHT="32" ALIGN="LEFT">'
            f'<FONT COLOR="#1674A8" POINT-SIZE="10"><B>{evidence_status}</B>'
            '</FONT></TD></TR><TR><TD ALIGN="LEFT">'
            '<FONT COLOR="#667E8D" POINT-SIZE="10">SCENARIO EVIDENCE ONLY '
            '— NOT A CLAIM OF AXI4 SPECIFICATION COMPLETENESS OR RTL COMPLIANCE'
            '</FONT></TD></TR><TR><TD ALIGN="LEFT">'
            '<FONT COLOR="#667E8D" POINT-SIZE="10">'
            '仅表示已执行的场景证据，不表示 AXI4 规范完备性或 RTL compliance'
            '</FONT></TD></TR></TABLE>>];',
            "  hero -> stats [style=invis, weight=80];",
        )
    )
    if row_nodes:
        lines.append(
            f"  stats -> {row_nodes[0]} [style=invis, weight=80];"
        )
        for previous, current in zip(row_nodes, row_nodes[1:]):
            lines.append(
                f"  {previous} -> {current} [style=invis, weight=80];"
            )
        lines.append(
            f"  {row_nodes[-1]} -> footer [style=invis, weight=80];"
        )
    else:
        lines.append("  stats -> footer [style=invis, weight=80];")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _bool_wave(values: Iterable[bool]) -> str:
    result: list[str] = []
    previous: bool | None = None
    for value in values:
        result.append("." if previous is value else ("1" if value else "0"))
        previous = value
    return "".join(result)


def _logic_wave(values: Iterable[bool | None]) -> str:
    result: list[str] = []
    sentinel = object()
    previous: bool | None | object = sentinel
    for value in values:
        if value == previous:
            result.append(".")
        elif value is None:
            result.append("x")
        else:
            result.append("1" if value else "0")
        previous = value
    return "".join(result)


def _field_wave(values: Iterable[str | None]) -> tuple[str, list[str]]:
    wave: list[str] = []
    labels: list[str] = []
    idle = False
    for value in values:
        if value is None:
            wave.append("." if idle else "x")
            idle = True
        else:
            wave.append("=")
            labels.append(value)
            idle = False
    return "".join(wave), labels


def _field_lane(
    name: str,
    events: Iterable[CanonicalEvent | None],
    label: Callable[[CanonicalEvent], str],
) -> dict[str, object]:
    wave, data = _field_wave(
        None if event is None else label(event) for event in events
    )
    return {"name": name, "wave": wave, "data": data}


def _event_label(event: CanonicalEvent) -> str:
    payload = event.payload
    if event.kind in {"AW", "AR"}:
        return (
            f"ID{event.key} A=0x{int(payload['addr']):x} "
            f"N={int(payload['len']) + 1} "
            f"S={1 << int(payload['size'])}B {payload['burst']}"
        )
    if event.kind == "W":
        return (
            f"D=0x{int(payload['data']):x} "
            f"S=0x{int(payload['strb']):x} L={int(payload['last'])}"
        )
    if event.kind == "R":
        return (
            f"ID{event.key} D=0x{int(payload['data']):x} "
            f"{payload['resp']} L={int(payload['last'])}"
        )
    if event.kind == "B":
        return f"ID{event.key} {payload['resp']}"
    return event.short()


def _wave_event_label(event: CanonicalEvent) -> str:
    """Keep adjacent event cells readable without dropping key AXI fields."""

    payload = event.payload
    response = {
        "OKAY": "OK",
        "EXOKAY": "EXOK",
        "SLVERR": "SLV",
        "DECERR": "DEC",
    }
    burst = {"FIXED": "F", "INCR": "I", "WRAP": "W"}

    def compact_hex(value: object) -> str:
        digits = f"{int(value):x}"
        if len(digits) > 8:
            digits = f"{digits[:4]}…{digits[-4:]}"
        return "0x" + digits

    if event.kind in {"AW", "AR"}:
        return (
            f"{event.key}@{compact_hex(payload['addr'])}:"
            f"{int(payload['len']) + 1}x{1 << int(payload['size'])}"
            f"{burst.get(str(payload['burst']), payload['burst'])}"
        )
    if event.kind == "W":
        return (
            f"D{compact_hex(payload['data'])}/S{int(payload['strb']):x}/"
            f"L{int(payload['last'])}"
        )
    if event.kind == "R":
        return (
            f"{event.key}:D{compact_hex(payload['data'])}/"
            f"{response.get(str(payload['resp']), payload['resp'])}/"
            f"L{int(payload['last'])}"
        )
    if event.kind == "B":
        return f"{event.key}:{response.get(str(payload['resp']), payload['resp'])}"
    return event.short()


def _observation_waveform(run: ExampleRun) -> dict[str, object]:
    frames = list(run.case.actions)
    if not all(isinstance(frame, AtomicFrame) for frame in frames):
        raise TypeError(f"observation case {run.case.name!r} has non-frame input")
    signal: list[object] = [
        {"name": "ACLK", "wave": "p" + "." * (len(frames) - 1)},
        {
            "name": "ARESETn",
            "wave": _bool_wave(not bool(frame.get("reset")) for frame in frames),
        },
    ]
    for channel in AXI4_CHANNELS:
        lanes = [frame.get(channel) for frame in frames]
        assert all(isinstance(item, ReadyValidSignals) for item in lanes)
        if not any(item.valid or item.event is not None for item in lanes):
            continue
        valid = [item.valid for item in lanes]
        ready = [item.ready for item in lanes]
        events = [item.event if item.valid else None for item in lanes]
        group: list[object] = [
            channel,
            {"name": "VALID", "wave": _bool_wave(valid)},
            {"name": "READY", "wave": _bool_wave(ready)},
            {
                "name": "FIRE",
                "wave": _bool_wave(
                    item.valid and item.ready for item in lanes
                ),
            },
        ]
        if channel in {"AW", "AR"}:
            group.extend(
                (
                    _field_lane("ID", events, lambda event: str(event.key)),
                    _field_lane(
                        "ADDR", events,
                        lambda event: f"0x{int(event.payload['addr']):08x}",
                    ),
                    _field_lane(
                        "LEN", events,
                        lambda event: (
                            f"{int(event.payload['len'])} "
                            f"({int(event.payload['len']) + 1} beats)"
                        ),
                    ),
                    _field_lane(
                        "SIZE", events,
                        lambda event: (
                            f"{int(event.payload['size'])} "
                            f"({1 << int(event.payload['size'])}B)"
                        ),
                    ),
                    _field_lane(
                        "BURST", events,
                        lambda event: str(event.payload["burst"]),
                    ),
                )
            )
        elif channel == "W":
            group.extend(
                (
                    _field_lane(
                        "DATA", events,
                        lambda event: f"0x{int(event.payload['data']):016x}",
                    ),
                    _field_lane(
                        "WSTRB", events,
                        lambda event: f"0x{int(event.payload['strb']):02x}",
                    ),
                    {
                        "name": "WLAST",
                        "wave": _logic_wave(
                            None if event is None
                            else bool(event.payload["last"])
                            for event in events
                        ),
                    },
                )
            )
        elif channel == "R":
            group.extend(
                (
                    _field_lane("ID", events, lambda event: str(event.key)),
                    _field_lane(
                        "DATA", events,
                        lambda event: f"0x{int(event.payload['data']):x}",
                    ),
                    _field_lane(
                        "RESP", events,
                        lambda event: str(event.payload["resp"]),
                    ),
                    {
                        "name": "RLAST",
                        "wave": _logic_wave(
                            None if event is None
                            else bool(event.payload["last"])
                            for event in events
                        ),
                    },
                )
            )
        else:
            group.extend(
                (
                    _field_lane("ID", events, lambda event: str(event.key)),
                    _field_lane(
                        "RESP", events,
                        lambda event: str(event.payload["resp"]),
                    ),
                )
            )
        signal.append(group)
    if run.fault is not None:
        signal.append(
            {
                "name": "MODEL FAULT",
                "wave": "0" + "." * max(0, len(frames) - 2) + "1"
                if len(frames) > 1 else "1",
            }
        )
    return {
        "signal": signal,
        "head": {
            "text": f"{run.case.title_en} / {run.case.title_zh}",
        },
        "foot": {
            "text": (
                "ARESETn = !reset · FIRE = VALID & READY · "
                "protocol-model observation, not RTL/VCD"
            ),
        },
        "config": {
            "hscale": max(
                4 if run.case.deep_dive else 3,
                min(10, (24 + max(1, len(frames)) - 1) // max(1, len(frames))),
            )
        },
    }


def _event_waveform(run: ExampleRun) -> dict[str, object]:
    events = list(run.case.actions)
    if not all(isinstance(event, CanonicalEvent) for event in events):
        raise TypeError(f"event case {run.case.name!r} has non-event input")
    step_wave, step_data = _field_wave(str(index) for index in range(len(events)))
    longest_label = max((len(_wave_event_label(event)) for event in events), default=1)
    signal: list[object] = [
        {"name": "MODEL STEP", "wave": step_wave, "data": step_data},
    ]
    for channel in AXI4_CHANNELS:
        channel_events = [event if event.kind == channel else None for event in events]
        if not any(event is not None for event in channel_events):
            continue
        signal.append(
            [
                channel,
                _field_lane("CanonicalEvent", channel_events, _wave_event_label),
            ]
        )
    committed = len(run.accepted_events)
    signal.append(
        {
            "name": "COMMITTED",
            "wave": _bool_wave(index < committed for index in range(len(events))),
        }
    )
    if run.fault is not None:
        signal.append(
            {
                "name": "MODEL FAULT",
                "wave": _logic_wave(
                    True if index == committed else None
                    for index in range(len(events))
                ),
            }
        )
    return {
        "signal": signal,
        "head": {
            "text": f"{run.case.title_en} / {run.case.title_zh}",
        },
        "foot": {
            "text": (
                "1 column = 1 CanonicalEvent · MODEL ORDER ONLY · "
                "NOT PINS/CYCLES/RTL / 非引脚时序"
            ),
        },
        "config": {
            "hscale": max(
                4 if len(events) > 8 else 2,
                min(
                    18,
                    (18 + max(1, len(events)) - 1) // max(1, len(events)),
                ),
                min(6, (longest_label + 4) // 5),
            )
        },
    }


def waveform_wavejson(run: ExampleRun) -> dict[str, object]:
    if run.case.mode is ExecutionMode.OBSERVATION:
        return _observation_waveform(run)
    return _event_waveform(run)


def _quote(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _diagnostic_context(action: CanonicalEvent | AtomicFrame) -> str:
    if isinstance(action, CanonicalEvent):
        return "rejected input / 被拒输入\n" + _event_label(action)
    active = []
    for channel in AXI4_CHANNELS:
        lane = action.get(channel)
        if isinstance(lane, ReadyValidSignals) and lane.valid and lane.event is not None:
            active.append(_event_label(lane.event))
    details = "\n".join(active) if active else "no active channel / 无活动通道"
    return f"diagnostic frame / 诊断帧 · tick {action.tick}\n{details}"


def causality_dot(run: ExampleRun) -> str:
    rank_direction = "TB" if len(run.accepted_events) > 8 else "LR"
    lines = [
        "digraph axi4_case {",
        f"  rankdir={rank_direction};",
        f"  label={_quote(run.case.title_en + ' / ' + run.case.title_zh)};",
        '  labelloc="t";',
        '  graph [bgcolor="white", nodesep=0.4, ranksep=0.65, splines=polyline, pad=0.2];',
        '  node [shape=box, style="rounded,filled", fillcolor="#eef5ff", color="#3169a8", fontname="sans-serif", fontsize=10];',
        '  edge [color="#3169a8", fontname="sans-serif", fontsize=9];',
    ]
    for event in run.accepted_events:
        if event.trace_index is None:
            continue
        lines.append(
            f"  event{event.trace_index} [label="
            f"{_quote(f'[{event.trace_index}] {_event_label(event)}')}];"
        )
    for before, after in run.causal_edges:
        lines.append(
            f'  event{before} -> event{after} [label="causes / 因果"];'
        )
    if run.fault is not None:
        label = f"REJECTED / 已拒绝\n{run.fault.rule}\n{run.fault.reason}"
        context = _diagnostic_context(run.case.actions[-1])
        lines.append(
            '  context [shape=note, style="filled", fillcolor="#f4f5f6", '
            f'color="#7c8790", label={_quote(context)}];'
        )
        lines.append(
            '  fault [shape=octagon, style="filled", fillcolor="#ffe9e7", '
            f'color="#b33a2b", label={_quote(label)}];'
        )
        lines.append(
            '  context -> fault [style=dashed, color="#777777", '
            'label="diagnostic context / 诊断上下文（非因果边）"];'
        )
    if not run.accepted_events and run.fault is None:
        lines.append(
            '  note [shape=note, fillcolor="#fff8dc", color="#9b7b22", '
            'label="No accepted event in this trace / 本轨迹没有已接受事件"];'
        )
    elif not run.causal_edges and run.fault is None:
        lines.append(
            '  note [shape=note, fillcolor="#fff8dc", color="#9b7b22", '
            'label="No cross-event causal edge in this trace / 本轨迹没有跨事件因果边"];'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def scope_dot() -> str:
    return """digraph demo_scope {
  rankdir=LR;
  label="AXI4 executable example path / AXI4 可执行示例路径";
  labelloc="t";
  graph [bgcolor="white", nodesep=0.5, ranksep=0.7, splines=polyline];
  node [shape=box, style="rounded,filled", fontname="sans-serif", margin="0.15,0.10"];
  inputs [label="24 named inputs\\nCanonicalEvent or AtomicFrame\\n24 个具名输入轨迹", fillcolor="#f7f0ff", color="#7652a8"];
  observation [label="Optional observation lowering\\nready/valid + reset\\n可选观察层下沉", fillcolor="#fff7dd", color="#a87d21"];
  link [label="AXI4 LinkProtocol session\\ngeometry · join · lifecycle\\n几何 · 关联 · 生命周期", fillcolor="#eaf8ef", color="#2d8650"];
  evidence [label="Per-case evidence\\nresult · waveform · causality\\n结果 · 波形 · 因果关系", fillcolor="#fff0ee", color="#a84a3d"];
  inputs -> observation -> link -> evidence;
  boundary [shape=note, label="Event-level waves show model sequence; AtomicFrame waves show protocol observations.\\nNeither is an RTL pin/VCD capture.\\n事件波形展示模型顺序；AtomicFrame 波形展示协议观察，均非 RTL/VCD。", fillcolor="#ffffff", color="#777777"];
  boundary -> observation [style=dashed, arrowhead=none, color="#777777"];
}
"""


def network_dot(system) -> str:
    link = next(iter(system.links.values()))
    manager = link.endpoints["manager"]
    subordinate = link.endpoints["subordinate"]
    manager_dut = system.virtual_duts[manager.dut]
    subordinate_dut = system.virtual_duts[subordinate.dut]
    manager_port = manager_dut.port(manager.port)
    subordinate_port = subordinate_dut.port(subordinate.port)
    manager_label = (
        f"{manager_dut.name}\nVirtualDut · initiating / 主动发起\n"
        f"port {manager_port.name}"
    )
    subordinate_label = (
        f"{subordinate_dut.name}\nVirtualDut · addressable / 可寻址\n"
        f"port {subordinate_port.name}"
    )
    return f'''digraph demo_network {{
  rankdir=LR;
  label={_quote(system.name + ": structural context / 结构上下文")};
  labelloc="t";
  graph [bgcolor="white", pad=0.25, nodesep=0.55, ranksep=0.75, splines=polyline];
  node [shape=box, style="rounded,filled", fontname="sans-serif", margin="0.18,0.12", penwidth=1.5];
  requester [label={_quote(manager_label)}, fillcolor="#eef5ff", color="#3169a8"];
  link [label="axi4-link\\nAXI4 LinkProtocol\\nAW · W · B · AR · R", fillcolor="#eaf8ef", color="#2d8650"];
  endpoint [label={_quote(subordinate_label)}, fillcolor="#fff4e7", color="#b56b21"];
  requester -> link [dir=both, color="#3169a8", penwidth=1.6];
  link -> endpoint [dir=both, color="#b56b21", penwidth=1.6];
  note [shape=note, label="Structural context only: examples execute protocol semantics, not endpoint backends.\\n仅表示结构上下文：示例执行协议语义，不执行端点 backend。", fillcolor="#ffffff", color="#777777", fontsize=10];
  note -> link [style=dashed, arrowhead=none, color="#777777", constraint=false];
}}
'''


def _case_rows(runs: tuple[ExampleRun, ...], *, language: str) -> str:
    rows = []
    for run in runs:
        title = run.case.title_zh if language == "zh-CN" else run.case.title_en
        claim = run.case.claim_zh if language == "zh-CN" else run.case.claim_en
        badge = " **精讲**" if language == "zh-CN" and run.case.deep_dive else ""
        badge = " **DEEP DIVE**" if language == "en" and run.case.deep_dive else badge
        rule = run.fault.rule if run.fault is not None else "—"
        rows.append(
            f"| `{run.case.name}`{badge}<br>{title}<br><sub>{claim}</sub> "
            f"| `{run.case.mode.value}` "
            f"| `{run.case.expected_verdict.value}` → `{run.actual_verdict.value}` "
            f"| `{rule}` "
            f"| [wave](cases/{run.case.name}/waveform.svg) · "
            f"[cause](cases/{run.case.name}/causality.svg) · "
            f"[JSON](cases/{run.case.name}/result.json) |"
        )
    return "\n".join(rows)


def _theme_sections(runs: tuple[ExampleRun, ...], *, language: str) -> str:
    sections = []
    for theme, theme_runs in _groups(runs):
        en, zh = THEME_LABELS[theme]
        label = zh if language == "zh-CN" else en
        table = (
            f"## {label}\n\n"
            "| Case | Input view | Expected → observed | Rule | Evidence |\n"
            "| --- | --- | --- | --- | --- |\n"
            + _case_rows(theme_runs, language=language)
        )
        details = []
        for run in theme_runs:
            if run.case.deep_dive:
                continue
            title = run.case.title_zh if language == "zh-CN" else run.case.title_en
            claim = run.case.claim_zh if language == "zh-CN" else run.case.claim_en
            if language == "zh-CN":
                summary = f"查看 `{run.case.name}` 的波形与因果图"
                note = (
                    "事件级波形的一列是一笔 CanonicalEvent，不表示 pin/cycle。"
                    if run.case.mode is ExecutionMode.LINK
                    else "该波形投影 AtomicFrame 中的 ready/valid 采样。"
                )
            else:
                summary = f"View waveform and causality for `{run.case.name}`"
                note = (
                    "One event-level column is one CanonicalEvent, not pin/cycle timing."
                    if run.case.mode is ExecutionMode.LINK
                    else "This waveform projects ready/valid samples from AtomicFrame."
                )
            details.append(
                f"<details>\n<summary>{summary}</summary>\n\n"
                f"**{title}.** {claim}\n\n{note}\n\n"
                f"![{title} waveform](cases/{run.case.name}/waveform.svg)\n\n"
                f"![{title} causality](cases/{run.case.name}/causality.svg)\n\n"
                f"[result.json](cases/{run.case.name}/result.json) · "
                f"[WaveJSON](sources/cases/{run.case.name}/waveform.json) · "
                f"[DOT](sources/cases/{run.case.name}/causality.dot)\n\n"
                "</details>"
            )
        sections.append(table + "\n\n" + "\n\n".join(details))
    return "\n\n".join(sections)


def _deep_dive_sections(runs: tuple[ExampleRun, ...], *, language: str) -> str:
    selected = [run for run in runs if run.case.deep_dive]
    sections = []
    for run in selected:
        title = run.case.title_zh if language == "zh-CN" else run.case.title_en
        if language == "zh-CN":
            if run.case.name == "write-narrow-unaligned-incr":
                explanation = (
                    "这条轨迹从复位开始，AWLEN=3 声明四拍写传输。四个 W beat "
                    "逐拍展示非对齐窄传输的 WSTRB 轮换，末拍 WLAST=1，随后 B "
                    "完成事务并释放相关资源。"
                )
            else:
                explanation = (
                    "这条轨迹保留同一 AW 描述符，只把第一拍 WLAST 置为 1。"
                    "模型由 AWLEN=3 推导此处仍需后续三拍，因此以 "
                    f"`{run.fault.rule if run.fault else '—'}` 拒绝本次原子提交。"
                )
            reset_note = (
                "波形中的 `ARESETn` 是模型内部 active-high `reset` 的取反展示；"
                "`FIRE` 由 `VALID && READY` 派生，不是额外 RTL 采样。"
            )
        else:
            if run.case.name == "write-narrow-unaligned-incr":
                explanation = (
                    "The trace starts in reset. AWLEN=3 declares four write "
                    "transfers; the four W beats expose rotating WSTRB masks for "
                    "the unaligned narrow access, the final beat asserts WLAST, "
                    "and B completes and releases the transaction resources."
                )
            else:
                explanation = (
                    "The trace keeps the same AW descriptor and changes only the "
                    "first beat's WLAST to 1. From AWLEN=3 the model derives that "
                    "three beats remain and rejects the atomic commit under "
                    f"`{run.fault.rule if run.fault else '—'}`."
                )
            reset_note = (
                "`ARESETn` is the AXI-facing inverse of the model's normalized "
                "active-high `reset`; `FIRE` is derived as `VALID && READY`, not "
                "sampled from additional RTL pins."
            )
        sections.append(
            f"### `{run.case.name}` — {title}\n\n"
            f"{explanation}\n\n{reset_note}\n\n"
            f"![{title} waveform](cases/{run.case.name}/waveform.svg)\n\n"
            f"![{title} causality](cases/{run.case.name}/causality.svg)\n\n"
            f"[result.json](cases/{run.case.name}/result.json) · "
            f"[WaveJSON](sources/cases/{run.case.name}/waveform.json) · "
            f"[DOT](sources/cases/{run.case.name}/causality.dot)"
        )
    return "\n\n".join(sections)


def index_report(runs: tuple[ExampleRun, ...], *, language: str) -> str:
    met = sum(item.expectation_met for item in runs)
    legal = sum(item.case.expected_verdict.value == "PASS" for item in runs)
    rejected = len(runs) - legal
    sections = _theme_sections(runs, language=language)
    deep_dives = _deep_dive_sections(runs, language=language)
    if language == "zh-CN":
        return f"""# AXI4 可执行示例导航

这是一套统一的 AXI4 介绍例：同一个具名 runner 执行 `{len(runs)}` 个场景，并为每个场景发布 `result.json`、波形和因果图。其中 `{legal}` 个展示合法路径，`{rejected}` 个展示预期拒绝；表中的 `FAIL` 是协议语义判定，不表示发布失败。

![按主题组织的执行证据](coverage.svg)

![全部场景共享的点到点结构](topology.svg)

![模型证据如何产生](evidence-path.svg)

场景有两种诚实的观察口径：`link-events` 的每一列是一笔依次送入模型的 `CanonicalEvent`，不表示 AXI pin、周期或 VALID/READY；`atomic-frames` 才展示一个采样沿内的 ready/valid lane，并把内部 reset 取反为 AXI 的 `ARESETn`。

{sections}

## 两个精讲场景

这两项仍是上表中的同一 case、同一次执行，不另计场景，也没有第二套 checker。它们只是使用更丰富的 `AtomicFrame` 输入和展开说明。

{deep_dives}

## 证据边界与追溯

本次 `{met}/{len(runs)}` 个场景满足各自声明的期望。场景数量表示已经执行的代表性样本，不等价于 AXI4 规范条款覆盖率，也不是 RTL compliance 结论。聚合数据见 [examples.json](examples.json)，生成来源见 [provenance.json](provenance.json)，文件清单见 [manifest.json](manifest.json)。
"""
    if language != "en":
        raise ValueError(f"unsupported language {language!r}")
    return f"""# AXI4 executable example guide

This is one unified AXI4 introduction set. A single named runner executes `{len(runs)}` cases and publishes `result.json`, a waveform, and a causality graph for every case. `{legal}` cases exercise legal paths and `{rejected}` exercise expected rejection. `FAIL` is a protocol-semantic verdict, not a failed publication.

![Executed evidence organized by theme](coverage.svg)

![Point-to-point structure shared by all cases](topology.svg)

![How the model evidence is produced](evidence-path.svg)

The set uses two honest observation views. In `link-events`, one column is one sequential `CanonicalEvent` input; it does not represent AXI pins, cycles, or VALID/READY. Only `atomic-frames` shows ready/valid lanes sampled at an edge, projecting the normalized internal reset as AXI `ARESETn`.

{sections}

## Two narrated deep dives

These are the same cases and the same executions already listed above. They do not increase the case count or introduce a second checker; they only use richer `AtomicFrame` input and expanded explanation.

{deep_dives}

## Evidence boundary and provenance

`{met}/{len(runs)}` cases met their declared expectations. Case count describes representative samples that were executed; it is not AXI4 requirement coverage or RTL compliance evidence. See [examples.json](examples.json) for aggregation, [provenance.json](provenance.json) for origin, and [manifest.json](manifest.json) for the artifact inventory.
"""


def example_set_record(runs: tuple[ExampleRun, ...], compact_records):
    themes = []
    for theme, theme_runs in _groups(runs):
        en, zh = THEME_LABELS[theme]
        themes.append(
            {
                "theme": theme,
                "label": {"en": en, "zh-CN": zh},
                "cases": [item.case.name for item in theme_runs],
            }
        )
    return {
        "schema": "protocol-model.showcase.axi4-examples/v1",
        "scope": "representative executable scenarios",
        "coverage_statement": (
            "scenario evidence only; case count is not specification coverage"
        ),
        "themes": themes,
        "cases": list(compact_records),
    }


__all__ = [
    "causality_dot",
    "coverage_dot",
    "example_set_record",
    "index_report",
    "network_dot",
    "scope_dot",
    "waveform_wavejson",
]
