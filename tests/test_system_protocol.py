from __future__ import annotations

import unittest

from protocol_model import (
    BitVectorDomain,
    CanonicalEvent,
    CardinalityMonitor,
    CaptureModel,
    CaptureState,
    ChannelProtocol,
    ConstraintScope,
    DutFacet,
    EventField,
    EventSchema,
    FunctionModel,
    LinkProtocol,
    ProtocolLink,
    SemanticConstraint,
    SemanticFragment,
    SystemProtocol,
    SystemAction,
    VirtualDut,
    PortEmission,
    ProtocolPort,
    VirtualDutPortRef,
)
from protocol_model.visualization import system_topology_dot


def ready_valid_protocol() -> LinkProtocol:
    transfer = EventSchema("transfer")
    channel = ChannelProtocol("data", "source", "sink", transfer)
    rule = SemanticConstraint(
        "stable_while_stalled",
        "payload remains stable while valid is held without acceptance",
        ConstraintScope.LINK,
        targets=("data",),
    )
    return LinkProtocol.define(
        "ready_valid",
        roles=frozenset(("source", "sink")),
        channels={"data": channel},
        fragments=(SemanticFragment("handshake", constraints=(rule,)),),
    )


def connected_system() -> SystemProtocol:
    protocol = ready_valid_protocol()
    source = VirtualDut(
        "producer",
        {"out": ProtocolPort("out", protocol, "source")},
        frozenset((DutFacet.INITIATING,)),
    )
    sink = VirtualDut(
        "consumer",
        {"in": ProtocolPort("in", protocol, "sink")},
    )
    link = ProtocolLink(
        "data_path",
        protocol,
        {
            "source": VirtualDutPortRef("producer", "out"),
            "sink": VirtualDutPortRef("consumer", "in"),
        },
    )
    return SystemProtocol(
        "producer_to_consumer",
        {source.name: source, sink.name: sink},
        {link.name: link},
    )


def request_response_protocol(name: str, prefix: str) -> LinkProtocol:
    request = EventSchema(
        f"{prefix}_REQUEST",
        {"data": EventField("data", BitVectorDomain(8))},
        BitVectorDomain(4),
    )
    response = EventSchema(
        f"{prefix}_RESPONSE",
        {"data": EventField("data", BitVectorDomain(8))},
        BitVectorDomain(4),
    )
    channels = {
        "request": ChannelProtocol("request", "initiator", "target", request),
        "response": ChannelProtocol("response", "target", "initiator", response),
    }
    return LinkProtocol.define(
        name,
        roles=frozenset(("initiator", "target")),
        channels=channels,
        fragments=(SemanticFragment.empty(f"{name}.base"),),
        monitors={
            f"{name}.request_response": CardinalityMonitor(
                f"{name}.request_response",
                f"{prefix}_REQUEST",
                f"{prefix}_RESPONSE",
                count_of=lambda _event: 1,
            )
        },
    )


