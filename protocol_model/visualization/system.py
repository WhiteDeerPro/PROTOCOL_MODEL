"""Protocol-independent projections of system topology and execution traces."""

from __future__ import annotations

from html import escape
import json
from typing import Mapping

from protocol_model.system.topology import (
    DirectedTransportConnection,
    InterfaceConnection,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.fabric.single_ingress import (
    SingleIngressAddressFabricBackend,
)

from .policy import DiagramDetail
from .virtual_dut import _structure_dot_lines, project_virtual_dut


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _interface_connection_dot_lines(
    name: str,
    connection,
    endpoint_nodes: Mapping[str, str],
    *,
    connection_index: int,
    penwidth: float = 1.4,
    detail: DiagramDetail = DiagramDetail.STANDARD,
) -> list[str]:
    """Render an ordinary binary connection as an edge, not a topology node.

    A two-ended InterfaceConnection is most legible as the typed edge
    between its endpoint ports.  Protocols with another arity still need a
    junction because one Graphviz edge cannot join all of their roles without
    inventing pairwise connectivity.
    """

    endpoints = tuple(connection.endpoints.items())
    if len(endpoints) == 2:
        (tail_role, tail), (head_role, head) = endpoints
        if detail is DiagramDetail.OVERVIEW:
            connection_label = connection.protocol.name
        elif detail is DiagramDetail.DIAGNOSTIC:
            connection_label = (
                f"{connection.protocol.name}\n"
                f"{name}\n"
                f"{tail_role} · {tail.port} ↔ {head_role} · {head.port}"
            )
        else:
            connection_label = (
                f"{connection.protocol.name}\n"
                f"{tail.port} ↔ {head.port}"
            )
        return [
            f"  {endpoint_nodes[tail_role]} -> {endpoint_nodes[head_role]} "
            f"[dir=none, penwidth={penwidth:.1f}, "
            f"label={_quoted(connection_label)}];"
        ]

    junction_id = f"connection_junction{connection_index}"
    junction_label = connection.protocol.name
    if detail is DiagramDetail.DIAGNOSTIC:
        junction_label += f"\n{name}"
    lines = [
        f"  {junction_id} [shape=point, width=0.11, height=0.11, "
        'fixedsize=true, style=filled, fillcolor="#64748b", '
        f"color=\"#64748b\", label=\"\", "
        f"xlabel={_quoted(junction_label)}];"
    ]
    for role, endpoint in endpoints:
        endpoint_label = ""
        if detail is not DiagramDetail.OVERVIEW:
            endpoint_label = f"{role} · {endpoint.port}"
        lines.append(
            f"  {endpoint_nodes[role]} -> {junction_id} "
            f"[dir=none, penwidth={penwidth:.1f}, "
            f"label={_quoted(endpoint_label)}];"
        )
    return lines


def _transport_connection_dot_line(
    name: str,
    connection: DirectedTransportConnection,
    transmitter_node: str,
    receiver_node: str,
    *,
    penwidth: float = 1.6,
    detail: DiagramDetail = DiagramDetail.STANDARD,
) -> str:
    if detail is DiagramDetail.OVERVIEW:
        label = connection.transport_family
    elif detail is DiagramDetail.DIAGNOSTIC:
        label = (
            f"{connection.transport_family}\n{name}\n"
            f"{connection.transmitter.port} → {connection.receiver.port}"
        )
    else:
        label = (
            f"{connection.transport_family}\n"
            f"{connection.transmitter.port} → {connection.receiver.port}"
        )
    return (
        f"  {transmitter_node} -> {receiver_node} "
        f"[dir=forward, penwidth={penwidth:.1f}, "
        f"label={_quoted(label)}];"
    )


def system_topology_dot(
    system,
    *,
    detail: DiagramDetail = DiagramDetail.STANDARD,
) -> str:
    """Project a SystemProtocol into a role-aware topology graph.

    ``detail`` changes visible labels only; it does not add or infer topology.
    """

    detail = DiagramDetail(detail)
    dut_ids = {
        name: f"dut{index}"
        for index, name in enumerate(system.virtual_duts)
    }
    lines = [
        "digraph system_topology {",
        "  rankdir=LR;",
        f"  label={_quoted(system.name)};",
        '  labelloc="t";',
        '  graph [nodesep=0.5, ranksep=1.15, splines=polyline];',
        '  node [fontname="monospace"];',
        '  edge [fontname="sans-serif", fontsize=8];',
    ]
    for name, dut in system.virtual_duts.items():
        behavior_tags = ", ".join(
            sorted(item.value for item in dut.behavior_tags)
        )
        if detail is DiagramDetail.OVERVIEW:
            label = name
        elif detail is DiagramDetail.DIAGNOSTIC:
            dut_detail = behavior_tags or dut.realization_name
            label = f"{name}\nVirtualDut · {dut_detail}"
        elif behavior_tags:
            label = f"{name}\nVirtualDut · {behavior_tags}"
        else:
            label = f"{name}\nVirtualDut"
        lines.append(
            f"  {dut_ids[name]} [shape=box, style=rounded, label={_quoted(label)}];"
        )
    for index, (name, connection) in enumerate(system.connections.items()):
        if isinstance(connection, InterfaceConnection):
            lines.extend(
                _interface_connection_dot_lines(
                    name,
                    connection,
                    {
                        role: dut_ids[endpoint.dut]
                        for role, endpoint in connection.endpoints.items()
                    },
                    connection_index=index,
                    detail=detail,
                )
            )
        else:
            lines.append(
                _transport_connection_dot_line(
                    name,
                    connection,
                    dut_ids[connection.transmitter.dut],
                    dut_ids[connection.receiver.dut],
                    detail=detail,
                )
            )
    for index, (name, endpoint) in enumerate(system.boundary.items()):
        boundary_id = f"boundary{index}"
        lines.append(
            f"  {boundary_id} [shape=plaintext, label={_quoted(name)}];"
        )
        boundary_port = "" if detail is DiagramDetail.OVERVIEW else endpoint.port
        lines.append(
            f"  {boundary_id} -> {dut_ids[endpoint.dut]} "
            f"[dir=none, label={_quoted(boundary_port)}];"
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def system_bus_strip_dot(
    system,
    *,
    fabric: str,
    title: str | None = None,
    detail: DiagramDetail = DiagramDetail.STANDARD,
) -> str:
    """Fold one single-ingress address fabric into a bus-strip view.

    The function reads the existing ``VirtualDut`` and binary
    ``InterfaceConnection`` declarations.  It does not create a shared
    connection or alter execution semantics: the ordinary star/netlist
    topology remains authoritative.  Callers select the fabric explicitly so
    visualization never infers routing behavior from a star-shaped drawing.
    ``detail`` controls labels and the diagnostic projection note only.
    """

    detail = DiagramDetail(detail)
    if fabric not in system.virtual_duts:
        raise ValueError(f"bus-strip view references unknown DUT {fabric!r}")
    fabric_dut = system.virtual_duts[fabric]
    backend = fabric_dut.backend
    if not isinstance(backend, SingleIngressAddressFabricBackend):
        raise ValueError(
            "bus-strip view requires a SingleIngressAddressFabricBackend"
        )

    connected: dict[str, tuple[str, object, str, VirtualDutPortRef]] = {}
    protocol_names: set[str] = set()
    for connection_name, connection in system.connections.items():
        if not isinstance(connection, InterfaceConnection):
            continue
        local = tuple(
            (role, endpoint)
            for role, endpoint in connection.endpoints.items()
            if endpoint.dut == fabric
        )
        if not local:
            continue
        if len(local) != 1 or len(connection.endpoints) != 2:
            raise ValueError(
                "bus-strip view requires binary fabric connections"
            )
        fabric_role, fabric_endpoint = local[0]
        external = tuple(
            (role, endpoint)
            for role, endpoint in connection.endpoints.items()
            if endpoint != fabric_endpoint
        )
        if len(external) != 1:
            raise ValueError(
                "bus-strip view cannot identify one external endpoint"
            )
        if fabric_endpoint.port in connected:
            raise ValueError(
                f"fabric port {fabric_endpoint.port!r} has two connections"
            )
        external_role, external_endpoint = external[0]
        connected[fabric_endpoint.port] = (
            connection_name,
            connection,
            external_role,
            external_endpoint,
        )
        protocol_names.add(connection.protocol.name)

    routed_egress_ports = tuple(
        dict.fromkeys(route.egress_port for route in backend.routes)
    )
    unreferenced_egress_ports = tuple(
        name
        for name in backend.egress_bindings
        if name not in routed_egress_ports
    )
    ordered_ports = (
        backend.ingress_port,
        *routed_egress_ports,
        *unreferenced_egress_ports,
    )
    missing = set(ordered_ports) - set(connected)
    extra = set(connected) - set(ordered_ports)
    if missing or extra:
        raise ValueError(
            "bus-strip view requires one connection for every fabric port; "
            f"missing={sorted(missing)!r}, extra={sorted(extra)!r}"
        )
    if len(protocol_names) != 1:
        raise ValueError(
            "bus-strip view requires one InterfaceProtocol across the fabric"
        )

    routes_by_egress: dict[str, list[str]] = {
        name: [] for name in backend.egress_bindings
    }
    for route in backend.routes:
        routes_by_egress[route.egress_port].append(
            f"0x{route.base_address:x}..0x{route.limit_address - 1:x}"
        )

    protocol_name = next(iter(protocol_names))
    bus_cells = "".join(
        f'<TD PORT="tap{index}" WIDTH="150" HEIGHT="14" '
        'BGCOLOR="#2563eb"></TD>'
        for index in range(len(ordered_ports))
    )
    bus_caption = (
        f"<B>{escape(protocol_name)}</B> · folded bus-strip view<BR/>"
        f'<FONT POINT-SIZE="9">{escape(fabric)} · decoder + response mux'
        "</FONT>"
    )
    lines = [
        "digraph system_bus_strip {",
        "  rankdir=TB;",
        f"  label={_quoted(title or system.name + ' · bus-strip projection')};",
        '  labelloc="t";',
        '  graph [bgcolor="white", pad=0.28, nodesep=0.48, '
        'ranksep=0.66, splines=polyline];',
        '  node [fontname="sans-serif", fontsize=10, shape=box, '
        'style="rounded,filled", fillcolor="#ffffff"];',
        '  edge [fontname="sans-serif", fontsize=8, color="#52606d", '
        'penwidth=1.3];',
        '  bus [shape=plain, label=<<TABLE BORDER="0" CELLBORDER="0" '
        'CELLSPACING="0" CELLPADDING="0">',
        f"    <TR>{bus_cells}</TR>",
        f'    <TR><TD COLSPAN="{len(ordered_ports)}" CELLPADDING="5">'
        f"{bus_caption}</TD></TR>",
        "  </TABLE>>];",
    ]

    ingress_nodes: list[str] = []
    egress_nodes: list[str] = []
    for index, port_name in enumerate(ordered_ports):
        connection_name, _, external_role, endpoint = connected[port_name]
        node_id = f"endpoint{index}"
        is_ingress = port_name == backend.ingress_port
        fill = "#eff6ff" if is_ingress else "#ecfdf5"
        color = "#2563eb" if is_ingress else "#059669"
        if detail is DiagramDetail.OVERVIEW:
            label = endpoint.dut
        elif detail is DiagramDetail.DIAGNOSTIC:
            label = (
                f"{endpoint.dut}\n{endpoint.port} · {external_role}\n"
                f"connection: {connection_name}"
            )
        else:
            label = f"{endpoint.dut}\n{endpoint.port} · {external_role}"
        lines.append(
            f"  {node_id} [fillcolor={_quoted(fill)}, "
            f"color={_quoted(color)}, label={_quoted(label)}];"
        )
        route_windows = routes_by_egress[port_name] if not is_ingress else []
        if detail is DiagramDetail.OVERVIEW:
            edge_label = ""
        elif detail is DiagramDetail.DIAGNOSTIC:
            route_text = ""
            if route_windows:
                route_text = "\n" + ", ".join(route_windows)
            edge_label = f"{port_name}{route_text}\nrequest ↔ completion"
        else:
            visible_windows = route_windows[:2]
            window_summary = ", ".join(visible_windows)
            if len(route_windows) > len(visible_windows):
                window_summary += (
                    f", +{len(route_windows) - len(visible_windows)} windows"
                )
            edge_label = port_name
            if window_summary:
                edge_label += f"\n{window_summary}"
        if is_ingress:
            ingress_nodes.append(node_id)
            lines.append(
                f"  {node_id} -> bus:tap{index}:n [dir=both, "
                f"arrowhead=normal, arrowtail=normal, "
                f"label={_quoted(edge_label)}];"
            )
        else:
            egress_nodes.append(node_id)
            lines.append(
                f"  bus:tap{index}:s -> {node_id} [dir=both, "
                f"arrowhead=normal, arrowtail=normal, "
                f"label={_quoted(edge_label)}];"
            )

    if ingress_nodes:
        lines.append(f"  {{ rank=source; {'; '.join(ingress_nodes)}; }}")
    if len(egress_nodes) > 1:
        lines.append(f"  {{ rank=sink; {'; '.join(egress_nodes)}; }}")
    if detail is DiagramDetail.DIAGNOSTIC:
        lines.extend(
            (
                '  boundary [shape=note, fillcolor="#f8fafc", '
                'color="#64748b", label="presentation-only fold\\n'
                'canonical topology remains explicit star connections"];',
                "  bus -> boundary [style=invis];",
            )
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def expanded_system_topology_dot(
    system,
    *,
    external_sources: Mapping[VirtualDutPortRef, str] | None = None,
    detail: DiagramDetail = DiagramDetail.STANDARD,
) -> str:
    """Project topology while expanding inspectable VirtualDut realizations.

    ``external_sources`` is display-only metadata for scenario drivers or
    other environment actors.  These nodes are deliberately outside the DUT
    clusters and do not become part of SystemProtocol execution semantics.
    ``detail`` is forwarded to each VirtualDut projection and connection label.
    """

    detail = DiagramDetail(detail)
    external_sources = dict(external_sources or {})
    structures = {
        name: project_virtual_dut(dut)
        for name, dut in system.virtual_duts.items()
    }
    component_ids: dict[tuple[str, str], str] = {}
    lines = [
        "digraph expanded_system_topology {",
        "  rankdir=LR;",
        f"  label={_quoted(system.name + ' · expanded VirtualDut topology')};",
        '  labelloc="t";',
        '  graph [nodesep=0.35, ranksep=1.05, splines=polyline, '
        'compound=true];',
        '  node [fontname="sans-serif", fontsize=10, shape=box, '
        'style="rounded,filled", fillcolor="#ffffff"];',
        '  edge [fontname="sans-serif", fontsize=9, color="#52606d"];',
    ]
    for dut_index, (name, structure) in enumerate(structures.items()):
        prefix = f"dut{dut_index}_component"
        for component_index, component in enumerate(structure.components):
            component_ids[(name, component.id)] = (
                f"{prefix}_{component_index}"
            )
        cluster_label = name
        if detail is not DiagramDetail.OVERVIEW:
            cluster_label += (
                " · VirtualDut · " + structure.realization.value
            )
        lines.extend(
            (
                f"  subgraph cluster_dut{dut_index} {{",
                f"    label={_quoted(cluster_label)};",
                '    color="#94a3b8";',
                '    style="rounded";',
            )
        )
        lines.extend(
            _structure_dot_lines(
                structure,
                prefix=prefix,
                indent="    ",
                detail=detail,
            )
        )
        lines.append("  }")

    for connection_index, (name, connection) in enumerate(
        system.connections.items()
    ):
        if isinstance(connection, InterfaceConnection):
            endpoint_nodes: dict[str, str] = {}
            for role, endpoint in connection.endpoints.items():
                structure = structures[endpoint.dut]
                port_component = structure.port_components[endpoint.port]
                endpoint_nodes[role] = component_ids[
                    (endpoint.dut, port_component)
                ]
            lines.extend(
                _interface_connection_dot_lines(
                    name,
                    connection,
                    endpoint_nodes,
                    connection_index=connection_index,
                    penwidth=1.6,
                    detail=detail,
                )
            )
            continue
        transmitter_structure = structures[connection.transmitter.dut]
        transmitter_component = transmitter_structure.port_components[
            connection.transmitter.port
        ]
        receiver_structure = structures[connection.receiver.dut]
        receiver_component = receiver_structure.port_components[
            connection.receiver.port
        ]
        lines.append(
            _transport_connection_dot_line(
                name,
                connection,
                component_ids[
                    (connection.transmitter.dut, transmitter_component)
                ],
                component_ids[(connection.receiver.dut, receiver_component)],
                detail=detail,
            )
        )

    for index, (endpoint, label) in enumerate(external_sources.items()):
        if endpoint.dut not in structures:
            raise ValueError(
                f"external source references unknown DUT {endpoint.dut!r}"
            )
        structure = structures[endpoint.dut]
        if endpoint.port not in structure.port_components:
            raise ValueError(
                f"external source references unknown port "
                f"{endpoint.qualified_name!r}"
            )
        external_id = f"external{index}"
        port_component = structure.port_components[endpoint.port]
        port_id = component_ids[(endpoint.dut, port_component)]
        lines.append(
            f"  {external_id} [shape=note, style=\"rounded,dashed,filled\", "
            f"fillcolor=\"#fff7ed\", color=\"#ea580c\", "
            f"label={_quoted(label)}];"
        )
        lines.append(
            f"  {external_id} -> {port_id} [style=dashed, color=\"#ea580c\", "
            f"label=\"scenario drive\"];"
        )

    lines.append("}")
    return "\n".join(lines) + "\n"


def system_trace_dot(trace, *, title: str = "System protocol execution") -> str:
    """Project routed SystemEvents and cross-interface causal edges."""

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
            f"[{event.index}] {event.connection}.{event.event_kind}\n"
            f"{event.source.qualified_name} → {event.destination.qualified_name}\n"
            f"{event.event.short()}"
        )
        lines.append(f"  event{event.index} [label={_quoted(label)}];")
    for before, after in trace.causal_edges:
        lines.append(f"  event{before} -> event{after};")
    lines.append("}")
    return "\n".join(lines) + "\n"
