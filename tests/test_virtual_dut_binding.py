from __future__ import annotations

import unittest

from protocol_model.integrations.attachments.amba.apb import (
    ApbCompleterAttachment,
)
from protocol_model.integrations.recipes.amba.endpoints import (
    build_apb_address_space_vdut,
)
from protocol_model.protocols.amba.apb.apb3 import build_apb3_interface
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.axi.axi4 import build_axi4_interface
from protocol_model.protocols.amba.axi.axi4_stream import build_axi4_stream_interface
from protocol_model.semantics import SemanticFragment
from protocol_model.virtual_dut import (
    AddressSpace,
    InterfaceAttachmentBinding,
    InterfacePort,
    RegisterRegion,
    RegisterSpec,
    VirtualDutBuilder,
)
from protocol_model.virtual_dut.attachments import (
    EmptyEndpointAttachment,
    EmptyEndpointMode,
)
from protocol_model.virtual_dut.backend.address_space import (
    PassiveAddressSpaceBackend,
)


class VirtualDutBindingTest(unittest.TestCase):
    def test_apb_completer_binding_and_recipe_share_the_declared_port(self) -> None:
        protocol = build_apb4_interface()
        attachment = ApbCompleterAttachment(protocol)
        port = InterfacePort("apb", protocol, "completer")
        binding = InterfaceAttachmentBinding(port, attachment)

        direct = VirtualDutBuilder("direct_registers").bind(binding).build()

        self.assertIs(direct.port("apb"), port)
        self.assertIs(direct.bindings["apb"], binding)
        self.assertIs(direct.bindings["apb"].attachment, attachment)

        recipe = build_apb_address_space_vdut(
            "recipe_registers",
            protocol,
            AddressSpace(
                (
                    RegisterRegion(
                        "control",
                        (RegisterSpec("value", 0),),
                    ),
                )
            ),
        )

        recipe_binding = recipe.bindings["apb"]
        self.assertIs(recipe_binding.port, recipe.port("apb"))
        self.assertIsInstance(
            recipe_binding.attachment, ApbCompleterAttachment
        )
        self.assertEqual("completer", recipe_binding.port.role)

    def test_binding_rejects_attachment_role_mismatch(self) -> None:
        protocol = build_apb4_interface()

        with self.assertRaisesRegex(ValueError, "role"):
            InterfaceAttachmentBinding(
                InterfacePort("apb", protocol, "requester"),
                ApbCompleterAttachment(protocol),
            )

    def test_binding_rejects_different_apb_transports(self) -> None:
        cases = (
            ("revision", build_apb4_interface(), build_apb3_interface()),
            (
                "data_width",
                build_apb4_interface(data_width=32),
                build_apb4_interface(data_width=16),
            ),
        )
        for name, attachment_protocol, port_protocol in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "protocol"):
                    InterfaceAttachmentBinding(
                        InterfacePort("apb", port_protocol, "completer"),
                        ApbCompleterAttachment(attachment_protocol),
                    )

    def test_base_attachment_can_bind_a_transport_equivalent_profile(self) -> None:
        base = build_apb4_interface()
        profile = base.refine(
            "apb4_checked",
            SemanticFragment.empty("apb4_checked.extra_semantics"),
        )

        binding = InterfaceAttachmentBinding(
            InterfacePort("apb", profile, "completer"),
            ApbCompleterAttachment(base),
        )
        dut = VirtualDutBuilder("profiled_registers").bind(binding).build()

        self.assertIs(dut.port("apb").protocol, profile)
        self.assertIs(dut.bindings["apb"].attachment.protocol, base)
        self.assertTrue(base.has_same_interface_shape_as(profile))

    def test_independently_built_axi_transports_have_stable_shape(self) -> None:
        cases = (
            (build_axi4_interface(), build_axi4_interface(), "manager"),
            (
                build_axi4_stream_interface(),
                build_axi4_stream_interface(),
                "transmitter",
            ),
        )

        for attachment_protocol, port_protocol, role in cases:
            with self.subTest(protocol=port_protocol.name):
                attachment = EmptyEndpointAttachment(
                    attachment_protocol,
                    role,
                    EmptyEndpointMode.IDLE_SOURCE,
                )
                binding = InterfaceAttachmentBinding(
                    InterfacePort("link", port_protocol, role), attachment
                )

                self.assertEqual("link", binding.name)
                self.assertTrue(
                    attachment_protocol.has_same_interface_shape_as(port_protocol)
                )

    def test_virtual_dut_rejects_backend_binding_split(self) -> None:
        protocol = build_apb4_interface()
        backend_attachment = ApbCompleterAttachment(protocol)
        declared_attachment = ApbCompleterAttachment(protocol)
        port = InterfacePort("apb", protocol, "completer")
        backend_binding = InterfaceAttachmentBinding(port, backend_attachment)
        declared_binding = InterfaceAttachmentBinding(port, declared_attachment)
        backend = PassiveAddressSpaceBackend(
            AddressSpace(
                (
                    RegisterRegion(
                        "control",
                        (RegisterSpec("value", 0),),
                    ),
                )
            ),
            {"apb": backend_binding},
        )

        with self.assertRaisesRegex(ValueError, "used by its backend"):
            (
                VirtualDutBuilder("split")
                .bind(declared_binding)
                .with_backend(backend)
                .build()
            )

    def test_opaque_virtual_dut_does_not_require_a_binding(self) -> None:
        protocol = build_apb4_interface()

        opaque = (
            VirtualDutBuilder("opaque_apb_module")
            .port("apb", protocol, "completer")
            .build()
        )

        self.assertIn("apb", opaque.ports)
        self.assertEqual({}, dict(opaque.bindings))
        self.assertIsNone(opaque.backend)


if __name__ == "__main__":
    unittest.main()
