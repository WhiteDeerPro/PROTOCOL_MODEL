from __future__ import annotations

import unittest

from protocol_model import (
    CanonicalEvent,
    NoOpModel,
    PortInput,
    ProtocolLink,
    SystemAction,
    SystemProtocol,
    VirtualDutPortRef,
    build_ahb_blackhole_sink_vdut,
    build_ahb_idle_source_vdut,
    build_apb_blackhole_sink_vdut,
    build_apb_idle_source_vdut,
    build_axi4_blackhole_sink_vdut,
    build_axi4_idle_source_vdut,
)
from protocol_model.link.amba.ahb.ahb_lite import build_ahb_lite_link
from protocol_model.link.amba.ahb.ahb5 import build_ahb5_link
from protocol_model.link.amba.apb.apb4 import build_apb4_link
from protocol_model.link.amba.axi.axi4 import build_axi4_link
from protocol_model.virtual_dut.attachments import (
    EmptyEndpointAttachment,
    EmptyEndpointMode,
)


class EmptyEndpointTest(unittest.TestCase):
    def test_amba_recipes_bind_expected_roles_and_modes(self) -> None:
        cases = (
            (
                "apb",
                build_apb4_link(),
                build_apb_idle_source_vdut,
                build_apb_blackhole_sink_vdut,
                "requester",
                "completer",
            ),
            (
                "ahb",
                build_ahb_lite_link(),
                build_ahb_idle_source_vdut,
                build_ahb_blackhole_sink_vdut,
                "manager",
                "subordinate",
            ),
            (
                "ahb",
                build_ahb5_link(),
                build_ahb_idle_source_vdut,
                build_ahb_blackhole_sink_vdut,
                "manager",
                "subordinate",
            ),
            (
                "axi",
                build_axi4_link(),
                build_axi4_idle_source_vdut,
                build_axi4_blackhole_sink_vdut,
                "manager",
                "subordinate",
            ),
        )

        for (
            port_name,
            protocol,
            source_builder,
            sink_builder,
            source_role,
            sink_role,
        ) in cases:
            with self.subTest(protocol=protocol.name):
                source = source_builder("source", protocol)
                sink = sink_builder("sink", protocol)

                self.assertEqual(source_role, source.port(port_name).role)
                self.assertEqual(sink_role, sink.port(port_name).role)
                self.assertIs(source.port(port_name).protocol, protocol)
                self.assertIs(sink.port(port_name).protocol, protocol)

                source_binding = source.bindings[port_name]
                sink_binding = sink.bindings[port_name]
                self.assertEqual(source.port(port_name), source_binding.port)
                self.assertEqual(sink.port(port_name), sink_binding.port)
                self.assertIsInstance(
                    source_binding.attachment, EmptyEndpointAttachment
                )
                self.assertIsInstance(
                    sink_binding.attachment, EmptyEndpointAttachment
                )
                self.assertIs(
                    EmptyEndpointMode.IDLE_SOURCE,
                    source_binding.attachment.mode,
                )
                self.assertIs(
                    EmptyEndpointMode.BLACKHOLE_SINK,
                    sink_binding.attachment.mode,
                )

    def test_noop_backend_consumes_without_emission(self) -> None:
        model = NoOpModel()
        transition = model.accept(
            model.initial_state(),
            PortInput("input", CanonicalEvent("IGNORED")),
        )

        self.assertIsNone(transition.fault)
        self.assertEqual((), transition.emissions)
        self.assertIsNone(transition.state)
        self.assertTrue(model.is_quiescent(transition.state))

    def test_apb_blackhole_leaves_request_pending(self) -> None:
        protocol = build_apb4_link()
        source = build_apb_idle_source_vdut("source", protocol)
        sink = build_apb_blackhole_sink_vdut("sink", protocol)
        link = ProtocolLink(
            "apb_bus",
            protocol,
            {
                "requester": VirtualDutPortRef("source", "apb"),
                "completer": VirtualDutPortRef("sink", "apb"),
            },
        )
        system = SystemProtocol(
            "blackhole_system",
            {source.name: source, sink.name: sink},
            {link.name: link},
        )
        session = system.open_session()
        initial = session.initial_state()

        step = session.step(
            initial,
            SystemAction(
                VirtualDutPortRef("source", "apb"),
                CanonicalEvent("READ", None, {"addr": 0x1000, "prot": 0}),
            ),
        )

        self.assertIsNone(step.fault)
        self.assertEqual(("READ",), tuple(item.event.kind for item in step.emissions))
        self.assertFalse(session.is_quiescent(step.state))

    def test_amba_recipe_rejects_wrong_protocol_family(self) -> None:
        axi = build_axi4_link()
        apb = build_apb4_link()

        with self.assertRaisesRegex(ValueError, "requires protocol family"):
            build_apb_idle_source_vdut("wrong_source", axi)
        with self.assertRaisesRegex(ValueError, "requires protocol family"):
            build_axi4_blackhole_sink_vdut("wrong_sink", apb)


if __name__ == "__main__":
    unittest.main()
