"""Presentation projections for the executable CHI topology-shape cases."""

from __future__ import annotations

from html import escape
import json
from typing import Mapping

from protocol_model.system.topology import DirectedTransportConnection

from model import (
    MESH_CASE,
    RING_CASE,
    GeneratedTopologyAssembly,
)


REQ_COLOR = "#2563eb"
DAT_COLOR = "#c026d3"
BACKBONE_COLOR = "#94a3b8"
ROUTER_FILL = "#ede9fe"
ROUTER_COLOR = "#7c3aed"


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _physical_backbone_edges(
    assembly: GeneratedTopologyAssembly,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (source, target)
        for source, neighbors in assembly.adjacency.items()
        for target in neighbors
        if source < target
    )


def _validate_projection(
    assembly: GeneratedTopologyAssembly,
    result: Mapping[str, object],
) -> None:
    if result["case"] != assembly.case:
        raise ValueError("topology result belongs to another assembly")
    connections = assembly.system.connections
    for source, target in _physical_backbone_edges(assembly):
        for name in (f"{source}_to_{target}", f"{target}_to_{source}"):
            if name not in connections:
                raise ValueError(
                    f"physical backbone edge lacks directed hop {name!r}"
                )
    for endpoint in assembly.endpoints:
        for name in (
            f"{endpoint.name}_to_{endpoint.router}",
            f"{endpoint.router}_to_{endpoint.name}",
        ):
            if name not in connections:
                raise ValueError(
                    f"endpoint attachment lacks directed hop {name!r}"
                )


def _endpoint_label(name: str, role: str, node_id: int) -> str:
    role_label = {
        "requester": "RN requester",
        "home": "Home",
        "leaf": "declared · idle",
    }[role]
    display_name = name.upper() if name in {"rn", "hn"} else name
    return f"{display_name}\n{role_label}\nNodeID 0x{node_id:02x}"


def _endpoint_style(role: str) -> tuple[str, str]:
    return {
        "requester": ("#dbeafe", "#2563eb"),
        "home": ("#ffedd5", "#ea580c"),
        "leaf": ("#f8fafc", "#64748b"),
    }[role]


def _base_edge_lines(
    assembly: GeneratedTopologyAssembly,
) -> list[str]:
    lines = []
    for source, target in _physical_backbone_edges(assembly):
        lines.append(
            f"  {source} -> {target} "
            f'[dir=both, color="{BACKBONE_COLOR}", penwidth=2.0, '
            'arrowsize=0.45];'
        )
    for endpoint in assembly.endpoints:
        lines.append(
            f"  {endpoint.name} -> {endpoint.router} "
            f'[dir=both, color="{BACKBONE_COLOR}", penwidth=1.5, '
            'arrowsize=0.42];'
        )
    return lines


def _route_lines(
    assembly: GeneratedTopologyAssembly,
    result: Mapping[str, object],
) -> list[str]:
    transaction = result["transaction"]
    if not isinstance(transaction, Mapping):
        raise TypeError("topology result transaction must be a mapping")
    lines = []
    for channel, color, route in (
        ("REQ", REQ_COLOR, transaction["request_route"]),
        ("DAT", DAT_COLOR, transaction["data_route"]),
    ):
        for index, connection_name in enumerate(route):
            connection = assembly.system.connections[str(connection_name)]
            if not isinstance(connection, DirectedTransportConnection):
                raise TypeError("CHI route contains a non-transport connection")
            label = channel if index == len(route) // 2 else ""
            lines.append(
                f"  {connection.transmitter.dut} -> "
                f"{connection.receiver.dut} "
                f"[constraint=false, color={_quoted(color)}, "
                "penwidth=3.1, arrowsize=0.72, "
                f"label={_quoted(label)}, fontcolor={_quoted(color)}];"
            )
    return lines


