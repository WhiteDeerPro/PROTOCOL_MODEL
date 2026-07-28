from __future__ import annotations

from random import Random
import unittest

from protocol_model.integrations.recipes.amba.endpoints.apb import (
    build_apb_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.queued import (
    build_amba_queued_address_responder_vdut,
)
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.scenario import (
    NoEnabledTraffic,
    RandomTrafficController,
    assemble_random_traffic_source,
)
from protocol_model.semantics import CanonicalEvent, EventOffer
from protocol_model.system import (
    DutAdvanceAction,
    InterfaceConnection,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address import AddressSpace, MemoryRegion
from protocol_model.virtual_dut.backend import NoOpBackend
from protocol_model.virtual_dut.backend.queued_address import (
    constant_address_delay,
)


class RandomTrafficControllerTest(unittest.TestCase):
    def test_equal_rng_states_generate_equal_canonical_events(self) -> None:
        protocol = build_apb4_interface()
        left = RandomTrafficController(protocol, "requester", Random(11))
        right = RandomTrafficController(protocol, "requester", Random(11))
        constraint = EventOffer.constrained(
            "WRITE", payload={"addr": 0x2000}
        )

        left_event = left.next_event(offer=constraint)
        right_event = right.next_event(offer=constraint)

        self.assertEqual(
            left_event.semantic_identity, right_event.semantic_identity
        )
        self.assertEqual(left.trace(), right.trace())

    def test_source_role_offers_close_until_peer_completion(self) -> None:
        protocol = build_apb4_interface()
        controller = RandomTrafficController(
            protocol,
            "requester",
            Random(17),
        )

        self.assertEqual(
            {"READ", "WRITE"},
            {offer.kind for offer in controller.enabled_offers()},
        )
        request = controller.next_event(
            offer=EventOffer.constrained(
                "READ", payload={"addr": 0x1000}
            )
        )

        self.assertTrue(
            protocol.event_kind_for("READ").schema.contains(request)
        )
        self.assertEqual((), controller.enabled_offers())
        with self.assertRaises(NoEnabledTraffic):
            controller.next_event()

        controller.observe(
            CanonicalEvent(
                "READ_RESPONSE",
                None,
                {"data": 0x11223344, "error": False},
            )
        )
        trace = controller.trace()

        self.assertEqual(
            ("READ", "READ_RESPONSE"),
            tuple(event.kind for event in trace.events),
        )
        self.assertEqual(((0, 1),), trace.causal_edges)
        self.assertTrue(controller.is_quiescent())
        self.assertEqual(
            {"READ", "WRITE"},
            {offer.kind for offer in controller.enabled_offers()},
        )

    def test_idle_source_harness_drives_and_tracks_one_apb_transfer(self) -> None:
        protocol = build_apb4_interface()
        source = assemble_random_traffic_source(
            "source",
            protocol,
            "requester",
            Random(23),
            port_name="apb",
            connection_name="bus",
        )
        target = build_apb_address_space_vdut(
            "target",
            protocol,
            AddressSpace(
                (
                    MemoryRegion(
                        "ram",
                        0x100,
                        base_address=0x1000,
                        initial_content=bytes.fromhex("44332211"),
                    ),
                )
            ),
        )
        link = InterfaceConnection(
            "bus",
            protocol,
            {
                "requester": source.origin,
                "completer": VirtualDutPortRef("target", "apb"),
            },
        )
        system = SystemProtocol(
            "random_apb",
            {
                source.virtual_dut.name: source.virtual_dut,
                target.name: target,
            },
            {link.name: link},
        )
        session = system.open_session()

        self.assertIsInstance(source.virtual_dut.backend, NoOpBackend)
        driven = source.controller.drive(
            session,
            session.initial_state(),
            offer=EventOffer.constrained(
                "READ", payload={"addr": 0x1000}
            ),
        )

        self.assertIsNone(driven.transition.fault)
        self.assertEqual(source.origin, driven.action.origin)
        self.assertEqual(
            ("READ", "READ_RESPONSE"),
            tuple(item.event.kind for item in driven.transition.emissions),
        )
        self.assertEqual(
            0x11223344,
            driven.transition.emissions[-1].event.payload["data"],
        )
        trace = source.controller.trace()
        self.assertEqual(
            ("READ", "READ_RESPONSE"),
            tuple(event.kind for event in trace.events),
        )
        self.assertTrue(source.controller.is_quiescent())
        self.assertTrue(session.is_quiescent(driven.transition.state))
        self.assertTrue(
            all(
                protocol.event_kind_for(event.kind).schema.contains(event)
                for event in trace.events
            )
        )

    def test_controller_tracks_a_response_from_explicit_dut_advance(self) -> None:
        protocol = build_apb4_interface()
        source = assemble_random_traffic_source(
            "source",
            protocol,
            "requester",
            Random(29),
            port_name="apb",
            connection_name="bus",
        )
        target = build_amba_queued_address_responder_vdut(
            "target",
            protocol,
            AddressSpace(
                (
                    MemoryRegion(
                        "ram",
                        0x100,
                        base_address=0x1000,
                        initial_content=bytes.fromhex("44332211"),
                    ),
                )
            ),
            capacity=2,
            delay_policy=constant_address_delay(2),
            port_name="apb",
        )
        system = SystemProtocol.from_interface(
            "random_delayed_apb",
            connection_name="bus",
            protocol=protocol,
            endpoints={
                "requester": (source.virtual_dut, "apb"),
                "completer": (target, "apb"),
            },
        )
        session = system.open_session()
        driven = source.controller.drive(
            session,
            session.initial_state(),
            offer=EventOffer.constrained(
                "READ", payload={"addr": 0x1000}
            ),
        )
        self.assertEqual(
            ("READ",),
            tuple(item.event.kind for item in driven.transition.emissions),
        )

        waiting = session.step(
            driven.transition.state, DutAdvanceAction("target")
        )
        source.controller.observe_system_events(waiting.emissions)
        completed = session.step(
            waiting.state, DutAdvanceAction("target")
        )
        source.controller.observe_system_events(completed.emissions)

        self.assertIsNone(completed.fault)
        self.assertEqual(
            ("READ_RESPONSE",),
            tuple(item.event.kind for item in completed.emissions),
        )
        self.assertEqual(
            source.controller.state, completed.state.connection_states["bus"]
        )
        self.assertTrue(source.controller.is_quiescent())
        self.assertTrue(session.is_quiescent(completed.state))


if __name__ == "__main__":
    unittest.main()
