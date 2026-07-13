"""Graphviz and browser evidence for network-level causal traces."""

from __future__ import annotations

from html import escape

from ..lifecycle import ProjectSnapshot
from .project import AxiReadNetworkRun


def _label(run: AxiReadNetworkRun, index: int) -> str:
    located = run.trace.events[index]
    event = located.event
    fields = []
    for name in ("addr", "len", "size", "data", "resp", "last"):
        if name in event.payload:
            value = event.payload[name]
            if name in {"addr", "data"}:
                value = f"0x{int(value):x}"
            fields.append(f"{name}={value}")
    suffix = "\\n" + " ".join(fields) if fields else ""
    return f"{located.location}\\n{event.kind} id={event.key}{suffix}"


def axi_read_chain_dot(run: AxiReadNetworkRun) -> str:
    colors = {"AXI-A": "#dbeafe", "AXI-B": "#dcfce7"}
    lines = [
        "digraph axi_read_chain {",
        '  rankdir="TB";',
        '  graph [bgcolor="white", nodesep=0.30, ranksep=0.42, ratio="compress", splines="polyline"];',
        '  node [shape=box, style="rounded,filled", fontname="monospace"];',
        '  edge [color="#64748b"];',
    ]
    for index, located in enumerate(run.trace.events):
        color = colors.get(located.location, "#f1f5f9")
        label = _label(run, index).replace('"', '\\"')
        lines.append(f'  n{index} [fillcolor="{color}", label="{label}"];')
    for before, after in sorted(run.trace.causal_graph.edges):
        cross = run.trace.events[before].location != run.trace.events[after].location
        attrs = ' [color="#dc2626", penwidth=2.0, label="forward"]' if cross else ""
        lines.append(f"  n{before} -> n{after}{attrs};")
    for before, after in sorted(run.trace.causal_graph.edges):
        if run.trace.events[before].location != run.trace.events[after].location:
            lines.append(f"  {{ rank=same; n{before}; n{after}; }}")
    lines.append("}")
    return "\n".join(lines)


def axi_fault_dot(run: AxiReadNetworkRun, *, title: str) -> str:
    event = run.attempted_event
    if event is None or run.fault is None:
        raise ValueError("negative causality requires an attempted event and fault")
    fields = " ".join(
        f"{name}={f'0x{int(value):x}' if name == 'addr' else value}"
        for name, value in event.payload.items()
        if name in {"addr", "len", "size", "burst"}
    )
    rule = str(run.fault.rule).replace('"', '\\"')
    return f"""digraph axi_fault {{
  rankdir=LR;
  graph [bgcolor="white", labelloc="t", label="{title}"];
  node [shape=box, style="rounded,filled", fontname="monospace"];
  stimulus [fillcolor="#fef3c7", label="attempted {event.kind} id={event.key}\\n{fields}"];
  link [fillcolor="#dbeafe", label="AXI-A constraint check"];
  fault [shape=octagon, fillcolor="#fecaca", label="FAULT\\n{rule}"];
  stimulus -> link -> fault [color="#dc2626", penwidth=2];
}}"""


def axi_read_network_dot(project: ProjectSnapshot) -> str:
    """Show named protocol instances separately from VirtualDut behavior."""

    return f"""digraph axi_read_bridge_network {{
  rankdir=LR;
  graph [bgcolor="white", labelloc=t, label="{project.name} instance network"];
  node [shape=box, style="rounded,filled", fontname="monospace"];
  source [fillcolor="#fef3c7", label="Read stimulus"];
  axia [fillcolor="#dbeafe", label="AXI-A link"];
  bridge [fillcolor="#fce7f3", label="VirtualDut AxiReadBridge"];
  axib [fillcolor="#dbeafe", label="AXI-B link"];
  responder [fillcolor="#dcfce7", label="VirtualDut ReadResponder"];
  source -> axia -> bridge -> axib -> responder [label="AR"];
  responder -> axib -> bridge -> axia [label="R"];
}}"""


