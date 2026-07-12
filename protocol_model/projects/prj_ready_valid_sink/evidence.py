"""Waveform, event causality, topology, and HTML for this Project."""

from __future__ import annotations

from html import escape

from ..base import ProjectSnapshot
from .project import ReadyValidSinkRun


def _bit_wave(values) -> str:
    result = []
    previous = None
    for value in values:
        symbol = "1" if value else "0"
        result.append("." if symbol == previous else symbol)
        previous = symbol
    return "".join(result)


def ready_valid_wavejson(run: ReadyValidSinkRun, *, title: str):
    observations = run.observations
    valid = [item.observation.valid for item in observations]
    ready = [item.observation.ready for item in observations]
    reset = [item.asserted for item in observations]
    fire = [v and r and not rst for v, r, rst in zip(valid, ready, reset)]
    data_wave = []
    data = []
    previous = object()
    for item in observations:
        sample = item.observation
        if not sample.valid:
            data_wave.append("." if data_wave else "0")
            continue
        value = int(sample.event.payload["data"])
        if value == previous:
            data_wave.append(".")
        else:
            data_wave.append("=")
            data.append(f"0x{value:02x}")
        previous = value
    return {
        "signal": [
            {"name": "CLK", "wave": "p" + "." * max(0, len(observations) - 1)},
            {"name": "RESETn", "wave": _bit_wave(not value for value in reset)},
            {},
            {"name": "VALID", "wave": _bit_wave(valid)},
            {"name": "READY", "wave": _bit_wave(ready)},
            {"name": "FIRE", "wave": _bit_wave(fire)},
            {"name": "DATA", "wave": "".join(data_wave), "data": data},
        ],
        "head": {"text": title, "tick": 0},
        "config": {"hscale": 3},
    }


def ready_valid_event_dot(run: ReadyValidSinkRun, *, title: str) -> str:
    lines = [
        "digraph ready_valid_events {",
        '  rankdir="TB";',
        f'  label="{title}"; labelloc="t";',
        '  graph [bgcolor="white", nodesep=0.35, ranksep=0.55];',
        '  node [shape=box, style="rounded,filled", fontname="monospace"];',
    ]
    transfer_index = 0
    previous_sample = None
    for index, wrapped in enumerate(run.observations):
        sample = wrapped.observation
        payload = "-" if sample.event is None else f"0x{int(sample.event.payload['data']):02x}"
        lines.append(
            f'  s{index} [fillcolor="#e2e8f0", label="cycle {sample.cycle}\\n'
            f'V={int(sample.valid)} R={int(sample.ready)} data={payload}"];'
        )
        if previous_sample is not None:
            lines.append(f'  s{previous_sample} -> s{index} [color="#94a3b8"];')
        previous_sample = index
        if wrapped.asserted or not (sample.valid and sample.ready):
            continue
        if run.fault_cycle == sample.cycle:
            rule = run.fault.rule if run.fault else "fault"
            lines.append(
                f'  f [shape=octagon, fillcolor="#fecaca", label="FAULT\\n{rule}"];'
            )
            lines.append(f'  s{index} -> f [color="#dc2626", penwidth=2];')
            lines.append(f"  {{ rank=same; s{index}; f; }}")
            continue
        if transfer_index >= len(run.transfers):
            continue
        transfer = run.transfers[transfer_index]
        value = int(transfer.payload["data"])
        lines.append(
            f'  t{transfer_index} [fillcolor="#dbeafe", label="DATA_TRANSFER\\n0x{value:02x}"];'
        )
        lines.append(
            f'  k{transfer_index} [fillcolor="#dcfce7", label="Sink.accept\\n0x{value:02x}"];'
        )
        lines.append(f'  s{index} -> t{transfer_index} [label="lower"];')
        lines.append(f'  t{transfer_index} -> k{transfer_index} [label="consume"];')
        lines.append(
            f"  {{ rank=same; s{index}; t{transfer_index}; k{transfer_index}; }}"
        )
        transfer_index += 1
    lines.append("}")
    return "\n".join(lines)


def ready_valid_topology_dot(project: ProjectSnapshot) -> str:
    return f"""digraph ready_valid_sink_topology {{
  rankdir=TB;
  graph [bgcolor="white", nodesep=0.7];
  node [shape=box, style="rounded,filled", fontname="monospace"];
  source [fillcolor="#fef3c7", label="Stimulus provider\\nScriptedSource\\n(Replaceable)"];
  protocol [fillcolor="#dbeafe", label="ReadyValid Protocol\\nVALID/READY + stall"];
  sink [fillcolor="#dcfce7", label="VirtualDut Sink\\ncapture accepted transfers"];
  source -> protocol [label="ReadyValidSample"];
  protocol -> sink [label="DATA_TRANSFER"];
  label="{project.name} verification plan"; labelloc=t;
}}"""


def ready_valid_sink_report_html(
    legal: ReadyValidSinkRun,
    legal_project: ProjectSnapshot,
    mutation: ReadyValidSinkRun,
    mutation_project: ProjectSnapshot,
) -> str:
    component_rows = "".join(
        f"<tr><td>{escape(item.name)}</td><td>{escape(item.category)}</td>"
        f"<td><code>{escape(item.implementation)}</code></td><td>{escape(item.role)}</td></tr>"
        for item in legal_project.components
    )
    lifecycle_rows = "".join(
        f"<tr><td>{item.phase.value}</td><td>{escape(item.summary)}</td></tr>"
        for item in legal_project.history
    )
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Ready-valid sink project</title><style>
body{{font-family:system-ui;margin:24px;background:#f8fafc;color:#0f172a}}
object{{width:100%;height:400px;background:white;border:1px solid #cbd5e1}}
table{{border-collapse:collapse;background:white}}td,th{{padding:8px 12px;border:1px solid #cbd5e1}}
</style></head><body>
<h1>{escape(legal_project.name)}</h1>
<h2>Components</h2><table><tr><th>Name</th><th>Category</th><th>Implementation</th><th>Role</th></tr>{component_rows}</table>
<h2>Lifecycle</h2><table><tr><th>Phase</th><th>Summary</th></tr>{lifecycle_rows}</table>
<h2>Verification plan</h2><object data="topology.svg" type="image/svg+xml"></object>
<h2>Legal waveform</h2><object data="legal.wave.svg" type="image/svg+xml"></object>
<h2>Legal event causality</h2><object data="legal.events.svg" type="image/svg+xml"></object>
<h2>Negative waveform</h2><p>Expected: <code>{escape(mutation.fault.rule if mutation.fault else 'NO FAULT')}</code>;
Sink received {mutation.sink_state.received} transfers; Project phase {mutation_project.phase.value}.</p>
<object data="mutation.wave.svg" type="image/svg+xml"></object>
<h2>Negative event causality</h2><object data="mutation.events.svg" type="image/svg+xml"></object>
</body></html>"""
