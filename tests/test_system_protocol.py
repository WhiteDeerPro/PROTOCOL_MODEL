from __future__ import annotations

import unittest

from protocol_model.interface import InterfaceEventKind, InterfaceProtocol
from protocol_model.patterns import CardinalityMonitor
from protocol_model.semantics import (
    BitVectorDomain,
    CanonicalEvent,
    ConstraintScope,
    EventField,
    EventSchema,
    SemanticConstraint,
    SemanticFragment,
)
from protocol_model.system import (
    InterfaceConnection,
    SystemAction,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.backend import (
    CaptureBackend,
    CaptureState,
    FunctionBackend,
    PortEmission,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    InterfacePort,
    VirtualDut,
)
from protocol_model.visualization import system_topology_dot
from protocol_model.visualization.policy import DiagramDetail


def ready_valid_protocol() -> InterfaceProtocol:
    transfer = EventSchema("transfer")
    channel = InterfaceEventKind("data", "source", "sink", transfer)
    rule = SemanticConstraint(
        "stable_while_stalled",
        "payload remains stable while valid is held without acceptance",
        ConstraintScope.INTERFACE,
        targets=("data",),
    )
    return InterfaceProtocol.define(
        "ready_valid",
        roles=frozenset(("source", "sink")),
        event_kinds={"data": channel},
        fragments=(SemanticFragment("handshake", constraints=(rule,)),),
    )


def connected_system() -> SystemProtocol:
    protocol = ready_valid_protocol()
    source = VirtualDut(
        "producer",
        {"out": InterfacePort("out", protocol, "source")},
        frozenset((DutBehaviorTag.INITIATING,)),
    )
    sink = VirtualDut(
        "consumer",
        {"in": InterfacePort("in", protocol, "sink")},
    )
    link = InterfaceConnection(
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


def request_response_protocol(name: str, prefix: str) -> InterfaceProtocol:
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
        "request": InterfaceEventKind("request", "initiator", "target", request),
        "response": InterfaceEventKind("response", "target", "initiator", response),
    }
    return InterfaceProtocol.define(
        name,
        roles=frozenset(("initiator", "target")),
        event_kinds=channels,
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
        system = connected_system()
        dot = system_topology_dot(system)

        self.assertIn("producer_to_consumer", dot)
        self.assertIn("VirtualDut", dot)
        self.assertIn('label="ready_valid\\nout ↔ in"', dot)
        self.assertNotIn("data_path", dot)
        self.assertNotIn("source · out", dot)
        self.assertNotIn("declaration", dot)
        self.assertNotIn("shape=diamond", dot)

        overview = system_topology_dot(
            system,
            detail=DiagramDetail.OVERVIEW,
        )
        self.assertIn('label="producer"', overview)
        self.assertIn('label="ready_valid"', overview)
        self.assertNotIn("VirtualDut", overview)
        self.assertNotIn("out ↔ in", overview)
        self.assertEqual(dot.count(" -> "), overview.count(" -> "))

        diagnostic = system_topology_dot(
            system,
            detail=DiagramDetail.DIAGNOSTIC,
        )
        self.assertIn(
            'label="ready_valid\\ndata_path\\nsource · out ↔ sink · in"',
            diagnostic,
        )
        self.assertIn("declaration", diagnostic)
        self.assertEqual(dot.count(" -> "), diagnostic.count(" -> "))

    def test_multi_role_link_keeps_a_small_junction(self) -> None:
        protocol = InterfaceProtocol.define(
            "three_role_control",
            roles=frozenset(("source", "relay", "sink")),
            event_kinds={
                "request": InterfaceEventKind(
                    "request", "source", "relay", EventSchema("REQUEST")
                ),
                "forward": InterfaceEventKind(
                    "forward", "relay", "sink", EventSchema("FORWARD")
                ),
            },
            fragments=(SemanticFragment.empty("three_role_control.base"),),
        )
        duts = {
            role: VirtualDut(
                role,
                {"link": InterfacePort("link", protocol, role)},
            )
            for role in ("source", "relay", "sink")
        }
        link = InterfaceConnection(
            "shared_control",
            protocol,
            {
                role: VirtualDutPortRef(role, "link")
                for role in ("source", "relay", "sink")
            },
        )
        system = SystemProtocol("three_party", duts, {link.name: link})
        dot = system_topology_dot(system)

        self.assertIn("shape=point", dot)
        self.assertIn("three_role_control", dot)
        self.assertNotIn("shared_control", dot)
        self.assertIn("relay · link", dot)
        self.assertNotIn("shape=diamond", dot)

        overview = system_topology_dot(
            system,
            detail=DiagramDetail.OVERVIEW,
        )
        diagnostic = system_topology_dot(
            system,
            detail=DiagramDetail.DIAGNOSTIC,
        )

        self.assertIn("shape=point", overview)
        self.assertNotIn("relay · link", overview)
        self.assertIn("shared_control", diagnostic)
        self.assertEqual(dot.count(" -> "), overview.count(" -> "))
        self.assertEqual(dot.count(" -> "), diagnostic.count(" -> "))

    def test_link_profile_refinement_only_adds_semantics(self) -> None:
        protocol = ready_valid_protocol()
        extra = SemanticFragment(
            "bounded_stall",
            constraints=(
                SemanticConstraint(
                    "eventual_accept",
                    "a continuously offered transfer is eventually accepted",
                    ConstraintScope.INTERFACE,
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
            ("interface.data_path.stable_while_stalled",),
            tuple(item.name for item in elaborated.semantics.constraints),
        )

    def test_unconnected_port_is_rejected(self) -> None:
        system = connected_system()
        protocol = next(iter(system.connections.values())).protocol
        dangling = VirtualDut(
            "dangling",
            {"in": InterfacePort("in", protocol, "sink")},
        )
        invalid = SystemProtocol(
            system.name,
            {**system.virtual_duts, dangling.name: dangling},
            system.connections,
        )

        with self.assertRaisesRegex(ValueError, "unconnected VirtualDut ports"):
            invalid.elaborate()

    def test_system_can_be_encapsulated_as_a_virtual_dut(self) -> None:
        protocol = ready_valid_protocol()
        endpoint = VirtualDut(
            "endpoint",
            {"external": InterfacePort("external", protocol, "source")},
        )
        subsystem = SystemProtocol(
            "subsystem",
            {endpoint.name: endpoint},
            {},
            {"out": VirtualDutPortRef("endpoint", "external")},
        )

        wrapper = subsystem.as_virtual_dut("chiplet")

        self.assertEqual("SystemProtocol", wrapper.realization_name)
        self.assertEqual("source", wrapper.port("out").role)
        self.assertIs(subsystem, wrapper.subsystem)

    def test_one_link_is_a_complete_executable_system_protocol(self) -> None:
        protocol = request_response_protocol("local_bus", "LOCAL")
        client_model = CaptureBackend()
        server_model = FunctionBackend(
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
            {"bus": InterfacePort("bus", protocol, "initiator")},
            backend=client_model,
        )
        server = VirtualDut(
            "server",
            {"bus": InterfacePort("bus", protocol, "target")},
            backend=server_model,
        )
        system = SystemProtocol.from_interface(
            "point_to_point",
            connection_name="bus",
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
            {"bus": InterfacePort("bus", upstream, "initiator")},
            backend=CaptureBackend(),
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
                "upstream": InterfacePort("upstream", upstream, "target"),
                "downstream": InterfacePort(
                    "downstream", downstream, "initiator"
                ),
            },
            frozenset((DutBehaviorTag.TRANSFORMING,)),
            backend=FunctionBackend(bridge_function),
        )
        server = VirtualDut(
            "point_b",
            {"bus": InterfacePort("bus", downstream, "target")},
            backend=FunctionBackend(
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
        link_a = InterfaceConnection(
            "link_a",
            upstream,
            {
                "initiator": VirtualDutPortRef("point_a", "bus"),
                "target": VirtualDutPortRef("bridge", "upstream"),
            },
        )
        link_b = InterfaceConnection(
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
            tuple(item.connection for item in transition.emissions),
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