def heterogeneous_ring_star_dot(
    assembly: GeneratedTopologyAssembly,
    result: Mapping[str, object],
) -> str:
    """Render the executed ring backbone and its uneven leaf attachment."""

    _validate_projection(assembly, result)
    if assembly.case != RING_CASE:
        raise ValueError("ring projection requires the ring-star case")
    positions = {
        "r0": (0.0, 0.0),
        "r1": (4.0, 3.0),
        "r2": (8.0, 0.0),
        "r3": (4.0, -3.0),
        "rn": (-3.0, 0.0),
        "leaf_a": (1.8, 6.0),
        "leaf_b": (6.2, 6.0),
        "hn": (11.0, 0.0),
    }
    if set(positions) != set(assembly.system.virtual_duts):
        raise ValueError("ring presentation positions do not match the system")

    topology = result["topology"]
    transaction = result["transaction"]
    lines = [
        "digraph chi_ring_star {",
        '  graph [layout=neato, overlap=false, splines=curved, '
        'bgcolor="white", pad=0.55, outputorder=edgesfirst, '
        'labelloc="t", label="CHI Issue H · nonuniform ring + leaf stars", '
        'fontname="sans-serif", fontsize=19];',
        '  node [fontname="sans-serif", fontsize=10, fixedsize=true];',
        '  edge [fontname="sans-serif", fontsize=9];',
    ]
    for router in assembly.routers:
        x, y = positions[router]
        local_count = sum(
            endpoint.router == router for endpoint in assembly.endpoints
        )
        local_label = (
            "transit-only"
            if local_count == 0
            else f"{local_count} local endpoint"
            + ("s" if local_count != 1 else "")
        )
        lines.append(
            f"  {router} [pos={_quoted(f'{x},{y}!')}, pin=true, "
            "shape=box, width=1.35, height=0.80, "
            f'style="rounded,filled", fillcolor="{ROUTER_FILL}", '
            f'color="{ROUTER_COLOR}", '
            f"label={_quoted(router.upper() + chr(10) + local_label)}];"
        )
    for endpoint in assembly.endpoints:
        x, y = positions[endpoint.name]
        fill, color = _endpoint_style(endpoint.role)
        lines.append(
            f"  {endpoint.name} [pos={_quoted(f'{x},{y}!')}, pin=true, "
            "shape=box, fixedsize=false, width=2.08, height=1.06, "
            f'style="rounded,filled", fillcolor="{fill}", color="{color}", '
            "label="
            f"{_quoted(_endpoint_label(endpoint.name, endpoint.role, endpoint.node_id))}"
            "];"
        )
    lines.extend(_base_edge_lines(assembly))
    lines.extend(_route_lines(assembly, result))
    lines.extend(
        (
            '  legend [pos="4,-5.2!", pin=true, fixedsize=false, '
            'shape=plain, label=<',
            '    <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="8"><TR>',
            f'      <TD><FONT COLOR="{REQ_COLOR}">● REQ path</FONT></TD>',
            f'      <TD><FONT COLOR="{DAT_COLOR}">● DAT return</FONT></TD>',
            f'      <TD><FONT COLOR="{BACKBONE_COLOR}">'
            "● declared bidirectional hop pair</FONT></TD>",
            "    </TR><TR><TD COLSPAN=\"3\"><FONT POINT-SIZE=\"9\" "
            'COLOR="#475569">',
            f"      {topology['directed_hop_count']} directed hops · "
            f"{topology['exact_route_count']} exact routes · "
            f"{len(transaction['request_route'])}+"
            f"{len(transaction['data_route'])} executed hops",
            "    </FONT></TD></TR><TR><TD COLSPAN=\"3\">"
            '<FONT POINT-SIZE="9" COLOR="#475569">',
            "      The leaf cluster is not a shared bus; each line is an "
            "explicit point-to-point attachment.",
            "    </FONT></TD></TR></TABLE>",
            "  >];",
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def four_by_four_mesh_dot(
    assembly: GeneratedTopologyAssembly,
    result: Mapping[str, object],
) -> str:
    """Render the generated 4x4 mesh and one corner round trip."""

    _validate_projection(assembly, result)
    if assembly.case != MESH_CASE:
        raise ValueError("mesh projection requires the 4x4 case")
    router_positions = {
        f"r{x}{y}": (x * 2.25, y * 2.25)
        for x in range(4)
        for y in range(4)
    }
    endpoint_positions = {
        "rn": (-2.5, 0.0),
        "corner_a": (-2.5, 6.75),
        "corner_b": (9.25, 0.0),
        "hn": (9.25, 6.75),
    }
    if set(router_positions) != set(assembly.routers):
        raise ValueError("mesh presentation positions do not match routers")
    if set(endpoint_positions) != {
        endpoint.name for endpoint in assembly.endpoints
    }:
        raise ValueError("mesh presentation positions do not match endpoints")

    topology = result["topology"]
    transaction = result["transaction"]
    lines = [
        "digraph chi_four_by_four_mesh {",
        '  graph [layout=neato, overlap=false, splines=line, '
        'bgcolor="white", pad=0.55, outputorder=edgesfirst, '
        'labelloc="t", label="CHI Issue H · generated 4×4 mesh", '
        'fontname="sans-serif", fontsize=19];',
        '  node [fontname="sans-serif", fontsize=9, fixedsize=true];',
        '  edge [fontname="sans-serif", fontsize=8];',
    ]
    for router, (x, y) in router_positions.items():
        lines.append(
            f"  {router} [pos={_quoted(f'{x},{y}!')}, pin=true, "
            "shape=box, width=0.70, height=0.56, "
            f'style="rounded,filled", fillcolor="{ROUTER_FILL}", '
            f'color="{ROUTER_COLOR}", label={_quoted(router.upper())}];'
        )
    for endpoint in assembly.endpoints:
        x, y = endpoint_positions[endpoint.name]
        fill, color = _endpoint_style(endpoint.role)
        display_name = {
            "rn": "RN requester",
            "hn": "Home",
        }.get(
            endpoint.name,
            endpoint.name.replace("_", " ").title(),
        )
        lines.append(
            f"  {endpoint.name} [pos={_quoted(f'{x},{y}!')}, pin=true, "
            "shape=box, width=1.58, height=0.84, "
            f'style="rounded,filled", fillcolor="{fill}", color="{color}", '
            "label="
            f"{_quoted(display_name + chr(10) + ('executed' if endpoint.role != 'leaf' else 'declared · idle'))}"
            "];"
        )
    lines.extend(_base_edge_lines(assembly))
    lines.extend(_route_lines(assembly, result))
    lines.extend(
        (
            '  legend [pos="3.38,-2.25!", pin=true, fixedsize=false, '
            'shape=plain, label=<',
            '    <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="8"><TR>',
            f'      <TD><FONT COLOR="{REQ_COLOR}">● REQ · X then Y</FONT></TD>',
            f'      <TD><FONT COLOR="{DAT_COLOR}">● DAT · X then Y</FONT></TD>',
            f'      <TD><FONT COLOR="{BACKBONE_COLOR}">'
            "● declared, not traversed here</FONT></TD>",
            "    </TR><TR><TD COLSPAN=\"3\"><FONT POINT-SIZE=\"9\" "
            'COLOR="#475569">',
            f"      {topology['router_count']} routers · "
            f"{topology['physical_backbone_edge_count']} physical grid edges · "
            f"{topology['directed_hop_count']} directed hops · "
            f"{topology['exact_route_count']} exact routes",
            "    </FONT></TD></TR><TR><TD COLSPAN=\"3\">"
            '<FONT POINT-SIZE="9" COLOR="#475569">',
            f"      One corner round trip executes "
            f"{len(transaction['request_route'])}+"
            f"{len(transaction['data_route'])} hops; grey interior links "
            "remain declared topology.",
            "    </FONT></TD></TR></TABLE>",
            "  >];",
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def _display_route(nodes: object) -> str:
    if not isinstance(nodes, (tuple, list)):
        raise TypeError("route nodes must be a sequence")
    return " → ".join(str(node).upper() for node in nodes)


def route_comparison_dot(
    cases: Mapping[
        str,
        tuple[GeneratedTopologyAssembly, Mapping[str, object]],
    ],
) -> str:
    """Compare executed routes without presenting scheduler time as latency."""

    rows = []
    labels = {
        RING_CASE: "Ring + leaf stars",
        MESH_CASE: "4×4 mesh",
    }
    for case in (RING_CASE, MESH_CASE):
        _, result = cases[case]
        topology = result["topology"]
        transaction = result["transaction"]
        rows.append(
            "<TR>"
            f'<TD ALIGN="LEFT"><B>{escape(labels[case])}</B></TD>'
            f'<TD>{topology["router_count"]}</TD>'
            f'<TD>{topology["directed_hop_count"]}</TD>'
            f'<TD>{topology["exact_route_count"]}</TD>'
            '<TD ALIGN="LEFT"><FONT COLOR="#2563eb">'
            f'{escape(_display_route(transaction["request_nodes"]))}'
            "</FONT><BR ALIGN=\"LEFT\"/>"
            '<FONT COLOR="#c026d3">'
            f'{escape(_display_route(transaction["data_nodes"]))}'
            "</FONT></TD>"
            f'<TD>{escape(str(result["verdict"]))}</TD>'
            "</TR>"
        )
    return "\n".join(
        (
            "digraph chi_route_comparison {",
            '  graph [bgcolor="white", pad=0.4, labelloc="t", '
            'label="Same restricted operation · two caller-built topologies", '
            'fontname="sans-serif", fontsize=18];',
            '  node [shape=plain, fontname="sans-serif", fontsize=10];',
            "  comparison [label=<",
            '    <TABLE BORDER="1" COLOR="#cbd5e1" CELLBORDER="0" '
            'CELLSPACING="0" CELLPADDING="9">',
            '      <TR><TD BGCOLOR="#f8fafc"><B>Case</B></TD>'
            '<TD BGCOLOR="#f8fafc"><B>Routers</B></TD>'
            '<TD BGCOLOR="#f8fafc"><B>Directed hops</B></TD>'
            '<TD BGCOLOR="#f8fafc"><B>Exact routes</B></TD>'
            '<TD BGCOLOR="#f8fafc"><B>Executed REQ / DAT node path</B></TD>'
            '<TD BGCOLOR="#f8fafc"><B>Result</B></TD></TR>',
            *rows,
            '      <TR><TD COLSPAN="6" ALIGN="LEFT" BGCOLOR="#eff6ff">'
            "<B>Executed common contract:</B> ReadNoSnp → CompData, "
            "TxnID correlation, finite router queues, per-hop Link Credit, "
            "exact NodeID routing, and final quiescence.</TD></TR>",
            '      <TR><TD COLSPAN="6" ALIGN="LEFT" BGCOLOR="#fff7ed">'
            "<B>Not established by these shapes:</B> shared-bus arbitration, "
            "RSP/SNP coherence, adaptive routing, CHI completeness, "
            "performance, fairness, or deadlock freedom.</TD></TR>",
            "    </TABLE>",
            "  >];",
            "}",
        )
    ) + "\n"


def guide(
    cases: Mapping[
        str,
        tuple[GeneratedTopologyAssembly, Mapping[str, object]],
    ],
) -> str:
    """Build the generated result-specific navigation page."""

    _, ring = cases[RING_CASE]
    _, mesh = cases[MESH_CASE]
    ring_topology = ring["topology"]
    mesh_topology = mesh["topology"]
    ring_transaction = ring["transaction"]
    mesh_transaction = mesh["transaction"]
    return f"""# CHI Issue H：同一事务经过两种调用方拓扑

本页执行同一条受限 `ReadNoSnp → CompData` 生命周期，但让调用方提供两种不同
`SystemProtocol` topology。目的不是用网络外观代替协议覆盖，而是展示现有 CHI participant、
有限 store-and-forward router、exact NodeID route 和逐跳 transport 能在不同固定拓扑上组合。

## 非均匀 ring backbone + leaf stars

![非均匀双向环形骨干](heterogeneous-ring-star.svg)

四个 router 构成双向 ring backbone。R0 挂 requester，R2 挂 Home，R1 同时挂两个声明但本次空闲的
leaf endpoint，R3 则是 transit-only。这个不均匀 attachment 使 topology 不再只是对称方框：
本次 REQ 使用 `{_display_route(ring_transaction['request_nodes'])}`，DAT 走
`{_display_route(ring_transaction['data_nodes'])}`，合起来覆盖 ring 的四条物理边。

这里的“star”只描述 R1 周围的点到点叶节点簇。它不是 multi-drop shared bus，也没有从图形推断
broadcast 或共享介质仲裁。实际系统包含 {ring_topology['directed_hop_count']} 条有向 hop 和
{ring_topology['exact_route_count']} 条 router exact-route entry。

## 4×4 bidirectional mesh

![4×4 mesh 与角到角路径](four-by-four-mesh.svg)

第二个 case 生成 16 个 router、{mesh_topology['physical_backbone_edge_count']} 条物理 grid edge、
{mesh_topology['directed_backbone_hop_count']} 条有向 backbone hop，再加四个角点 endpoint 的
双向 attachment。每个 router 为四个 endpoint 建立 exact NodeID route，因此共有
{mesh_topology['exact_route_count']} 条 route entry。

REQ 与 DAT 各执行 {len(mesh_transaction['request_route'])} 条有向 hop，采用确定性的 X-then-Y
选择并在角到角往返后静默。灰色 interior edge 是已 elaborated、route table 已覆盖但这一次事务没有穿过的
topology；图没有暗示一笔 read 已经动态扫遍所有 mesh link。

## 对照与边界

![两种拓扑的已执行路径与能力边界](route-comparison.svg)

两案都实际检查了 completion、返回值、每个已执行 hop 的 lineage、router accept/forward 计数和最终
quiescence。reference microstep 数只记录确定性模型执行，不是吞吐或物理延迟测量。

这两个 case 当前集中在 REQ/DAT direct read。它们不建立 shared-bus/broadcast 语义，不包含
RSP/SNP coherence、Retry/error 组合或 adaptive routing，也不构成完整 CHI compliance、QoS/fairness
结论或 deadlock proof。clean coherence 的状态闭合需要另外的 ReadUnique/Snoop witness。

机器结果见 [result.json](result.json)，三张图的可检查 DOT 源见 [sources](sources/)，构造与宣称边界见
[provenance.json](provenance.json)，发布文件清单见 [manifest.json](manifest.json)。
"""


__all__ = [
    "four_by_four_mesh_dot",
    "guide",
    "heterogeneous_ring_star_dot",
    "route_comparison_dot",
]
