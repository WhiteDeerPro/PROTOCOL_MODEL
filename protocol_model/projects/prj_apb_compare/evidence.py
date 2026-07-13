"""Network visualization and report assembly for the APB Project."""

from protocol_model.protocols.apb import apb_report_html


def trace_dot(trace, *, title: str, fault_rule: str | None = None) -> str:
    lines = [
        "digraph apb_trace {",
        '  rankdir="TB";',
        f'  graph [bgcolor="white", labelloc="t", newrank=true, nodesep=0.35, ranksep=0.55, splines=polyline, label="{title}"];',
        '  node [shape=box, style="rounded,filled", fontname="monospace"];',
    ]
    previous_addr = None
    fault_index = None
    for index, sample in enumerate(trace.samples):
        phase = (
            "RESET" if not sample.presetn else
            "IDLE" if not sample.psel else
            "SETUP" if not sample.penable else
            "WAIT" if not sample.pready else "COMPLETE"
        )
        label = f"cycle {index}\\n{phase}\\nPADDR=0x{sample.paddr:x}"
        lines.append(f'  s{index} [fillcolor="#e2e8f0", label="{label}"];')
        if index:
            constraint = "false" if index % 4 else "true"
            lines.append(
                f'  s{index - 1} -> s{index} [color="#94a3b8", constraint={constraint}];'
            )
        if sample.psel:
            if (
                fault_index is None
                and previous_addr is not None
                and sample.paddr != previous_addr
            ):
                fault_index = index
            previous_addr = sample.paddr
        else:
            previous_addr = None
    for row_index, start in enumerate(range(0, len(trace.samples), 4)):
        indices = list(range(start, min(start + 4, len(trace.samples))))
        lines.append("  { rank=same; " + "; ".join(f"s{index}" for index in indices) + "; }")
        order = indices if row_index % 2 == 0 else list(reversed(indices))
        if len(order) > 1:
            lines.append(
                "  " + " -> ".join(f"s{index}" for index in order)
                + " [style=invis, weight=100];"
            )
    if fault_rule is not None:
        index = fault_index if fault_index is not None else len(trace.samples) - 1
        rule = fault_rule.replace('"', '\\"')
        lines.append(
            f'  fault [shape=octagon, fillcolor="#fecaca", label="FAULT\\n{rule}"];'
        )
        lines.append(f'  s{index} -> fault [color="#dc2626", penwidth=2];')
    lines.append("}")
    return "\n".join(lines)


def topology_dot(snapshot) -> str:
    return f"""digraph apb_compare_network {{
  rankdir=LR;
  graph [bgcolor="white", labelloc=t, label="{snapshot.name} protocol-instance network"];
  node [shape=box, style="rounded,filled", fontname="monospace"];
  source [fillcolor="#fef3c7", label="Constructive stimulus\\nAPB pin samples"];
  apb3 [fillcolor="#dbeafe", label="APB3 link"];
  apb4 [fillcolor="#dbeafe", label="APB4 link"];
  sink [fillcolor="#dcfce7", label="Canonical transfer collector"];
  source -> apb3 -> sink;
  source -> apb4 -> sink;
}}"""


def report_html(run, project, transactions: int) -> str:
    base = apb_report_html(
        apb3_cycles=len(run.traces[3].samples),
        apb4_cycles=len(run.traces[4].samples),
        transactions=transactions,
        violation=run.mutation_rule,
    )
    network = """<section><h2>Project network</h2>
<p>Two independent protocol links receive the same class of pin stimulus.</p>
<p><a href="constraints.md">Constraint report</a> · <a href="manifest.json">Run manifest</a> · <a href="cases/request_stability_mutation/trace.json">Negative trace</a></p>
<object data="network.svg" type="image/svg+xml"></object></section>"""
    return base.replace("<h1>", network + "<h1>", 1)
