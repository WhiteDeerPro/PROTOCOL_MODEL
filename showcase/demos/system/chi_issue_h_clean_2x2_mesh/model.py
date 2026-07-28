"""Executable clean-coherence traffic on a caller-built 2×2 CHI mesh.

The four XP VirtualDuts form a physical square.  Because every physical edge
is represented by two directed transport connections, the square is also the
smallest mesh that visibly contains a ring.  Per-target routing remains
acyclic: the cycle belongs to the available topology, not to one packet path.

This file only assembles existing CHI participants, transport links, routers,
capability closure, and the clean-coherence network scheduler.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from protocol_model.integrations.recipes.amba.chi import (
    bind_chi_issue_h_cache_lines,
    bind_chi_issue_h_home_vdut,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
    CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
    ChiBehaviorFacet,
    ChiCacheLine,
    ChiCacheState,
    ChiExactNodeRoute,
    ChiFacetKind,
    ChiHomeDirectoryEntry,
    ChiParticipantBinding,
    ChiParticipantCapability,
    ChiParticipantPortBinding,
    ChiStoreForwardRouterNode,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiIssueHRspProfile,
    ChiIssueHSnpProfile,
    ChiNetworkPacket,
    ChiReadUniqueMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    CHI_FEATURE_CLEAN_READ_UNIQUE,
    CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiCoherenceNetworkEvent,
    ChiCoherenceNetworkSession,
    ChiFeatureContract,
    ChiHomeAuthority,
    ChiSubmitCoherentRead,
    ResolvedChiSystem,
    resolve_chi_system,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiRspChannelProfile,
    ChiSnpChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.semantics import Verdict
from protocol_model.system import (
    AddressClaim,
    AddressWindow,
    ElaboratedSystemProtocol,
    SystemProtocol,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)


REQUESTER_NODE_ID = 0x07
FIRST_SNOOPEE_NODE_ID = 0x08
SECOND_SNOOPEE_NODE_ID = 0x09
HOME_NODE_ID = 0x21
LINE_ADDRESS = 0x8000
LINE_DATA = (1 << 400) | 0xC0DE

ALL_CHANNELS = frozenset(ChiChannelKind)
REQ_RSP = frozenset((ChiChannelKind.REQ, ChiChannelKind.RSP))
DAT_SNP = frozenset((ChiChannelKind.DAT, ChiChannelKind.SNP))
REQ = frozenset((ChiChannelKind.REQ,))
RSP = frozenset((ChiChannelKind.RSP,))
SNP = frozenset((ChiChannelKind.SNP,))
DAT = frozenset((ChiChannelKind.DAT,))

PHYSICAL_RING_EDGES = (
    ("xp00", "xp10"),
    ("xp10", "xp11"),
    ("xp11", "xp01"),
    ("xp01", "xp00"),
)


@dataclass(frozen=True)
class CleanMeshAssembly:
    """Construction objects retained for execution and projection."""

    system: SystemProtocol
    elaborated: ElaboratedSystemProtocol
    resolved: ResolvedChiSystem
    session: ChiCoherenceNetworkSession
    request: ChiReadUniqueMessage
    bindings: dict[str, ChiParticipantBinding]


def _port(name: str, direction: TransportDirection) -> TransportPort:
    return TransportPort(
        name,
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        direction,
        clock_domain="chi_clk",
    )


def _link_profile(
    name: str,
    channels: frozenset[ChiChannelKind],
) -> ChiTransportLinkProfile:
    return ChiTransportLinkProfile(
        request=(
            ChiReqChannelProfile(
                ChiIssueHReqProfile(),
                (1,),
                f"{name}.req",
            )
            if ChiChannelKind.REQ in channels
            else None
        ),
        response=(
            ChiRspChannelProfile(
                ChiIssueHRspProfile(),
                1,
                f"{name}.rsp",
            )
            if ChiChannelKind.RSP in channels
            else None
        ),
        snoop=(
            ChiSnpChannelProfile(
                ChiIssueHSnpProfile(),
                1,
                f"{name}.snp",
            )
            if ChiChannelKind.SNP in channels
            else None
        ),
        data=(
            ChiDatChannelProfile(
                ChiIssueHDatProfile(data_width=512),
                1,
                f"{name}.dat",
            )
            if ChiChannelKind.DAT in channels
            else None
        ),
        clock="chi_clk",
        activation_observation=f"{name}.active",
    )


def _participant_duts() -> dict[str, VirtualDut]:
    return {
        "rn0": VirtualDut(
            "rn0",
            {
                "tx_req_rsp": _port(
                    "tx_req_rsp", TransportDirection.TRANSMIT
                ),
                "rx_dat": _port("rx_dat", TransportDirection.RECEIVE),
            },
            behavior_tags=frozenset((DutBehaviorTag.INITIATING,)),
            description="requesting coherent RN-F",
        ),
        "rn1": VirtualDut(
            "rn1",
            {
                "rx_snp": _port("rx_snp", TransportDirection.RECEIVE),
                "tx_rsp": _port("tx_rsp", TransportDirection.TRANSMIT),
            },
            description="clean snoopee RN-F",
        ),
        "rn2": VirtualDut(
            "rn2",
            {
                "rx_snp": _port("rx_snp", TransportDirection.RECEIVE),
                "tx_rsp": _port("tx_rsp", TransportDirection.TRANSMIT),
            },
            description="clean snoopee RN-F",
        ),
        "hn0": VirtualDut(
            "hn0",
            {
                "rx_req_rsp": _port(
                    "rx_req_rsp", TransportDirection.RECEIVE
                ),
                "tx_dat_snp": _port(
                    "tx_dat_snp", TransportDirection.TRANSMIT
                ),
            },
            behavior_tags=frozenset((DutBehaviorTag.ADDRESSABLE,)),
            description="clean coherent Home Node",
        ),
    }


def _xp_dut(
    name: str,
    directions: tuple[str, str],
) -> VirtualDut:
    peers = ("local", *directions)
    return VirtualDut(
        name,
        {
            **{
                f"rx_{peer}": _port(
                    f"rx_{peer}", TransportDirection.RECEIVE
                )
                for peer in peers
            },
            **{
                f"tx_{peer}": _port(
                    f"tx_{peer}", TransportDirection.TRANSMIT
                )
                for peer in peers
            },
        },
        behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
        description="finite exact-NodeID store-and-forward XP",
    )


def _xp_duts() -> dict[str, VirtualDut]:
    return {
        "xp00": _xp_dut("xp00", ("east", "south")),
        "xp10": _xp_dut("xp10", ("west", "south")),
        "xp11": _xp_dut("xp11", ("north", "west")),
        "xp01": _xp_dut("xp01", ("north", "east")),
    }


def _route(
    target_id: int,
    egress: str,
    channels: frozenset[ChiChannelKind],
) -> ChiExactNodeRoute:
    return ChiExactNodeRoute(target_id, egress, channels)


def _routers() -> dict[str, ChiStoreForwardRouterNode]:
    return {
        "xp00": ChiStoreForwardRouterNode(
            "xp00",
            ingress_ports=("rx_local", "rx_east", "rx_south"),
            egress_ports=("tx_local", "tx_east", "tx_south"),
            routes=(
                _route(HOME_NODE_ID, "tx_east", REQ_RSP),
                _route(FIRST_SNOOPEE_NODE_ID, "tx_east", SNP),
                _route(SECOND_SNOOPEE_NODE_ID, "tx_south", SNP),
                _route(REQUESTER_NODE_ID, "tx_local", DAT),
            ),
            queue_capacity=1,
        ),
        "xp10": ChiStoreForwardRouterNode(
            "xp10",
            ingress_ports=("rx_local", "rx_west", "rx_south"),
            egress_ports=("tx_local", "tx_west", "tx_south"),
            routes=(
                _route(HOME_NODE_ID, "tx_south", REQ_RSP),
                _route(FIRST_SNOOPEE_NODE_ID, "tx_local", SNP),
                _route(SECOND_SNOOPEE_NODE_ID, "tx_south", SNP),
                _route(REQUESTER_NODE_ID, "tx_west", DAT),
            ),
            queue_capacity=1,
        ),
        "xp11": ChiStoreForwardRouterNode(
            "xp11",
            ingress_ports=("rx_local", "rx_north", "rx_west"),
            egress_ports=("tx_local", "tx_north", "tx_west"),
            routes=(
                _route(HOME_NODE_ID, "tx_local", REQ_RSP),
                _route(FIRST_SNOOPEE_NODE_ID, "tx_north", SNP),
                _route(SECOND_SNOOPEE_NODE_ID, "tx_west", SNP),
                _route(REQUESTER_NODE_ID, "tx_west", DAT),
            ),
            queue_capacity=1,
        ),
        "xp01": ChiStoreForwardRouterNode(
            "xp01",
            ingress_ports=("rx_local", "rx_north", "rx_east"),
            egress_ports=("tx_local", "tx_north", "tx_east"),
            routes=(
                _route(HOME_NODE_ID, "tx_east", REQ_RSP),
                _route(FIRST_SNOOPEE_NODE_ID, "tx_north", SNP),
                _route(SECOND_SNOOPEE_NODE_ID, "tx_local", SNP),
                _route(REQUESTER_NODE_ID, "tx_north", DAT),
            ),
            queue_capacity=1,
        ),
    }


def _connection_specs():
    return (
        (
            "rn0_to_xp00",
            ("rn0", "tx_req_rsp"),
            ("xp00", "rx_local"),
            REQ_RSP,
        ),
        (
            "xp00_to_rn0",
            ("xp00", "tx_local"),
            ("rn0", "rx_dat"),
            DAT,
        ),
        (
            "rn1_to_xp10",
            ("rn1", "tx_rsp"),
            ("xp10", "rx_local"),
            RSP,
        ),
        (
            "xp10_to_rn1",
            ("xp10", "tx_local"),
            ("rn1", "rx_snp"),
            SNP,
        ),
        (
            "hn0_to_xp11",
            ("hn0", "tx_dat_snp"),
            ("xp11", "rx_local"),
            DAT_SNP,
        ),
        (
            "xp11_to_hn0",
            ("xp11", "tx_local"),
            ("hn0", "rx_req_rsp"),
            REQ_RSP,
        ),
        (
            "rn2_to_xp01",
            ("rn2", "tx_rsp"),
            ("xp01", "rx_local"),
            RSP,
        ),
        (
            "xp01_to_rn2",
            ("xp01", "tx_local"),
            ("rn2", "rx_snp"),
            SNP,
        ),
        (
            "xp00_to_xp10",
            ("xp00", "tx_east"),
            ("xp10", "rx_west"),
            ALL_CHANNELS,
        ),
        (
            "xp10_to_xp00",
            ("xp10", "tx_west"),
            ("xp00", "rx_east"),
            ALL_CHANNELS,
        ),
        (
            "xp10_to_xp11",
            ("xp10", "tx_south"),
            ("xp11", "rx_north"),
            ALL_CHANNELS,
        ),
        (
            "xp11_to_xp10",
            ("xp11", "tx_north"),
            ("xp10", "rx_south"),
            ALL_CHANNELS,
        ),
        (
            "xp11_to_xp01",
            ("xp11", "tx_west"),
            ("xp01", "rx_east"),
            ALL_CHANNELS,
        ),
        (
            "xp01_to_xp11",
            ("xp01", "tx_east"),
            ("xp11", "rx_west"),
            ALL_CHANNELS,
        ),
        (
            "xp01_to_xp00",
            ("xp01", "tx_north"),
            ("xp00", "rx_south"),
            ALL_CHANNELS,
        ),
        (
            "xp00_to_xp01",
            ("xp00", "tx_south"),
            ("xp01", "rx_north"),
            ALL_CHANNELS,
        ),
    )


def _router_binding(
    dut: VirtualDut,
    router: ChiStoreForwardRouterNode,
    local_rx: frozenset[ChiChannelKind],
    local_tx: frozenset[ChiChannelKind],
) -> ChiParticipantBinding:
    ports = []
    for name, port in dut.ports.items():
        channels = (
            local_rx
            if name == "rx_local"
            else local_tx
            if name == "tx_local"
            else ALL_CHANNELS
        )
        ports.append(ChiParticipantPortBinding(port, channels))
    return ChiParticipantBinding(
        dut.name,
        dut,
        router,
        tuple(ports),
    )


def build_clean_mesh() -> CleanMeshAssembly:
    """Build and close one clean ReadUnique feature over a 2×2 XP mesh."""

    duts = {**_participant_duts(), **_xp_duts()}
    builder = SystemProtocolBuilder("chi_issue_h_clean_2x2_mesh")
    for dut in duts.values():
        builder.add_dut(dut)
    for name, transmitter, receiver, channels in _connection_specs():
        builder.connect_transport(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef(*transmitter),
            VirtualDutPortRef(*receiver),
            profile=_link_profile(name, channels),
        )
    home_address_claim = "hn0.cache_line"
    builder.add_address_claim(
        AddressClaim(
            home_address_claim,
            VirtualDutPortRef("hn0", "rx_req_rsp"),
            AddressWindow(LINE_ADDRESS, 0x40),
        )
    )
    system = builder.build()
    elaborated = system.elaborate()
    resolved_duts = elaborated.spec.virtual_duts

    requester = bind_chi_issue_h_cache_lines(
        resolved_duts["rn0"],
        REQUESTER_NODE_ID,
        HOME_NODE_ID,
        port_channels={
            "tx_req_rsp": REQ_RSP,
            "rx_dat": DAT,
        },
        participant_name="rn0",
        binding_name="rn0",
    )
    first_snoopee = bind_chi_issue_h_cache_lines(
        resolved_duts["rn1"],
        FIRST_SNOOPEE_NODE_ID,
        HOME_NODE_ID,
        port_channels={
            "rx_snp": SNP,
            "tx_rsp": RSP,
        },
        initial_lines=(
            ChiCacheLine(
                LINE_ADDRESS,
                ChiCacheState.SC,
                LINE_DATA,
            ),
        ),
        participant_name="rn1",
        binding_name="rn1",
    )
    second_snoopee = bind_chi_issue_h_cache_lines(
        resolved_duts["rn2"],
        SECOND_SNOOPEE_NODE_ID,
        HOME_NODE_ID,
        port_channels={
            "rx_snp": SNP,
            "tx_rsp": RSP,
        },
        initial_lines=(
            ChiCacheLine(
                LINE_ADDRESS,
                ChiCacheState.SC,
                LINE_DATA,
            ),
        ),
        participant_name="rn2",
        binding_name="rn2",
    )
    home = bind_chi_issue_h_home_vdut(
        resolved_duts["hn0"],
        FullLineBackingCore(
            "hn0.backing",
            line_bytes=64,
            initial_lines=(BackingLine(LINE_ADDRESS, LINE_DATA),),
        ),
        HOME_NODE_ID,
        port_channels={
            "rx_req_rsp": REQ_RSP,
            "tx_dat_snp": DAT_SNP,
        },
        initial_directory=(
            ChiHomeDirectoryEntry(
                LINE_ADDRESS,
                sharers=frozenset(
                    (FIRST_SNOOPEE_NODE_ID, SECOND_SNOOPEE_NODE_ID)
                ),
            ),
        ),
        participant_name="hn0",
        binding_name="hn0",
        initial_snoop_transaction_id=0x100,
        initial_data_buffer_id=0x200,
    )

    bindings = {
        "rn0": requester.binding,
        "rn1": first_snoopee.binding,
        "rn2": second_snoopee.binding,
        "hn0": home.binding,
    }
    routers = _routers()
    for name, local_rx, local_tx in (
        ("xp00", REQ_RSP, DAT),
        ("xp10", RSP, SNP),
        ("xp11", DAT_SNP, REQ_RSP),
        ("xp01", RSP, SNP),
    ):
        bindings[name] = _router_binding(
            resolved_duts[name],
            routers[name],
            local_rx,
            local_tx,
        )

    feature_contract = ChiFeatureContract(
        {"requester": "rn0"},
        frozenset((CHI_FEATURE_CLEAN_READ_UNIQUE,)),
    )
    capabilities = (
        ChiParticipantCapability(
            "rn0",
            CHI_CLEAN_READ_UNIQUE_REQUESTER_CAPABILITIES,
        ),
        ChiParticipantCapability(
            "hn0",
            CHI_CLEAN_READ_UNIQUE_HOME_CAPABILITIES,
        ),
        ChiParticipantCapability(
            "rn1",
            CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
        ),
        ChiParticipantCapability(
            "rn2",
            CHI_CLEAN_READ_UNIQUE_SNOOPEE_CAPABILITIES,
        ),
    )
    resolved = resolve_chi_system(
        elaborated,
        facets=(
            *requester.facets.facets,
            *first_snoopee.facets.facets,
            *second_snoopee.facets.facets,
            *home.facets.facets,
            *(
                ChiBehaviorFacet.from_binding(
                    bindings[name],
                    ChiFacetKind.FORWARDING,
                )
                for name in ("xp00", "xp10", "xp11", "xp01")
            ),
        ),
        feature_contract=feature_contract,
        authority_contract=ChiCoherenceAuthorityContract(
            authorities=(
                ChiHomeAuthority(
                    home_address_claim,
                    "hn0",
                    "coherent_agents",
                ),
            ),
            domains=(
                ChiCoherenceDomain(
                    "coherent_agents",
                    frozenset(("rn0", "rn1", "rn2")),
                ),
            ),
        ),
        feature_address_claim=home_address_claim,
        participant_capabilities=capabilities,
        system_capabilities=frozenset(
            (CHI_SYSTEM_CLEAN_READ_UNIQUE_LIFECYCLE,)
        ),
        # The Home emits two Snoop packets at once.  A one-entry TX boundary
        # makes the retained egress batch and its backpressure visible.
        transmitter_capacity_by_connection={"hn0_to_xp11": 1},
    )
    session = ChiCoherenceNetworkSession.from_resolved(resolved)
    request = ChiReadUniqueMessage(
        transaction_id=0x12,
        address=LINE_ADDRESS,
    )
    return CleanMeshAssembly(
        system,
        elaborated,
        resolved,
        session,
        request,
        bindings,
    )


def _line_state(coherence_state, node_id: int) -> str:
    line = coherence_state.request_nodes[node_id].lines.get(LINE_ADDRESS)
    return ChiCacheState.I.value if line is None else line.state.value


def _coherence_snapshot(coherence_state) -> dict[str, object]:
    directory = coherence_state.home.directory[LINE_ADDRESS]
    return {
        "rn0": _line_state(coherence_state, REQUESTER_NODE_ID),
        "rn1": _line_state(coherence_state, FIRST_SNOOPEE_NODE_ID),
        "rn2": _line_state(coherence_state, SECOND_SNOOPEE_NODE_ID),
        "home": {
            "sharers": sorted(directory.sharers),
            "unique_owner": directory.unique_owner,
            "data": coherence_state.home.backing.line_at(
                LINE_ADDRESS
            ).data,
        },
    }


def _event_record(
    index: int,
    event: ChiCoherenceNetworkEvent,
) -> dict[str, object]:
    packet = event.packet
    detail = event.detail
    message = None if packet is None else packet.message
    return {
        "index": index,
        "kind": event.kind.value,
        "participant": event.participant,
        "connection": event.connection,
        "network_kind": None if detail is None else detail.kind.value,
        "router": "" if detail is None else detail.node,
        "channel": None if packet is None else packet.channel.value,
        "message": None if message is None else type(message).__name__,
        "source_id": None if packet is None else packet.source_id,
        "target_id": None if packet is None else packet.target_id,
        "transaction_id": (
            None if message is None else message.transaction_id
        ),
        "produced": tuple(
            type(item.message).__name__ for item in event.produced
        ),
        "lineage": tuple(event.lineage),
    }


def _packet_record(
    packet: ChiNetworkPacket,
    route: tuple[str, ...],
) -> dict[str, object]:
    return {
        "message": type(packet.message).__name__,
        "channel": packet.channel.value,
        "source_id": packet.source_id,
        "target_id": packet.target_id,
        "transaction_id": packet.message.transaction_id,
        "route": route,
    }


def execute_clean_mesh(
    assembly: CleanMeshAssembly | None = None,
) -> tuple[CleanMeshAssembly, dict[str, object]]:
    """Execute one clean ReadUnique and return JSON-safe evidence."""

    assembly = assembly or build_clean_mesh()
    session = assembly.session
    initial = session.initial_state()
    before = _coherence_snapshot(initial.coherence)
    issued = session.step(
        initial,
        ChiSubmitCoherentRead(REQUESTER_NODE_ID, assembly.request),
    )
    if issued.fault is not None:
        raise RuntimeError(f"ReadUnique issue faulted: {issued.fault.reason}")
    if issued.blocked is not None:
        raise RuntimeError(f"ReadUnique issue blocked: {issued.blocked.reason}")
    run = session.run_until_quiescent(issued.state, max_steps=2048)
    if run.verdict is not Verdict.PASS:
        reason = "unknown" if run.blocked is None else run.blocked.reason
        raise RuntimeError(
            f"clean mesh execution ended as {run.verdict.value}: {reason}"
        )

    events = (*issued.emissions, *run.emissions)
    packets_by_identity: dict[int, ChiNetworkPacket] = {}
    for event in events:
        for packet in event.produced:
            packets_by_identity[id(packet)] = packet
    packets = tuple(packets_by_identity.values())
    message_counts = Counter(type(packet.message).__name__ for packet in packets)
    if len(packets) != 7:
        raise RuntimeError(
            f"clean ReadUnique produced {len(packets)} packets, expected 7"
        )

    packet_records = []
    for packet in packets:
        route = session.route_by_packet_key[
            (packet.source_id, packet.target_id, packet.channel)
        ]
        packet_records.append(_packet_record(packet, route))
    packet_records.sort(
        key=lambda item: (
            item["channel"],
            item["source_id"],
            item["target_id"],
            item["transaction_id"],
        )
    )
    used_connections = sorted(
        {
            connection
            for packet in packet_records
            for connection in packet["route"]
        }
    )
    used_physical_edges = sorted(
        "-".join(sorted((left, right)))
        for left, right in PHYSICAL_RING_EDGES
        if (
            f"{left}_to_{right}" in used_connections
            or f"{right}_to_{left}" in used_connections
        )
    )
    if len(used_physical_edges) != 4:
        raise RuntimeError("the clean witness did not exercise all ring edges")

    final = run.final_state
    after = _coherence_snapshot(final.coherence)
    router_stats = {
        name: {
            "accepted": state.accepted_count,
            "forwarded": state.forwarded_count,
            "depth": state.depth,
        }
        for name, state in final.network.routers.items()
    }
    maximum_pending_egress = max(
        len(state.pending_egress)
        for state in (issued.state, *run.state_history)
    )
    assertions = {
        "quiescent": session.is_quiescent(final),
        "packet_count_is_7": len(packets) == 7,
        "fanout_retained": maximum_pending_egress >= 2,
        "all_four_physical_edges_used": len(used_physical_edges) == 4,
        "requester_is_unique_clean": after["rn0"] == "UC",
        "former_sharers_invalid": (
            after["rn1"] == "I" and after["rn2"] == "I"
        ),
        "home_names_requester_as_unique_owner": (
            after["home"]["unique_owner"] == REQUESTER_NODE_ID
            and not after["home"]["sharers"]
        ),
    }
    if not all(assertions.values()):
        raise RuntimeError(f"clean mesh assertions failed: {assertions!r}")

    connection_names = tuple(assembly.system.connections)
    result = {
        "schema": "protocol-model.showcase.chi-clean-2x2-mesh/v1",
        "verdict": run.verdict.value,
        "profile": {
            "issue": "H",
            "data_width": 512,
            "router_queue_capacity": 1,
            "link_credit_capacity": 1,
            "home_egress_capacity": 1,
            "coherence_states": ("I", "SC", "UC"),
        },
        "request": {
            "message": type(assembly.request).__name__,
            "transaction_id": assembly.request.transaction_id,
            "address": assembly.request.address,
        },
        "topology": {
            "xps": ("xp00", "xp10", "xp11", "xp01"),
            "participants": ("rn0", "rn1", "hn0", "rn2"),
            "physical_ring_edges": PHYSICAL_RING_EDGES,
            "directed_connections": connection_names,
            "used_connections": used_connections,
            "unused_connections": sorted(
                set(connection_names) - set(used_connections)
            ),
            "used_physical_edges": used_physical_edges,
        },
        "packets": packet_records,
        "message_counts": dict(sorted(message_counts.items())),
        "coherence": {
            "before": before,
            "after": after,
        },
        "runtime": {
            "committed_microsteps": final.committed_microsteps,
            "maximum_pending_egress": maximum_pending_egress,
            "router_stats": router_stats,
            "event_count": len(events),
        },
        "events": tuple(
            _event_record(index, event)
            for index, event in enumerate(events)
        ),
        "assertions": assertions,
        "scope": {
            "raw_pin_waveform": False,
            "dirty_data": False,
            "retry": False,
            "routing_policy": "exact target NodeID plus channel",
            "cache_states": ("I", "SC", "UC"),
        },
    }
    return assembly, result


__all__ = [
    "CleanMeshAssembly",
    "FIRST_SNOOPEE_NODE_ID",
    "HOME_NODE_ID",
    "LINE_ADDRESS",
    "LINE_DATA",
    "PHYSICAL_RING_EDGES",
    "REQUESTER_NODE_ID",
    "SECOND_SNOOPEE_NODE_ID",
    "build_clean_mesh",
    "execute_clean_mesh",
]
