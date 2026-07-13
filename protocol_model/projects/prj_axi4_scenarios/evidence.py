"""Waveform-adjacent causality and HTML views for AXI scenario batches."""

from __future__ import annotations

from html import escape

from protocol_model.protocols.axi4 import beat_address


def topology_dot(snapshot) -> str:
    return f"""digraph axi_scenario_topology {{
  rankdir=LR;
  graph [bgcolor="white", labelloc="t", label="{snapshot.name} endpoint topology"];
  node [shape=box, style="rounded,filled", fontname="monospace"];
  manager [fillcolor="#fef3c7", label="Manager VirtualDut\\nAxiManagerSource\\nAW / W / AR"];
  protocol [fillcolor="#dbeafe", label="AXI4 ProtocolInstance\\nfive-channel signal + transaction monitors"];
  responder [fillcolor="#dcfce7", label="Subordinate VirtualDut\\nAxiSubordinateResponder\\nB / R"];
  manager -> protocol [label="AW W AR"];
  protocol -> responder [label="accepted requests"];
  responder -> protocol [label="B R"];
}}"""


def scenario_dot(result) -> str:
    lines = [
        "digraph axi_scenario {",
        '  rankdir="LR";',
        f'  graph [bgcolor="white", labelloc="t", label="{result.case.name}"];',
        '  node [shape=box, style="rounded,filled", fontname="monospace"];',
    ]
    attempts = [
        (cycle.cycle, name, wrapped.observation.event)
        for cycle in result.case.cycles
        for name, wrapped in cycle.channels.items()
        if wrapped.observation.valid and wrapped.observation.event is not None
    ]
    for index, (cycle, channel, event) in enumerate(attempts):
        payload = " ".join(
            f"{name}={value}"
            for name, value in event.payload.items()
            if name in {"addr", "len", "size", "burst", "last", "resp"}
        )
        color = "#fef3c7" if event.kind in {"AW_TRANSFER", "W_TRANSFER", "AR_TRANSFER"} else "#dcfce7"
        lines.append(
            f'  n{index} [fillcolor="{color}", label="cycle {cycle} {channel}\\n{event.kind} id={event.key}\\n{payload}"];'
        )
        if index:
            lines.append(f'  n{index - 1} -> n{index} [color="#94a3b8"];')
    for before, after in result.causal_edges:
        if before < len(attempts) and after < len(attempts):
            lines.append(f'  n{before} -> n{after} [color="#2563eb", penwidth=2];')
    if not attempts:
        lines.append('  cycle [fillcolor="#e2e8f0", label="signal-level attempt"];')
        source = "cycle"
    else:
        source = f"n{len(attempts) - 1}"
    if result.case.name in {"read_4kb_edge", "read_cross_4kb"}:
        request = attempts[0][2]
        beats = int(request.payload["len"]) + 1
        beat_bytes = 1 << int(request.payload["size"])
        addresses = tuple(beat_address(request, index) for index in range(beats))
        last = max(addresses) + beat_bytes - 1
        address_text = " -> ".join(f"0x{address:x}" for address in addresses)
        relation = "==" if int(request.payload["addr"]) >> 12 == last >> 12 else "!="
        lines.append(
            f'  geometry [fillcolor="#e0f2fe", label="derive burst geometry\\n{beats} beat(s) x {beat_bytes} bytes"];'
        )
        lines.append(
            f'  footprint [fillcolor="#e0f2fe", label="beat addresses\\n{address_text}\\nlast byte=0x{last:x}"];'
        )
        lines.append(
            f'  pages [fillcolor="#e0f2fe", label="4KB page comparison\\n0x{int(request.payload["addr"]) >> 12:x} {relation} 0x{last >> 12:x}"];'
        )
        lines.append(f"  {source} -> geometry -> footprint -> pages;")
        source = "pages"
    if result.fault is not None:
        rule = result.fault.rule.replace('"', '\\"')
        reason = result.fault.reason.replace('"', '\\"')
        lines.append(
            f'  fault [shape=octagon, fillcolor="#fecaca", label="FAULT\\n{rule}\\n{reason}"];'
        )
        lines.append(f'  {source} -> fault [color="#dc2626", penwidth=2];')
    elif attempts:
        lines.append('  done [fillcolor="#bbf7d0", label="QUIESCENT / PASS"];')
        lines.append(f'  {source} -> done [color="#16a34a", penwidth=2];')
    lines.append("}")
    return "\n".join(lines)


def report_html(run, snapshot) -> str:
    categories = ("read", "write", "ordering", "concurrency", "reset")
    sections = []
    for category in categories:
        results = [item for item in run.results if item.case.category == category]
        if not results:
            continue
        rows = "".join(
            "<tr>"
            f'<td><a href="cases/{escape(item.case.name)}/trace.json"><code>{escape(item.case.name)}</code></a></td>'
            f"<td>{escape(item.case.description)}</td>"
            f"<td>{item.case.expected.value}</td><td>{item.observed.value}</td>"
            f"<td>{'yes' if item.matched else 'no'}</td>"
            f"<td><code>{escape(item.fault.rule if item.fault else '-')}</code></td>"
            "</tr>"
            for item in results
        )
        views = "".join(
            f'<details><summary><code>{escape(item.case.name)}</code> — {escape(item.case.description)}</summary>'
            f'<object class="wave" data="cases/{escape(item.case.name)}/waveform.svg" type="image/svg+xml"></object>'
            f'<object class="causal" data="cases/{escape(item.case.name)}/causality.svg" type="image/svg+xml"></object></details>'
            for item in results
        )
        sections.append(
            f"<section><h2>{escape(category.title())} cases</h2>"
            "<table><tr><th>Case</th><th>Intent</th><th>Expected</th><th>Observed</th><th>Matched</th><th>Rule</th></tr>"
            f"{rows}</table>{views}</section>"
        )
    components = "".join(
        f"<tr><td>{escape(item.name)}</td><td>{escape(item.category)}</td>"
        f"<td><code>{escape(item.implementation)}</code></td><td>{escape(item.role)}</td></tr>"
        for item in snapshot.components
    )
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>AXI4 source/responder scenarios</title><style>
body{{font-family:system-ui;margin:24px;background:#f8fafc;color:#0f172a}}
section{{margin:28px 0}}table{{border-collapse:collapse;width:100%;background:white}}
td,th{{padding:8px;border:1px solid #cbd5e1;text-align:left}}details{{margin:12px 0;background:white;padding:10px}}
object{{width:100%;background:white;border:1px solid #cbd5e1;margin-top:10px}}.wave{{height:620px}}.causal{{height:420px}}
</style></head><body><h1>AXI4 source/responder scenario batch</h1>
<p>Verdict <strong>{run.verdict.value}</strong> · {len(run.results)} cases ·
full-width aligned profile; atomic/exclusive, cache semantics, and narrow/unaligned transfers are excluded.</p>
<p><a href="constraints.md">Constraint report</a> · <a href="manifest.json">Run manifest</a></p>
<h2>Endpoint topology</h2><object class="causal" data="network.svg" type="image/svg+xml"></object>
<h2>Components</h2><table><tr><th>Name</th><th>Category</th><th>Implementation</th><th>Role</th></tr>{components}</table>
{''.join(sections)}</body></html>"""
