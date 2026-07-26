"""Small explanatory projections for the executable CHI 2×2 mesh."""

from __future__ import annotations

from html import escape
import json


CHANNEL_COLORS = {
    "req": "#2563eb",
    "rsp": "#d97706",
    "snp": "#059669",
    "dat": "#c026d3",
}


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _node_label(name: str) -> str:
    return name.upper() if name.startswith(("xp", "rn", "hn")) else name


def _route_label(route: tuple[str, ...] | list[str]) -> str:
    if not route:
        return ""
    first_source, first_target = route[0].split("_to_", 1)
    nodes = [first_source, first_target]
    for connection in route[1:]:
        source, target = connection.split("_to_", 1)
        if source != nodes[-1]:
            nodes.append(source)
        nodes.append(target)
    return " → ".join(_node_label(item) for item in nodes)


def _packet(
    result: dict[str, object],
    message: str,
    *,
    source_id: int | None = None,
    target_id: int | None = None,
) -> dict[str, object]:
    matches = tuple(
        packet
        for packet in result["packets"]
        if packet["message"] == message
        and (source_id is None or packet["source_id"] == source_id)
        and (target_id is None or packet["target_id"] == target_id)
    )
    if len(matches) != 1:
        raise ValueError(
            f"expected one {message} packet, found {len(matches)}"
        )
    return matches[0]


def topology_dot(assembly, result: dict[str, object]) -> str:
    """Project the actual SystemProtocol into a fixed four-XP square.

    Positions are presentation metadata local to this example.  Node and edge
    membership still comes from the executed assembly.
    """

    expected_nodes = {
        "rn0",
        "rn1",
        "rn2",
        "hn0",
        "xp00",
        "xp10",
        "xp11",
        "xp01",
    }
    if set(assembly.system.virtual_duts) != expected_nodes:
        raise ValueError("the clean-mesh topology projection received another system")
    physical_edges = {
        frozenset(edge) for edge in result["topology"]["physical_ring_edges"]
    }
    expected_edges = {
        frozenset(("xp00", "xp10")),
        frozenset(("xp10", "xp11")),
        frozenset(("xp11", "xp01")),
        frozenset(("xp01", "xp00")),
    }
    if physical_edges != expected_edges:
        raise ValueError("the executed topology is not the expected XP square")

    lines = [
        "digraph chi_clean_mesh {",
        '  graph [layout=neato, overlap=false, splines=polyline, '
        'bgcolor="white", pad=0.55, outputorder=edgesfirst, '
        'labelloc="t", label="CHI Issue H · clean ReadUnique on a 2×2 XP mesh", '
        'fontname="sans-serif", fontsize=18];',
        '  node [fontname="sans-serif", fontsize=11, fixedsize=true];',
        '  edge [fontname="sans-serif", fontsize=9, penwidth=2.2, '
        'arrowsize=0.65];',
        '  xp00 [pos="0,4!", pin=true, shape=box, width=1.15, height=0.78, '
        'style="rounded,filled", fillcolor="#ede9fe", color="#7c3aed", '
        'label="XP00\\nNW"];',
        '  xp10 [pos="5.4,4!", pin=true, shape=box, width=1.15, height=0.78, '
        'style="rounded,filled", fillcolor="#ede9fe", color="#7c3aed", '
        'label="XP10\\nNE"];',
        '  xp11 [pos="5.4,0!", pin=true, shape=box, width=1.15, height=0.78, '
        'style="rounded,filled", fillcolor="#ede9fe", color="#7c3aed", '
        'label="XP11\\nSE"];',
        '  xp01 [pos="0,0!", pin=true, shape=box, width=1.15, height=0.78, '
        'style="rounded,filled", fillcolor="#ede9fe", color="#7c3aed", '
        'label="XP01\\nSW"];',
        '  rn0 [pos="-3.15,4!", pin=true, shape=box, width=1.72, height=0.82, '
        'style="rounded,filled", fillcolor="#dbeafe", color="#2563eb", '
        'label="RN0 · requester\\nI → UC"];',
        '  rn1 [pos="8.55,4!", pin=true, shape=box, width=1.72, height=0.82, '
        'style="rounded,filled", fillcolor="#dcfce7", color="#16a34a", '
        'label="RN1 · snoopee\\nSC → I"];',
        '  hn0 [pos="8.55,0!", pin=true, shape=box, width=1.72, height=0.82, '
        'style="rounded,filled", fillcolor="#ffedd5", color="#ea580c", '
        'label="HN0 · Home\\nsharers → owner"];',
        '  rn2 [pos="-3.15,0!", pin=true, shape=box, width=1.72, height=0.82, '
        'style="rounded,filled", fillcolor="#dcfce7", color="#16a34a", '
        'label="RN2 · snoopee\\nSC → I"];',
        # The multi-color values render parallel strokes.  They summarize
        # channel families that actually used each physical side.
        '  xp00 -> xp10 [dir=both, color="#2563eb:#d97706", '
        'label="REQ · CompAck"];',
        '  xp10 -> xp11 [dir=both, color="#2563eb:#059669:#d97706", '
        'label="REQ · SNP/RSP₁ · CompAck"];',
        '  xp11 -> xp01 [dir=both, color="#059669:#c026d3:#d97706", '
        'label="SNP/RSP₂ · DAT"];',
        '  xp01 -> xp00 [dir=both, color="#c026d3", label="DAT"];',
        '  rn0 -> xp00 [dir=both, color="#64748b"];',
        '  xp10 -> rn1 [dir=both, color="#64748b"];',
        '  hn0 -> xp11 [dir=both, color="#64748b"];',
        '  xp01 -> rn2 [dir=both, color="#64748b"];',
        '  legend [pos="2.7,-1.55!", pin=true, fixedsize=false, '
        'shape=plain, label=<',
        '    <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="8"><TR>',
        '      <TD><FONT COLOR="#2563eb">● REQ</FONT></TD>',
        '      <TD><FONT COLOR="#059669">● SNP</FONT></TD>',
        '      <TD><FONT COLOR="#d97706">● RSP</FONT></TD>',
        '      <TD><FONT COLOR="#c026d3">● DAT</FONT></TD>',
        '    </TR><TR><TD COLSPAN="4"><FONT POINT-SIZE="9" COLOR="#64748b">',
        '      Four physical sides are exercised; each side is two directed hops.',
        '    </FONT></TD></TR></TABLE>',
        '  >];',
        "}",
    ]
    return "\n".join(lines) + "\n"