class SystemProtocolTest(unittest.TestCase):
    def test_system_topology_visualization_is_protocol_independent(self) -> None:
        dot = system_topology_dot(connected_system())

        self.assertIn("producer_to_consumer", dot)
        self.assertIn("VirtualDut", dot)
        self.assertIn("data_path", dot)
        self.assertIn("source · out", dot)
        self.assertIn("sink · in", dot)

    def test_link_profile_refinement_only_adds_semantics(self) -> None:
        protocol = ready_valid_protocol()
        extra = SemanticFragment(
            "bounded_stall",
            constraints=(
                SemanticConstraint(
                    "eventual_accept",
                    "a continuously offered transfer is eventually accepted",
                    ConstraintScope.LINK,
                ),
            ),
        )

        profile = protocol.refine("ready_valid_bounded", extra)

        self.assertEqual(("ready_valid",), profile.lineage)
        self.assertEqual(
            ("stable_while_stalled", "eventual_accept"),
            tuple(item.name for item in profile.semantics.constraints),
        )

    def test_elaboration_owns_ports_and_lifts_link_semantics(self) -> None:
        elaborated = connected_system().elaborate()

        self.assertEqual(2, len(elaborated.owner_by_port))
        self.assertEqual(
            ("link.data_path.stable_while_stalled",),
            tuple(item.name for item in elaborated.semantics.constraints),
        )

    def test_unconnected_port_is_rejected(self) -> None:
        system = connected_system()
        protocol = next(iter(system.links.values())).protocol
        dangling = VirtualDut(
            "dangling",
            {"in": ProtocolPort("in", protocol, "sink")},
        )
        invalid = SystemProtocol(
            system.name,
            {**system.virtual_duts, dangling.name: dangling},
            system.links,
        )

        with self.assertRaisesRegex(ValueError, "unconnected VirtualDut ports"):
            invalid.elaborate()

    def test_system_can_be_encapsulated_as_a_virtual_dut(self) -> None:
        protocol = ready_valid_protocol()
        endpoint = VirtualDut(
            "endpoint",
            {"external": ProtocolPort("external", protocol, "source")},
        )
        subsystem = SystemProtocol(
            "subsystem",
            {endpoint.name: endpoint},
            {},
            {"out": VirtualDutPortRef("endpoint", "external")},
        )

        wrapper = subsystem.as_virtual_dut("chiplet")

        self.assertIn(DutFacet.COMPOSITE, wrapper.facets)
        self.assertEqual("source", wrapper.port("out").role)
        self.assertIs(subsystem, wrapper.subsystem)

    def test_one_link_is_a_complete_executable_system_protocol(self) -> None:
        protocol = request_response_protocol("local_bus", "LOCAL")
        client_model = CaptureModel()
        server_model = FunctionModel(
            lambda action: (
                PortEmission(
                    "bus",
                    CanonicalEvent(
                        "LOCAL_RESPONSE",
                        action.event.key,
                        {"data": int(action.event.payload["data"]) + 1},
                    ),
                ),
            )
        )
        client = VirtualDut(
            "client",
            {"bus": ProtocolPort("bus", protocol, "initiator")},
            model=client_model,
        )
        server = VirtualDut(
            "server",
            {"bus": ProtocolPort("bus", protocol, "target")},
            model=server_model,
        )
        system = SystemProtocol.from_link(
            "point_to_point",
            link_name="bus",
            protocol=protocol,
            endpoints={
                "initiator": (client, "bus"),
                "target": (server, "bus"),
            },
        )

        session = system.open_session()
        transition = session.step(
            session.initial_state(),
            SystemAction(
                VirtualDutPortRef("client", "bus"),
                CanonicalEvent("LOCAL_REQUEST", 3, {"data": 7}),
            ),
        )

        self.assertIsNone(transition.fault)
        self.assertEqual(
            ("LOCAL_REQUEST", "LOCAL_RESPONSE"),
            tuple(item.event.kind for item in transition.emissions),
        )
        self.assertEqual(((0, 1),), transition.state.causal_edges)
        client_state = transition.state.dut_states["client"]
        self.assertIsInstance(client_state, CaptureState)
        self.assertEqual(8, client_state.received[0].event.payload["data"])

    def test_bridge_system_routes_until_the_emission_queue_is_empty(self) -> None:
        upstream = request_response_protocol("upstream_bus", "UP")
        downstream = request_response_protocol("downstream_bus", "DOWN")
        client = VirtualDut(
            "point_a",
            {"bus": ProtocolPort("bus", upstream, "initiator")},
            model=CaptureModel(),
        )

        def bridge_function(action):
            if action.port == "upstream" and action.event.kind == "UP_REQUEST":
                return (
                    PortEmission(
                        "downstream",
                        CanonicalEvent(
                            "DOWN_REQUEST",
                            action.event.key,
                            {"data": int(action.event.payload["data"]) + 10},
                        ),
                    ),
                )
            if action.port == "downstream" and action.event.kind == "DOWN_RESPONSE":
                return (
                    PortEmission(
                        "upstream",
                        CanonicalEvent(
                            "UP_RESPONSE",
                            action.event.key,
                            {"data": int(action.event.payload["data"]) + 20},
                        ),
                    ),
                )
            raise ValueError(f"unexpected bridge input {action}")

        bridge = VirtualDut(
            "bridge",
            {
                "upstream": ProtocolPort("upstream", upstream, "target"),
                "downstream": ProtocolPort(
                    "downstream", downstream, "initiator"
                ),
            },
            frozenset((DutFacet.TRANSFORMING,)),
            model=FunctionModel(bridge_function),
        )
        server = VirtualDut(
            "point_b",
            {"bus": ProtocolPort("bus", downstream, "target")},
            model=FunctionModel(
                lambda action: (
                    PortEmission(
                        "bus",
                        CanonicalEvent(
                            "DOWN_RESPONSE",
                            action.event.key,
                            {"data": int(action.event.payload["data"]) + 1},
                        ),
                    ),
                )
            ),
        )
        link_a = ProtocolLink(
            "link_a",
            upstream,
            {
                "initiator": VirtualDutPortRef("point_a", "bus"),
                "target": VirtualDutPortRef("bridge", "upstream"),
            },
        )
        link_b = ProtocolLink(
            "link_b",
            downstream,
            {
                "initiator": VirtualDutPortRef("bridge", "downstream"),
                "target": VirtualDutPortRef("point_b", "bus"),
            },
        )
        system = SystemProtocol(
            "a_bridge_b",
            {item.name: item for item in (client, bridge, server)},
            {item.name: item for item in (link_a, link_b)},
        )

        session = system.open_session()
        transition = session.step(
            session.initial_state(),
            SystemAction(
                VirtualDutPortRef("point_a", "bus"),
                CanonicalEvent("UP_REQUEST", 2, {"data": 3}),
            ),
        )

        self.assertIsNone(transition.fault)
        self.assertEqual(
            ("UP_REQUEST", "DOWN_REQUEST", "DOWN_RESPONSE", "UP_RESPONSE"),
            tuple(item.event.kind for item in transition.emissions),
        )
        self.assertEqual(
            ("link_a", "link_b", "link_b", "link_a"),
            tuple(item.link for item in transition.emissions),
        )
        self.assertEqual(
            frozenset(((0, 1), (1, 2), (2, 3), (0, 3))),
            frozenset(transition.state.causal_edges),
        )
        point_a_state = transition.state.dut_states["point_a"]
        self.assertEqual(34, point_a_state.received[0].event.payload["data"])

    def test_link_monitor_rejects_an_orphan_response(self) -> None:
        protocol = request_response_protocol("orphan_bus", "ORPHAN")
        session = protocol.open_session()

        transition = session.step(
            session.initial_state(),
            CanonicalEvent("ORPHAN_RESPONSE", 1, {"data": 0}),
        )

        self.assertIsNotNone(transition.fault)
        self.assertTrue(transition.fault.rule.endswith("orphan_beat"))


if __name__ == "__main__":
    unittest.main()
