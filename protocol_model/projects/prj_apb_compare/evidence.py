"""Network visualization and report assembly for the APB Project."""

from protocol_model.protocols.apb import apb_report_html


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
<p><a href="constraints.md">Constraint report</a> · <a href="manifest.json">Run manifest</a> · <a href="trace.json">Trace data</a></p>
<object data="network.svg" type="image/svg+xml"></object></section>"""
    return base.replace("<h1>", network + "<h1>", 1)