def sequence_dot(result: dict[str, object]) -> str:
    """Show participant messages while keeping XP paths as secondary labels."""

    read = _packet(result, "ChiReadUniqueMessage")
    snp1 = _packet(result, "ChiSnpUniqueMessage", target_id=0x08)
    snp2 = _packet(result, "ChiSnpUniqueMessage", target_id=0x09)
    rsp1 = _packet(result, "ChiSnpRespMessage", source_id=0x08)
    rsp2 = _packet(result, "ChiSnpRespMessage", source_id=0x09)
    data = _packet(result, "ChiCompDataMessage")
    ack = _packet(result, "ChiCompAckMessage")
    messages = (
        ("rn0", "hn0", "ReadUnique", read),
        ("hn0", "rn1", "SnpUnique", snp1),
        ("hn0", "rn2", "SnpUnique", snp2),
        ("rn1", "hn0", "SnpResp(I)", rsp1),
        ("rn2", "hn0", "SnpResp(I)", rsp2),
        ("hn0", "rn0", "CompData(UC)", data),
        ("rn0", "hn0", "CompAck", ack),
    )
    columns = ("rn0", "hn0", "rn1", "rn2")
    headers = {
        "rn0": "RN0\nrequester",
        "hn0": "HN0\nHome",
        "rn1": "RN1\nsnoopee",
        "rn2": "RN2\nsnoopee",
    }
    lines = [
        "digraph chi_clean_sequence {",
        "  rankdir=TB;",
        '  graph [bgcolor="white", pad=0.45, nodesep=0.88, ranksep=0.63, '
        'splines=polyline, outputorder=edgesfirst, labelloc="t", '
        'label="Clean ReadUnique · participant sequence", '
        'fontname="sans-serif", fontsize=18];',
        '  node [fontname="sans-serif", fontsize=10];',
        '  edge [fontname="sans-serif", fontsize=9, arrowsize=0.72, '
        'penwidth=1.8];',
    ]
    for column in columns:
        fill = "#ffedd5" if column == "hn0" else "#e0f2fe"
        color = "#ea580c" if column == "hn0" else "#0284c7"
        lines.append(
            f"  h_{column} [shape=box, group={_quoted(column)}, "
            f"style=\"rounded,filled\", "
            f"fillcolor={_quoted(fill)}, color={_quoted(color)}, "
            f"label={_quoted(headers[column])}];"
        )
    lines.append(
        "  { rank=same; "
        + "; ".join(f"h_{column}" for column in columns)
        + "; }"
    )
    lines.append(
        "  h_rn0 -> h_hn0 -> h_rn1 -> h_rn2 "
        '[style=invis, weight=100];'
    )

    for index, (source, target, label, packet) in enumerate(messages, 1):
        for column in columns:
            lines.append(
                f'  e{index}_{column} [shape=point, group={_quoted(column)}, '
                'width=0.055, '
                'height=0.055, label="", color="#94a3b8"];'
            )
        lines.append(
            "  { rank=same; "
            + "; ".join(f"e{index}_{column}" for column in columns)
            + "; }"
        )
        lines.append(
            "  "
            + " -> ".join(f"e{index}_{column}" for column in columns)
            + " [style=invis, weight=100];"
        )
        color = CHANNEL_COLORS[packet["channel"]]
        route = _route_label(packet["route"])
        message_label = f"{label}\n{route}"
        lines.append(
            f"  e{index}_{source} -> e{index}_{target} "
            f"[constraint=false, color={_quoted(color)}, "
            f"fontcolor={_quoted(color)}, "
            f"xlabel={_quoted(message_label)}];"
        )

    for column in columns:
        chain = [f"h_{column}", *(
            f"e{index}_{column}" for index in range(1, len(messages) + 1)
        )]
        lines.append(
            "  "
            + " -> ".join(chain)
            + ' [color="#cbd5e1", style=dashed, arrowhead=none, '
            'penwidth=1.0, weight=1000];'
        )
    lines.extend(
        (
            '  note [shape=note, style=filled, fillcolor="#f8fafc", '
            'color="#94a3b8", label="Vertical order is committed model '
            'causality, not a clock scale.\\nXP names in message labels are '
            'the resolved packet route."];',
            f"  e{len(messages)}_rn2 -> note "
            '[style=invis, weight=1];',
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def _state_cell(state: str) -> tuple[str, str]:
    return {
        "I": ("#e2e8f0", "#475569"),
        "SC": ("#dcfce7", "#15803d"),
        "UC": ("#ede9fe", "#7c3aed"),
    }[state]


def _snapshot_table(
    title: str,
    snapshot: dict[str, object],
) -> str:
    rows = []
    for participant in ("rn0", "rn1", "rn2"):
        state = snapshot[participant]
        fill, color = _state_cell(state)
        rows.append(
            f'<TR><TD ALIGN="LEFT">{participant.upper()}</TD>'
            f'<TD BGCOLOR="{fill}"><FONT COLOR="{color}"><B>'
            f"{escape(state)}</B></FONT></TD></TR>"
        )
    home = snapshot["home"]
    owner = (
        "—"
        if home["unique_owner"] is None
        else f"RN{home['unique_owner'] - 7}"
    )
    sharers = (
        "—"
        if not home["sharers"]
        else ", ".join(f"RN{node_id - 7}" for node_id in home["sharers"])
    )
    rows.append(
        '<TR><TD ALIGN="LEFT">Home directory</TD>'
        f'<TD ALIGN="LEFT">sharers: {escape(sharers)}<BR/>'
        f"unique owner: {escape(owner)}</TD></TR>"
    )
    return (
        '<<TABLE BORDER="1" COLOR="#cbd5e1" CELLBORDER="0" '
        'CELLSPACING="0" CELLPADDING="10">'
        f'<TR><TD COLSPAN="2" BGCOLOR="#f8fafc"><B>{escape(title)}</B></TD></TR>'
        + "".join(rows)
        + "</TABLE>>"
    )


def coherence_state_dot(result: dict[str, object]) -> str:
    """Render the stable clean-coherence state before and after the run."""

    before = result["coherence"]["before"]
    after = result["coherence"]["after"]
    return "\n".join(
        (
            "digraph chi_clean_state {",
            "  rankdir=LR;",
            '  graph [bgcolor="white", pad=0.45, nodesep=0.9, '
            'labelloc="t", label="Stable clean-coherence state", '
            'fontname="sans-serif", fontsize=18];',
            '  node [shape=plain, fontname="sans-serif", fontsize=11];',
            '  edge [fontname="sans-serif", fontsize=10, color="#7c3aed", '
            'fontcolor="#7c3aed", penwidth=2.3, arrowsize=0.8];',
            f"  before [label={_snapshot_table('Before · line 0x8000', before)}];",
            f"  after [label={_snapshot_table('After · line 0x8000', after)}];",
            '  before -> after [label="ReadUnique lifecycle\\n7 protocol packets"];',
            '  note [shape=note, style=filled, fillcolor="#f8fafc", '
            'color="#94a3b8", label="I = Invalid\\nSC = Shared Clean\\n'
            'UC = Unique Clean"];',
            "  after -> note [style=dashed, color=\"#94a3b8\", arrowhead=none];",
            "}",
        )
    ) + "\n"


def guide(result: dict[str, object]) -> str:
    """Build the generated navigation page from this execution."""

    runtime = result["runtime"]
    topology = result["topology"]
    counts = result["message_counts"]
    return f"""# CHI Issue H：2×2 XP mesh 上的 Clean ReadUnique

![四 XP 方环拓扑](topology.svg)

四个 XP 组成 2×2 方形 mesh；在这个最小尺寸上，mesh 的四条边也构成一个环。RN0、RN1、HN0、RN2
分别挂在四角。图中的节点和连接来自本次实际 `SystemProtocol`，固定坐标只是这张讲解图的排版选择。

本次运行使用了 {len(topology['used_connections'])}/{len(topology['directed_connections'])} 条有向
connection，并覆盖全部四条物理边。未使用的两个反向 hop 是
`{', '.join(topology['unused_connections'])}`；拓扑允许双向通信，并不要求一笔事务遍历每个方向。

![事务消息与实际路径](transaction-sequence.svg)

一笔 `ReadUnique` 产生：

- {counts['ChiReadUniqueMessage']} 个 REQ；
- {counts['ChiSnpUniqueMessage']} 个 `SnpUnique` packet；
- {counts['ChiSnpRespMessage']} 个 `SnpResp`；
- {counts['ChiCompDataMessage']} 个 `CompData`；
- {counts['ChiCompAckMessage']} 个 `CompAck`。

消息下方的 XP 序列来自 resolved route。纵向仅表示模型提交的因果次序，不表示时钟周期距离。

![一致性稳定状态](coherence-state.svg)

初始 RN1/RN2 为 `SC`，Home directory 记录两个 sharer；完成后 RN0 为 `UC`，RN1/RN2 为 `I`，
Home 将 RN0 记作 unique owner。Home 同时发出的两份 snoop 经过容量为一的 egress 分批进入网络，
运行中待发送 batch 的最大深度为 {runtime['maximum_pending_egress']}，没有丢失 fan-out packet。

## 这个见证实际说明了什么

- caller 可以自由组装含环的 transport topology，CHI package 不固化 mesh；
- exact `TgtID + channel` 路由把每个 packet 解析到一条有限、无环的实际路径；
- 四个 XP 均执行有限队列的 store-and-forward；
- REQ、SNP、RSP、DAT 与 clean coherence participant state 在同一 session 中闭合；
- {runtime['committed_microsteps']} 个 reference microstep 后网络、participant transaction 和 pending
  egress 均静默。

## 当前范围

这是 clean-only `I/SC/UC` 的 `ReadUnique` 场景。它还不包含 dirty owner、完整 MESI/MOESI、
adaptive routing、Retry、router QoS/fairness 或网络 deadlock proof。物理拓扑存在环，只说明以后可以在
真实循环结构上建立 wait-for 分析，不等于本例已经证明无死锁。

三张图是 topology、packet route 和 stable state 的模型级投影，**不是 raw pin waveform**，也不规定
RTL 的流水级、空拍位置或周期距离。机器结果见 [result.json](result.json)，DOT 源见
[sources](sources/)，生成边界见 [provenance.json](provenance.json)。
"""


__all__ = [
    "coherence_state_dot",
    "guide",
    "sequence_dot",
    "topology_dot",
]
