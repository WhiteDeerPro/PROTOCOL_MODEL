"""Text and HTML evidence for the AXI4 read-interleaving Project."""

from __future__ import annotations

from html import escape

from .project import AxiReadInterleaveRun


def format_run(run: AxiReadInterleaveRun) -> str:
    lines = [
        "AXI4 READ INTERLEAVING PROJECT",
        f"  verdict={run.verdict.value}",
        f"  input_dut_ar={run.source_emitted} output_dut_r={run.responder_emitted}",
        "",
        "LEGAL FLOW",
    ]
    lines.extend(f"  [{index}] {event.short()}" for index, event in enumerate(run.trace.events))
    lines.extend(("", "CONSTRAINT MUTATIONS"))
    for item in run.checks:
        lines.append(
            f"  {item.name}: expected={item.expected.value} observed={item.observed.value} "
            f"matched={item.matched} rule={item.rule}"
        )
        lines.append(f"    {item.detail}")
    return "\n".join(lines)


def topology_dot(snapshot) -> str:
    """Render ownership and event flow for the two-VirtualDut experiment."""

    return f"""digraph axi_read_interleave_topology {{
  rankdir=LR;
  graph [bgcolor="white", nodesep=0.75, ranksep=0.6, labelloc=t,
         label="{snapshot.name} verification network"];
  node [shape=box, style="rounded,filled", fontname="monospace"];
  protocol [fillcolor="#dbeafe", label="AXI read link\\nIDs 1/2 + quiet constraints"];
  input [fillcolor="#fef3c7", label="Input VirtualDut\\nScriptedSource\\nAR order 1,2"];
  output [fillcolor="#dcfce7", label="Output VirtualDut\\nInterleavingReadResponder\\nalternating R beats by ID"];
  input -> protocol [label="AR_TRANSFER"];
  protocol -> output [label="accepted AR"];
  output -> protocol [label="R_TRANSFER"];
}}"""


def report_html(run: AxiReadInterleaveRun, snapshot) -> str:
    components = "".join(
        f"<tr><td>{escape(item.name)}</td><td>{escape(item.category)}</td>"
        f"<td><code>{escape(item.implementation)}</code></td><td>{escape(item.role)}</td></tr>"
        for item in snapshot.components
    )
    events = "".join(
        f"<tr><td>{index}</td><td><code>{escape(event.kind)}</code></td>"
        f"<td>{escape(str(event.key))}</td><td><code>{escape(str(dict(event.payload)))}</code></td></tr>"
        for index, event in enumerate(run.trace.events)
    )
    checks = "".join(
        f"<tr><td>{escape(item.name)}</td><td>{item.expected.value}</td>"
        f"<td>{item.observed.value}</td><td>{item.matched}</td>"
        f"<td><code>{escape(item.rule)}</code></td><td>{escape(item.detail)}</td></tr>"
        for item in run.checks
    )
    records = snapshot.state.get("derivation_constraints", ())
    constraint_rows = "".join(
        f"<tr><td><code>{escape(item.name)}</code></td>"
        f"<td>{escape(item.scope)}</td>"
        f"<td><code>{escape(', '.join(item.targets))}</code></td>"
        f"<td>{escape(item.rule)}</td>"
        f"<td><code>{escape(item.foundation)}</code></td></tr>"
        for item in records
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>AXI4 read interleaving</title>
<style>body{{font-family:system-ui;margin:24px;color:#0f172a;background:#f8fafc}}
table{{border-collapse:collapse;background:white;margin-bottom:24px}}td,th{{border:1px solid #cbd5e1;padding:8px 12px}}
code{{white-space:pre-wrap}}object{{width:100%;background:white;border:1px solid #cbd5e1;margin-bottom:24px}}
.network{{height:300px}}.wave{{height:620px}}.causal{{height:560px}}</style></head><body>
<h1>AXI4 cross-ID read interleaving</h1>
<p>Project <strong>{escape(snapshot.name)}</strong> · verdict <strong>{run.verdict.value}</strong>.</p>
<p><a href="constraints.md">Constraint report</a> · <a href="manifest.json">Run manifest</a> · <a href="trace.json">Trace data</a> · <a href="run.txt">Text report</a></p>
<p>The base AXI4 ProtocolSpec is derived into a project-owned read-only profile. Two VirtualDuts
drive two AR requests and alternating R responses; protocol state decides legality.</p>
<h2>Components</h2><table><tr><th>Name</th><th>Category</th><th>Implementation</th><th>Role</th></tr>{components}</table>
<h2>Verification network</h2>
<object class="network" data="network.svg" type="image/svg+xml"></object>
<h2>Applied constraints</h2>
<table><tr><th>Constraint record</th><th>Scope</th><th>Targets</th><th>Rule</th><th>Foundation</th></tr>{constraint_rows}</table>
<h2>AXI4 waveform</h2>
<p>Quiet AW/W/B channels are omitted. AR1 is issued before AR2, while R2 responds and completes first.</p>
<object class="wave" data="waveform.svg" type="image/svg+xml"></object>
<h2>Causal chain</h2>
<p>Each AR creates its same-ID R-beat obligation; there is no ordering edge between different IDs.</p>
<object class="causal" data="causality.svg" type="image/svg+xml"></object>
<h2>Legal two-DUT flow</h2><table><tr><th>#</th><th>Event</th><th>ID</th><th>Payload</th></tr>{events}</table>
<h2>Constraint mutations</h2><table><tr><th>Check</th><th>Expected</th><th>Observed</th><th>Matched</th><th>Rule</th><th>Detail</th></tr>{checks}</table>
<h2>Constraint boundary</h2>
<p>Active IDs are 1/2. ARLOCK, ARCACHE, ARPROT, ARQOS and ARREGION are tied low. AW/W/B are quiet.
Same-ID responses consume the oldest burst; different IDs may interleave. AXI4 has no AXI5 AWATOP atomic signal.</p>
</body></html>"""
