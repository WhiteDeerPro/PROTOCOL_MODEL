"""Executable system assembly for a restricted CHI Issue H routed read.

This module intentionally contains only scenario composition.  CHI transport,
router, participant, and transaction behavior continue to come from
``protocol_model``.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.protocols.amba.chi.issue_h.interface import (
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpDirectProfile,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiAddressHomeNode,
    ChiExactNodeRoute,
    ChiParticipantBinding,
    ChiParticipantPortBinding,
    ChiStoreForwardRouterNode,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiReadNoSnpMessage,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    ChiNetworkEventKind,
    ChiReadNoSnpSystemEvent,
    ChiReadNoSnpSystemEventKind,
    ChiReadNoSnpSystemSession,
    ChiSubmitRead,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
    ChiDatChannelProfile,
    ChiReqChannelProfile,
    ChiTransportLinkProfile,
)
from protocol_model.semantics import Verdict
from protocol_model.system import (
    ElaboratedSystemProtocol,
    SystemProtocol,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    TransportDirection,
    TransportPort,
    VirtualDut,
)
from protocol_model.virtual_dut.address import AddressSpace, MemoryRegion


REQUESTER_NODE_ID = 0x07
HOME_NODE_ID = 0x21
SENSOR_SAMPLE_ADDRESS = 0x4020
SENSOR_SAMPLE_VALUE = 0x5300_4020


@dataclass(frozen=True)
class RoutedReadAssembly:
    """Objects needed to execute and project the demonstration."""

    system: SystemProtocol
    elaborated: ElaboratedSystemProtocol
    session: ChiReadNoSnpSystemSession
    requester: ChiParticipantBinding
    home: ChiParticipantBinding
    routers: tuple[ChiParticipantBinding, ...]
    request: ChiReadNoSnpMessage
    profile: ChiReadNoSnpDirectProfile


def _transport_port(
    name: str,
    direction: TransportDirection,
) -> TransportPort:
    return TransportPort(
        name,
        CHI_ISSUE_H_TRANSPORT_FAMILY,
        direction,
        clock_domain="chi_clk",
    )


def _req_profile(name: str) -> ChiTransportLinkProfile:
    return ChiTransportLinkProfile(
        request=ChiReqChannelProfile(
            representation=ChiIssueHReqProfile(),
            credit_capacities=(1,),
            observation=f"{name}.req",
        ),
        data=None,
        clock="chi_clk",
        activation_observation=f"{name}.active",
    )


def _dat_profile(name: str) -> ChiTransportLinkProfile:
    return ChiTransportLinkProfile(
        request=None,
        data=ChiDatChannelProfile(
            representation=ChiIssueHDatProfile(data_width=128),
            credit_capacity=1,
            observation=f"{name}.dat",
        ),
        clock="chi_clk",
        activation_observation=f"{name}.active",
    )


def _router(name: str) -> ChiStoreForwardRouterNode:
    return ChiStoreForwardRouterNode(
        name,
        ingress_ports=("req_w", "dat_e"),
        egress_ports=("req_e", "dat_w"),
        routes=(
            ChiExactNodeRoute(
                HOME_NODE_ID,
                "req_e",
                frozenset((ChiChannelKind.REQ,)),
            ),
            ChiExactNodeRoute(
                REQUESTER_NODE_ID,
                "dat_w",
                frozenset((ChiChannelKind.DAT,)),
            ),
        ),
        queue_capacity=1,
    )


def _router_dut(name: str) -> VirtualDut:
    return VirtualDut(
        name,
        {
            "req_w": _transport_port(
                "req_w", TransportDirection.RECEIVE
            ),
            "req_e": _transport_port(
                "req_e", TransportDirection.TRANSMIT
            ),
            "dat_e": _transport_port(
                "dat_e", TransportDirection.RECEIVE
            ),
            "dat_w": _transport_port(
                "dat_w", TransportDirection.TRANSMIT
            ),
        },
        behavior_tags=frozenset((DutBehaviorTag.ROUTING,)),
        description="finite CHI store-and-forward XP reference node",
    )


def _participant_port(
    dut: VirtualDut,
    name: str,
    channel: ChiChannelKind,
) -> ChiParticipantPortBinding:
    port = dut.port(name)
    assert isinstance(port, TransportPort)
    return ChiParticipantPortBinding(port, frozenset((channel,)))


def _router_binding(
    dut: VirtualDut,
    component: ChiStoreForwardRouterNode,
) -> ChiParticipantBinding:
    return ChiParticipantBinding(
        f"{dut.name}.fabric",
        dut,
        component,
        (
            _participant_port(dut, "req_w", ChiChannelKind.REQ),
            _participant_port(dut, "req_e", ChiChannelKind.REQ),
            _participant_port(dut, "dat_e", ChiChannelKind.DAT),
            _participant_port(dut, "dat_w", ChiChannelKind.DAT),
        ),
    )


def build_routed_read() -> RoutedReadAssembly:
    """Build RN-I -> XP0 -> XP1 -> I/O Home and its reverse DAT path."""

    profile = ChiReadNoSnpDirectProfile(
        requester_node_id=REQUESTER_NODE_ID,
        home_node_id=HOME_NODE_ID,
        data_width=128,
        outstanding_capacity=2,
    )
    requester_component = ChiReadNoSnpDirectLedger(
        "sensor_reader.reads", profile
    )
    sensor_register = AddressSpace(
        (
            MemoryRegion(
                "sensor_sample",
                profile.data_bytes,
                base_address=SENSOR_SAMPLE_ADDRESS,
                read_only=True,
                initial_content=SENSOR_SAMPLE_VALUE.to_bytes(
                    profile.data_bytes, "little"
                ),
            ),
        )
    )
    home_component = ChiAddressHomeNode(
        "sensor_io_home",
        profile,
        sensor_register,
        request_capacity=1,
    )
    router_components = (_router("xp0"), _router("xp1"))

    requester_dut = VirtualDut(
        "sensor_reader_rn",
        {
            "tx_req": _transport_port(
                "tx_req", TransportDirection.TRANSMIT
            ),
            "rx_dat": _transport_port(
                "rx_dat", TransportDirection.RECEIVE
            ),
        },
        behavior_tags=frozenset((DutBehaviorTag.INITIATING,)),
        description="RN-I reference requester",
    )
    router_duts = (_router_dut("xp0"), _router_dut("xp1"))
    home_dut = VirtualDut(
        "sensor_io_home",
        {
            "rx_req": _transport_port(
                "rx_req", TransportDirection.RECEIVE
            ),
            "tx_dat": _transport_port(
                "tx_dat", TransportDirection.TRANSMIT
            ),
        },
        behavior_tags=frozenset((DutBehaviorTag.ADDRESSABLE,)),
        description=(
            "direct Home participant backed by a read-only AddressSpace"
        ),
    )

    builder = SystemProtocolBuilder("chi_issue_h_two_xp_sensor_read")
    for dut in (requester_dut, *router_duts, home_dut):
        builder.add_dut(dut)
    for name, transmitter, receiver, link_profile in (
        (
            "req_0_rn_to_xp0",
            ("sensor_reader_rn", "tx_req"),
            ("xp0", "req_w"),
            _req_profile("req_0_rn_to_xp0"),
        ),
        (
            "req_1_xp0_to_xp1",
            ("xp0", "req_e"),
            ("xp1", "req_w"),
            _req_profile("req_1_xp0_to_xp1"),
        ),
        (
            "req_2_xp1_to_home",
            ("xp1", "req_e"),
            ("sensor_io_home", "rx_req"),
            _req_profile("req_2_xp1_to_home"),
        ),
        (
            "dat_0_home_to_xp1",
            ("sensor_io_home", "tx_dat"),
            ("xp1", "dat_e"),
            _dat_profile("dat_0_home_to_xp1"),
        ),
        (
            "dat_1_xp1_to_xp0",
            ("xp1", "dat_w"),
            ("xp0", "dat_e"),
            _dat_profile("dat_1_xp1_to_xp0"),
        ),
        (
            "dat_2_xp0_to_rn",
            ("xp0", "dat_w"),
            ("sensor_reader_rn", "rx_dat"),
            _dat_profile("dat_2_xp0_to_rn"),
        ),
    ):
        builder.connect_transport(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            VirtualDutPortRef(*transmitter),
            VirtualDutPortRef(*receiver),
            profile=link_profile,
        )
    system = builder.build()
    elaborated = system.elaborate()

    requester = ChiParticipantBinding(
        requester_component.name,
        requester_dut,
        requester_component,
        (
            _participant_port(
                requester_dut, "tx_req", ChiChannelKind.REQ
            ),
            _participant_port(
                requester_dut, "rx_dat", ChiChannelKind.DAT
            ),
        ),
        frozenset((REQUESTER_NODE_ID,)),
    )
    home = ChiParticipantBinding(
        home_component.name,
        home_dut,
        home_component,
        (
            _participant_port(home_dut, "rx_req", ChiChannelKind.REQ),
            _participant_port(home_dut, "tx_dat", ChiChannelKind.DAT),
        ),
        frozenset((HOME_NODE_ID,)),
    )
    routers = tuple(
        _router_binding(dut, component)
        for dut, component in zip(
            router_duts, router_components, strict=True
        )
    )
    session = ChiReadNoSnpSystemSession(
        elaborated,
        requester=requester,
        home=home,
        routers=routers,
    )
    request = ChiReadNoSnpMessage(
        transaction_id=3,
        address=SENSOR_SAMPLE_ADDRESS,
        size=4,
        order=0,
        allow_retry=True,
        protocol_credit_type=0,
        expect_completion_ack=False,
        memory_attributes=0,
    )
    return RoutedReadAssembly(
        system,
        elaborated,
        session,
        requester,
        home,
        routers,
        request,
        profile,
    )


def _event_record(
    index: int,
    event: ChiReadNoSnpSystemEvent,
) -> dict[str, object]:
    detail = event.detail
    packet = event.packet or (None if detail is None else detail.packet)
    message = None if packet is None else packet.message
    return {
        "index": index,
        "kind": event.kind.value,
        "participant": event.participant,
        "connection": event.connection,
        "network_kind": None if detail is None else detail.kind.value,
        "node": "" if detail is None else detail.node,
        "channel": None if packet is None else packet.channel.value,
        "source_id": None if packet is None else packet.source_id,
        "target_id": None if packet is None else packet.target_id,
        "transaction_id": (
            None if message is None else message.transaction_id
        ),
        "lineage": tuple(event.lineage),
    }


def execute_routed_read(
    assembly: RoutedReadAssembly | None = None,
) -> tuple[RoutedReadAssembly, dict[str, object]]:
    """Execute one read and return presentation-neutral evidence."""

    assembly = assembly or build_routed_read()
    session = assembly.session
    issued = session.step(
        session.initial_state(),
        ChiSubmitRead(assembly.requester.name, assembly.request),
    )
    if issued.fault is not None:
        raise RuntimeError(f"read submission faulted: {issued.fault.reason}")
    if issued.blocked is not None:
        raise RuntimeError(f"read submission blocked: {issued.blocked.reason}")
    run = session.run_until_quiescent(issued.state, max_steps=512)
    if run.verdict is not Verdict.PASS:
        reason = (
            "unknown"
            if run.blocked is None
            else run.blocked.reason
        )
        raise RuntimeError(
            f"routed read ended as {run.verdict.value}: {reason}"
        )

    events = (*issued.emissions, *run.emissions)
    completed = run.final_state.requester.completed
    if len(completed) != 1:
        raise RuntimeError("routed read did not produce exactly one result")
    response = completed[0].response
    complete_events = tuple(
        event
        for event in events
        if event.kind is ChiReadNoSnpSystemEventKind.COMPLETE
    )
    if len(complete_events) != 1:
        raise RuntimeError("routed read did not emit exactly one completion")
    complete_lineage = tuple(complete_events[0].lineage)
    request_route = tuple(session.request_route_connections)
    data_route = tuple(session.data_route_connections)
    required_hops = (*request_route, *data_route)
    network_kinds = tuple(
        event.detail.kind
        for event in events
        if event.detail is not None
    )
    assertions = {
        "verdict_is_pass": run.verdict is Verdict.PASS,
        "one_completion": len(completed) == 1,
        "sensor_value_matches": response.data == SENSOR_SAMPLE_VALUE,
        "request_crosses_two_xps": len(request_route) == 3,
        "data_crosses_two_xps": len(data_route) == 3,
        "router_accept_count": (
            network_kinds.count(ChiNetworkEventKind.ROUTER_ACCEPT) == 4
        ),
        "router_forward_count": (
            network_kinds.count(ChiNetworkEventKind.ROUTER_FORWARD) == 4
        ),
        "lineage_covers_every_hop": all(
            any(label.startswith(f"{name}@") for label in complete_lineage)
            for name in required_hops
        ),
        "session_is_quiescent": session.is_quiescent(run.final_state),
    }
    if not all(assertions.values()):
        failed = ", ".join(
            name for name, passed in assertions.items() if not passed
        )
        raise RuntimeError(f"routed-read assertions failed: {failed}")

    result: dict[str, object] = {
        "schema": "protocol-model.showcase.chi-routed-read/v1",
        "scope": "restricted_two_xp_read_no_snp_witness",
        "topology": {
            "nodes": tuple(assembly.system.virtual_duts),
            "connections": tuple(assembly.system.connections),
            "request_route": request_route,
            "data_route": data_route,
        },
        "profile": {
            "issue": "H",
            "requester_node_id": assembly.profile.requester_node_id,
            "home_node_id": assembly.profile.home_node_id,
            "data_width": assembly.profile.data_width,
            "outstanding_capacity": assembly.profile.outstanding_capacity,
            "home_request_capacity": 1,
            "router_queue_capacity": 1,
            "link_credit_capacity": 1,
        },
        "peripheral_reference": {
            "name": "read-only sensor sample register",
            "address": SENSOR_SAMPLE_ADDRESS,
            "value": SENSOR_SAMPLE_VALUE,
            "implementation": (
                "ChiAddressHomeNode -> AddressTarget -> "
                "AddressSpace/MemoryRegion"
            ),
        },
        "request": assembly.request,
        "response": response,
        "lineage": complete_lineage,
        "events": tuple(
            _event_record(index, event)
            for index, event in enumerate(events)
        ),
        "result": {
            "verdict": run.verdict.value,
            "data": response.data,
            "data_id": response.data_id,
            "completed_count": len(completed),
            "committed_microsteps": run.final_state.committed_microsteps,
        },
        "assertions": assertions,
    }
    return assembly, result


__all__ = [
    "HOME_NODE_ID",
    "REQUESTER_NODE_ID",
    "RoutedReadAssembly",
    "SENSOR_SAMPLE_ADDRESS",
    "SENSOR_SAMPLE_VALUE",
    "build_routed_read",
    "execute_routed_read",
]