def axi_read_chain_report_html(
    run: AxiReadNetworkRun,
    project: ProjectSnapshot,
    rejected: AxiReadNetworkRun | None = None,
) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(item.name)}</td>"
        f"<td>{item.link_a_pending}</td>"
        f"<td>{item.bridge_pending}</td>"
        f"<td>{item.link_b_pending}</td>"
        "</tr>"
        for item in run.milestones
    )
    component_rows = "".join(
        "<tr>"
        f"<td>{escape(item.name)}</td><td>{escape(item.category)}</td>"
        f"<td><code>{escape(item.implementation)}</code></td>"
        f"<td>{escape(item.role)}</td></tr>"
        for item in project.components
    )
    lifecycle_rows = "".join(
        f"<tr><td>{index}</td><td>{item.phase.value}</td><td>{escape(item.summary)}</td></tr>"
        for index, item in enumerate(project.history)
    )
    state_rows = "".join(
        f"<tr><td>{escape(str(name))}</td><td><code>{escape(str(value))}</code></td></tr>"
        for name, value in project.state.items()
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>AXI read network</title>
<style>
body{{font-family:system-ui;margin:24px;background:#f8fafc;color:#0f172a}}
object{{width:100%;background:white;border:1px solid #cbd5e1}}
.causal{{height:720px}}.wave{{height:430px}}
.scroll{{overflow-x:auto;margin-bottom:18px}}
table{{border-collapse:collapse;background:white}}td,th{{padding:8px 14px;border:1px solid #cbd5e1}}
</style></head><body>
<h1>Two-link AXI read network</h1>
<p>Project: <strong>{escape(project.name)}</strong> · phase: <strong>{project.phase.value}</strong>
· verdict: <strong>{run.verdict.value}</strong>.</p>
<p><a href="constraints.md">Constraint report</a> · <a href="manifest.json">Run manifest</a> · <a href="cases/legal_4kb_edge/trace.json">Legal trace</a> · <a href="cases/crossing_4kb/trace.json">Negative trace</a></p>
<h2>Project components</h2>
<table><tr><th>Name</th><th>Category</th><th>Implementation</th><th>Role</th></tr>{component_rows}</table>
<h2>Lifecycle</h2>
<table><tr><th>#</th><th>Phase</th><th>Summary</th></tr>{lifecycle_rows}</table>
<h2>Current project state</h2>
<table><tr><th>Field</th><th>Value</th></tr>{state_rows}</table>
<h2>End-to-end causality</h2>
<p>Blue nodes are AXI-A, green nodes are AXI-B;
red edges cross the bridge.</p>
<object class="causal" data="cases/legal_4kb_edge/causality.svg" type="image/svg+xml"></object>
<h2>Protocol-instance network</h2>
<object class="causal" data="network.svg" type="image/svg+xml"></object>
<h2>AXI-A signals</h2>
<p>AW/W/B are quiet for this read-only experiment and are omitted.</p>
<div class="scroll"><object class="wave" data="cases/legal_4kb_edge/waveform.axi-a.svg" type="image/svg+xml"></object></div>
<h2>AXI-B signals</h2>
<p>AW/W/B are quiet for this read-only experiment and are omitted.</p>
<div class="scroll"><object class="wave" data="cases/legal_4kb_edge/waveform.axi-b.svg" type="image/svg+xml"></object></div>
<h2>Negative constraint witness</h2>
<p>4KB-crossing case: <code>{escape(rejected.fault.rule if rejected and rejected.fault else 'NO FAULT')}</code>.</p>
<div class="scroll"><object class="wave" data="cases/crossing_4kb/waveform.svg" type="image/svg+xml"></object></div>
<object class="causal" data="cases/crossing_4kb/causality.svg" type="image/svg+xml"></object>
<h2>Obligation state</h2>
<table><tr><th>Milestone</th><th>Link A pending</th><th>Bridge tokens</th><th>Link B pending</th></tr>{rows}</table>
</body></html>"""
