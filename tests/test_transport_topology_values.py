from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from protocol_model.system.topology.model import VirtualDutPortRef
from protocol_model.system.topology.transport import (
    DirectedTransportConnection,
)
from protocol_model.system import (
    PortOwnerKind,
    SystemProtocolBuilder,
)
from protocol_model.virtual_dut.boundary import VirtualDut
from protocol_model.virtual_dut.boundary.transport import (
    TransportDirection,
    TransportPort,
)
from protocol_model.visualization import (
    expanded_system_topology_dot,
    system_topology_dot,
)
from protocol_model.visualization.policy import DiagramDetail


class TransportBoundaryValueTest(unittest.TestCase):
    def test_port_normalizes_direction_and_keeps_domains(self) -> None:
        capability = {"credits": 2}
        port = TransportPort(
            "txreq",
            "amba.chi.issue_h",
            "transmit",
            capability=capability,
            clock_domain="chi_clk",
            reset_domain="chi_reset",
        )

        self.assertIs(TransportDirection.TRANSMIT, port.direction)
        self.assertIs(capability, port.capability)
        self.assertEqual("chi_clk", port.clock_domain)
        with self.assertRaises(FrozenInstanceError):
            port.name = "other"

    def test_port_rejects_incomplete_identity_or_direction(self) -> None:
        for name, family, direction in (
            ("", "chi", TransportDirection.RECEIVE),
            ("rxreq", "", TransportDirection.RECEIVE),
            ("rxreq", "chi", "sideways"),
        ):
            with self.subTest(
                name=name, family=family, direction=direction
            ):
                with self.assertRaises(ValueError):
                    TransportPort(name, family, direction)

        with self.assertRaises(ValueError):
            TransportPort(
                "rxreq",
                "chi",
                TransportDirection.RECEIVE,
                clock_domain="",
            )


class DirectedTransportConnectionValueTest(unittest.TestCase):
    def test_connection_records_one_immutable_directed_edge(self) -> None:
        profile = {"credit_capacity": 2}
        connection = DirectedTransportConnection(
            "rn_to_xp",
            "amba.chi.issue_h",
            VirtualDutPortRef("rn", "txreq"),
            VirtualDutPortRef("xp", "rxreq"),
            profile,
        )

        self.assertEqual("rn.txreq", connection.transmitter.qualified_name)
        self.assertEqual("xp.rxreq", connection.receiver.qualified_name)
        self.assertIs(profile, connection.profile)
        with self.assertRaises(FrozenInstanceError):
            connection.name = "other"

    def test_connection_rejects_invalid_or_identical_endpoints(self) -> None:
        endpoint = VirtualDutPortRef("node", "port")
        with self.assertRaises(ValueError):
            DirectedTransportConnection(
                "loop", "chi", endpoint, endpoint
            )
        with self.assertRaises(TypeError):
            DirectedTransportConnection(
                "bad", "chi", endpoint, object()
            )
        with self.assertRaises(ValueError):
            VirtualDutPortRef("", "tx")


class DirectedTransportSystemTopologyTest(unittest.TestCase):
    @staticmethod
    def system():
        family = "amba.chi.issue_h"
        profile = {"credit_capacity": 2}
        builder = SystemProtocolBuilder("free_transport_topology")
        builder.add_dut(
            VirtualDut(
                "source",
                {
                    "tx": TransportPort(
                        "tx",
                        family,
                        TransportDirection.TRANSMIT,
                        clock_domain="chi_clk",
                    )
                },
            )
        )
        builder.add_dut(
            VirtualDut(
                "sink",
                {
                    "rx": TransportPort(
                        "rx",
                        family,
                        TransportDirection.RECEIVE,
                        clock_domain="chi_clk",
                    )
                },
            )
        )
        builder.connect_transport(
            "source_to_sink",
            family,
            VirtualDutPortRef("source", "tx"),
            VirtualDutPortRef("sink", "rx"),
            profile=profile,
        )
        return builder.build(), profile

    def test_elaboration_derives_plan_from_the_single_connection_registry(
        self,
    ) -> None:
        system, profile = self.system()
        elaborated = system.elaborate()

        self.assertEqual(("source_to_sink",), tuple(system.connections))
        self.assertEqual((), tuple(system.interface_connections))
        self.assertEqual(
            ("source_to_sink",), tuple(system.transport_connections)
        )
        self.assertIsNotNone(elaborated.transport_plan)
        assert elaborated.transport_plan is not None
        hop = elaborated.transport_plan.hops_by_name["source_to_sink"]
        self.assertIs(profile, hop.profile)
        self.assertEqual("source.tx", hop.transmitter.qualified_name)
        self.assertEqual("sink.rx", hop.receiver.qualified_name)
        self.assertIs(
            PortOwnerKind.TRANSPORT_CONNECTION,
            elaborated.owner_by_port[hop.transmitter].kind,
        )
        dot = system_topology_dot(system)
        self.assertNotIn("source_to_sink", dot)
        self.assertIn("tx → rx", dot)
        self.assertNotIn("dir=none", dot)

        overview = system_topology_dot(
            system,
            detail=DiagramDetail.OVERVIEW,
        )
        diagnostic = system_topology_dot(
            system,
            detail=DiagramDetail.DIAGNOSTIC,
        )
        self.assertIn("amba.chi.issue_h", overview)
        self.assertNotIn("tx → rx", overview)
        self.assertIn("source_to_sink", diagnostic)
        self.assertEqual(dot.count(" -> "), overview.count(" -> "))
        self.assertEqual(dot.count(" -> "), diagnostic.count(" -> "))

        expanded = expanded_system_topology_dot(system)
        self.assertIn("transport port", expanded)
        self.assertNotIn("source_to_sink", expanded)
        with self.assertRaisesRegex(ValueError, "transport-family session"):
            system.open_session()

    def test_elaboration_rejects_direction_or_family_mismatch(self) -> None:
        family = "amba.chi.issue_h"
        for source_family, source_direction, message in (
            (family, TransportDirection.RECEIVE, "direction"),
            ("another.transport", TransportDirection.TRANSMIT, "family"),
        ):
            with self.subTest(
                family=source_family, direction=source_direction
            ):
                builder = SystemProtocolBuilder("invalid_transport")
                builder.add_dut(
                    VirtualDut(
                        "source",
                        {
                            "tx": TransportPort(
                                "tx",
                                source_family,
                                source_direction,
                            )
                        },
                    )
                )
                builder.add_dut(
                    VirtualDut(
                        "sink",
                        {
                            "rx": TransportPort(
                                "rx", family, TransportDirection.RECEIVE
                            )
                        },
                    )
                )
                builder.connect_transport(
                    "hop",
                    family,
                    VirtualDutPortRef("source", "tx"),
                    VirtualDutPortRef("sink", "rx"),
                )
                with self.assertRaisesRegex(ValueError, message):
                    builder.build().elaborate()

    def test_transport_boundary_survives_recursive_encapsulation(self) -> None:
        system, _ = self.system()
        exposed = type(system)(
            system.name,
            system.virtual_duts,
            {},
            {
                "external_tx": VirtualDutPortRef("source", "tx"),
                "external_rx": VirtualDutPortRef("sink", "rx"),
            },
        )
        # A boundary-only variant demonstrates recursive port projection
        # without making one port both internal and external.
        subsystem = exposed.as_virtual_dut("subsystem")

        port = subsystem.port("external_tx")
        self.assertIsInstance(port, TransportPort)
        self.assertIs(TransportDirection.TRANSMIT, port.direction)


if __name__ == "__main__":
    unittest.main()
