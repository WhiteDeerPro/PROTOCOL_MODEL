"""Protocol-independent projections of system topology and execution traces."""

from __future__ import annotations

import json


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def system_topology_dot(system) -> str:
    """Project a SystemProtocol into a role-aware topology graph."""

    dut_ids = {name: f"dut{index}" for index, name in enumerate(system.virtual_duts)}
    lines = [
        "digraph system_topology {",
        "  rankdir=LR;",
        f"  label={_quoted(system.name)};",
        '  labelloc="t";',
        '  graph [nodesep=0.45, ranksep=0.7, splines=polyline];',
        '  node [fontname="monospace"];',
    ]
    for name, dut in system.virtual_duts.items():
        facets = ", ".join(sorted(item.value for item in dut.facets))
        detail = facets or dut.model_name
        label = f"{name}\nVirtualDut · {detail}"
        lines.append(
            f"  {dut_ids[name]} [shape=box, style=rounded, label={_quoted(label)}];"
        )
    for index, (name, link) in enumerate(system.links.items()):
        link_id = f"link{index}"
        lines.append(
            f"  {link_id} [shape=diamond, label={_quoted(name + chr(10) + link.protocol.name)}];"
        )
        for role, endpoint in link.endpoints.items():
            label = f"{role} · {endpoint.port}"
            lines.append(
                f"  {dut_ids[endpoint.dut]} -> {link_id} "
                f"[dir=none, label={_quoted(label)}];"
            )
    for index, (name, endpoint) in enumerate(system.boundary.items()):
        boundary_id = f"boundary{index}"
        lines.append(
            f"  {boundary_id} [shape=plaintext, label={_quoted(name)}];"
        )
        lines.append(
            f"  {boundary_id} -> {dut_ids[endpoint.dut]} "
            f"[dir=none, label={_quoted(endpoint.port)}];"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def system_trace_dot(trace, *, title: str = "System protocol execution") -> str:
    """Project routed SystemEvents and their cross-link causal edges."""

    lines = [
        "digraph system_trace {",
        "  rankdir=TB;",
        f"  label={_quoted(title)};",
        '  labelloc="t";',
        '  graph [nodesep=0.4, ranksep=0.55, splines=polyline];',
        '  node [shape=box, fontname="monospace", margin="0.08,0.05"];',
    ]
    for event in trace.events:
        label = (
            f"[{event.index}] {event.link}.{event.channel}\n"
            f"{event.source.qualified_name} → {event.destination.qualified_name}\n"
            f"{event.event.short()}"
        )
        lines.append(f"  event{event.index} [label={_quoted(label)}];")
    for before, after in trace.causal_edges:
        lines.append(f"  event{before} -> event{after};")
    lines.append("}")
    return "\n".join(lines) + "\n"
