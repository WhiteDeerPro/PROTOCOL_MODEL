"""Compact topology projections for the CHI Issue H flow gallery.

Resolved-network cases are projected from their elaborated
``SystemProtocol`` connections.  A participant-runtime fallback remains for
other callers that deliberately have no transport construction; its dashed
edges summarize only model-emitted packet interactions at that boundary.
"""

from __future__ import annotations

from collections import defaultdict
import json

from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiNetworkPacket,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    ChiCoherenceNetworkSession,
    ChiCoherenceSession,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    ChiTransportLinkProfile,
)
from protocol_model.system import (
    DirectedTransportConnection,
    InterfaceConnection,
)
from showcase.demos.chi.issue_h_flow_gallery.model import FlowGalleryCase


_CHANNEL_ATTRIBUTES = (
    ("request", ChiChannelKind.REQ),
    ("response", ChiChannelKind.RSP),
    ("snoop", ChiChannelKind.SNP),
    ("data", ChiChannelKind.DAT),
)
_ROLE_STYLE = {
    "requester": ("#dbeafe", "#2563eb"),
    "home": ("#ffedd5", "#ea580c"),
    "snoopee": ("#dcfce7", "#16a34a"),
    "forwarder": ("#ede9fe", "#7c3aed"),
}
_ROLE_LABEL = {
    "requester": "requester",
    "home": "home",
    "snoopee": "snoopee",
    "forwarder": "routing forwarder (XP abstraction)",
}


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _role_text(roles: set[str]) -> str:
    ordered = tuple(
        role
        for role in ("requester", "home", "snoopee", "forwarder")
        if role in roles
    )
    extras = tuple(sorted(roles - set(ordered)))
    labels = tuple(_ROLE_LABEL[role] for role in ordered)
    return " / ".join((*labels, *extras)) if roles else "VirtualDut"


def _node_style(roles: set[str]) -> tuple[str, str]:
    for role in ("home", "requester", "snoopee", "forwarder"):
        if role in roles:
            return _ROLE_STYLE[role]
    return "#f8fafc", "#64748b"


def _channels(profile: object) -> tuple[ChiChannelKind, ...]:
    if not isinstance(profile, ChiTransportLinkProfile):
        return ()
    return tuple(
        channel
        for attribute, channel in _CHANNEL_ATTRIBUTES
        if getattr(profile, attribute) is not None
    )


def _channel_text(channels: tuple[ChiChannelKind, ...] | set[ChiChannelKind]) -> str:
    return "/".join(
        channel.value.upper()
        for channel in ChiChannelKind
        if channel in channels
    )


def _resolved_topology_dot(case: FlowGalleryCase) -> str:
    session = case.execution.session
    if not isinstance(session, ChiCoherenceNetworkSession):
        raise TypeError("resolved topology projection requires a network session")
    resolved = session.resolved
    system = resolved.system.spec

    roles_by_binding: dict[str, set[str]] = defaultdict(set)
    for role, participant in resolved.feature_contract.roles.items():
        roles_by_binding[participant].add(role)
    for role, participants in resolved.feature_contract.role_sets.items():
        for participant in participants:
            roles_by_binding[participant].add(role)

    bindings_by_dut: dict[str, list[object]] = defaultdict(list)
    for binding in resolved.binding_by_name.values():
        bindings_by_dut[binding.dut.name].append(binding)
    for binding in resolved.forwarding_bindings:
        if binding not in bindings_by_dut[binding.dut.name]:
            bindings_by_dut[binding.dut.name].append(binding)

    graph_label = case.title + "\nresolved SystemProtocol topology"
    lines = [
        f"digraph {_quoted('chi_flow_' + case.case_id)} {{",
        '  graph [rankdir=LR, bgcolor="white", pad=0.28, '
        'nodesep=0.42, ranksep=0.72, splines=polyline, '
        f'labelloc="t", label={_quoted(graph_label)}, '
        'fontname="sans-serif", fontsize=16];',
        '  node [shape=box, style="rounded,filled", '
        'fontname="sans-serif", fontsize=10, margin="0.13,0.08"];',
        '  edge [fontname="sans-serif", fontsize=8, color="#64748b", '
        'fontcolor="#334155", arrowsize=0.62];',
    ]

    for dut_name in system.virtual_duts:
        bindings = bindings_by_dut.get(dut_name, [])
        roles = {
            role
            for binding in bindings
            for role in roles_by_binding.get(binding.name, ())
        }
        if not roles and bindings:
            roles.add("forwarder")
        node_ids = sorted(
            {
                node_id
                for binding in bindings
                for node_id in binding.node_ids
            }
        )
        participant_names = tuple(
            binding.name
            for binding in bindings
            if binding.name != dut_name
        )
        label_parts = [dut_name.upper(), _role_text(roles)]
        if participant_names:
            label_parts.append("participant " + ", ".join(participant_names))
        if node_ids:
            label_parts.append(
                "NodeID "
                + ", ".join(f"0x{node_id:x}" for node_id in node_ids)
            )
        fill, color = _node_style(roles)
        lines.append(
            f"  {_quoted(dut_name)} [label={_quoted(chr(10).join(label_parts))}, "
            f'fillcolor="{fill}", color="{color}"];'
        )

    connection_count = 0
    for connection in system.connections.values():
        if isinstance(connection, DirectedTransportConnection):
            connection_count += 1
            channel_text = _channel_text(_channels(connection.profile))
            label = f"{connection.name}\ntransport"
            if channel_text:
                label += f" · {channel_text}"
            tooltip = (
                connection.transmitter.qualified_name
                + " → "
                + connection.receiver.qualified_name
            )
            lines.append(
                f"  {_quoted(connection.transmitter.dut)} -> "
                f"{_quoted(connection.receiver.dut)} "
                f"[label={_quoted(label)}, "
                f"tooltip={_quoted(tooltip)}];"
            )
            continue
        if isinstance(connection, InterfaceConnection):
            endpoints = tuple(connection.endpoints.items())
            if len(endpoints) != 2:
                raise ValueError(
                    "compact CHI topology projection requires binary "
                    "InterfaceConnection values"
                )
            connection_count += 1
            (first_role, first), (second_role, second) = endpoints
            label = (
                connection.name
                + "\ninterface · "
                + first_role
                + "/"
                + second_role
            )
            lines.append(
                f"  {_quoted(first.dut)} -> {_quoted(second.dut)} "
                f"[dir=both, label={_quoted(label)}];"
            )
            continue
        raise TypeError(
            f"unsupported SystemProtocol connection {type(connection).__name__}"
        )

    forwarding_count = len(resolved.forwarding_bindings)
    routing_boundary = (
        f"{forwarding_count} XP-like forwarding abstraction"
        + ("s are" if forwarding_count != 1 else " is")
        + " shown explicitly"
        if forwarding_count
        else "direct participant topology · no XP-like forwarder constructed"
    )
    evidence_label = (
        f"{len(system.virtual_duts)} VirtualDuts · "
        f"{connection_count} declared connections\n"
        "solid arrows come from resolved construction\n"
        f"{routing_boundary}\n"
        "flow time-space omits per-hop transport MOVE events"
    )
    lines.extend(
        (
            '  evidence [shape=note, style="filled", fillcolor="#f8fafc", '
            'color="#94a3b8", fontsize=8, '
            f"label={_quoted(evidence_label)}];",
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def _participant_boundary_dot(case: FlowGalleryCase) -> str:
    session = case.execution.session
    if not isinstance(session, ChiCoherenceSession):
        raise TypeError(
            "participant-boundary projection requires ChiCoherenceSession"
        )

    participants = {
        session.home.node_id: (
            session.home.name,
            {"home"},
        )
    }
    for node_id, node in session.request_nodes.items():
        roles = set()
        if node_id in session.requester_node_ids:
            roles.add("requester")
        if node_id in session.snoopee_node_ids:
            roles.add("snoopee")
        participants[node_id] = (node.name, roles)

    interactions: dict[
        tuple[int, int],
        list[ChiNetworkPacket],
    ] = defaultdict(list)
    for emission in case.execution.emissions:
        if not isinstance(emission, ChiNetworkPacket):
            raise TypeError(
                "participant-boundary evidence contains a non-packet emission"
            )
        if (
            emission.source_id not in participants
            or emission.target_id not in participants
        ):
            raise ValueError(
                "participant-boundary packet references an unknown NodeID"
            )
        interactions[(emission.source_id, emission.target_id)].append(
            emission
        )

    graph_label = case.title + "\nparticipant interaction boundary"
    lines = [
        f"digraph {_quoted('chi_flow_' + case.case_id)} {{",
        '  graph [rankdir=LR, bgcolor="white", pad=0.28, '
        'nodesep=0.46, ranksep=0.78, splines=polyline, '
        f'labelloc="t", label={_quoted(graph_label)}, '
        'fontname="sans-serif", fontsize=16];',
        '  node [shape=box, style="rounded,filled", '
        'fontname="sans-serif", fontsize=10, margin="0.13,0.08"];',
        '  edge [style=dashed, penwidth=1.5, fontname="sans-serif", '
        'fontsize=8, color="#64748b", fontcolor="#334155", '
        'arrowsize=0.62];',
    ]
    for node_id, (name, roles) in participants.items():
        fill, color = _node_style(roles)
        display_name = name.removesuffix(".coherence")
        node_label = (
            f"{display_name}\n{_role_text(roles)}\nNodeID 0x{node_id:x}"
        )
        lines.append(
            f"  {_quoted(f'node-{node_id}')} "
            f"[label={_quoted(node_label)}, "
            f'fillcolor="{fill}", color="{color}", '
            f"tooltip={_quoted(name)}];"
        )

    for (source_id, target_id), packets in sorted(interactions.items()):
        channels = {packet.channel for packet in packets}
        opcodes = tuple(
            dict.fromkeys(
                type(packet.message).__name__
                .removeprefix("Chi")
                .removesuffix("Message")
                for packet in packets
            )
        )
        label = (
            f"participant packets · {_channel_text(channels)}\n"
            f"{len(packets)} emitted"
        )
        lines.append(
            f"  {_quoted(f'node-{source_id}')} -> "
            f"{_quoted(f'node-{target_id}')} "
            f"[label={_quoted(label)}, tooltip={_quoted(', '.join(opcodes))}];"
        )

    boundary_label = (
        "dashed = model-emitted participant packets\n"
        "no transport connections or hop execution claimed"
    )
    lines.extend(
        (
            '  boundary [shape=note, style="filled", fillcolor="#fff7ed", '
            'color="#f97316", fontsize=8, '
            f"label={_quoted(boundary_label)}];",
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def flow_case_topology_dot(case: FlowGalleryCase) -> str:
    """Return a compact evidence-backed topology/boundary DOT projection."""

    if not isinstance(case, FlowGalleryCase):
        raise TypeError("flow topology projection requires FlowGalleryCase")
    session = case.execution.session
    if isinstance(session, ChiCoherenceNetworkSession):
        return _resolved_topology_dot(case)
    if isinstance(session, ChiCoherenceSession):
        return _participant_boundary_dot(case)
    raise TypeError(
        "flow topology projection requires a resolved-network or "
        "participant-level CHI coherence session"
    )


__all__ = ["flow_case_topology_dot"]
