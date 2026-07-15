from __future__ import annotations

import unittest

from protocol_model import (
    AddressRoute,
    AddressSpace,
    CanonicalEvent,
    CaptureModel,
    ProtocolLink,
    ProtocolPort,
    RegisterRegion,
    RegisterSpec,
    SystemAction,
    SystemProtocol,
    VirtualDut,
    VirtualDutPortRef,
    build_apb_address_fabric_vdut,
    build_apb_address_space_vdut,
)
from protocol_model.link.amba.apb.apb4 import build_apb4_link
from protocol_model.integrations.attachments.amba.apb import (
    ApbCompleterAttachment,
    ApbRequesterAttachment,
)
from protocol_model.virtual_dut.binding import PortAttachmentBinding
from protocol_model.virtual_dut.fabric import (
    SingleIngressAddressFabricBackend,
)


class ApbAddressFabricTest(unittest.TestCase):
    def _system(self) -> SystemProtocol:
        protocol = build_apb4_link()
        manager = VirtualDut(
            "manager",
            {"apb": ProtocolPort("apb", protocol, "requester")},
            model=CaptureModel(),
        )
        fabric = build_apb_address_fabric_vdut(
            "peripheral_fabric",
            protocol,
            (
                AddressRoute("control", 0x1000, 0x100, "control"),
                AddressRoute("status", 0x2000, 0x100, "status"),
            ),
        )
        control = build_apb_address_space_vdut(
            "control",
            protocol,
            AddressSpace(
                (
                    RegisterRegion(
                        "control_regs",
                        (RegisterSpec("value", 0),),
                        base_address=0x1000,
                    ),
                )
            ),
        )
        status = build_apb_address_space_vdut(
            "status",
            protocol,
            AddressSpace(
                (
                    RegisterRegion(
                        "status_regs",
                        (RegisterSpec("value", 0),),
                        base_address=0x2000,
                    ),
                )
            ),
        )
        links = (
            ProtocolLink(
                "upstream_bus",
                protocol,
                {
                    "requester": VirtualDutPortRef("manager", "apb"),
                    "completer": VirtualDutPortRef(
                        "peripheral_fabric", "upstream"
                    ),
                },
            ),
            ProtocolLink(
                "control_bus",
                protocol,
                {
                    "requester": VirtualDutPortRef(
                        "peripheral_fabric", "control"
                    ),
                    "completer": VirtualDutPortRef("control", "apb"),
                },
            ),
            ProtocolLink(
                "status_bus",
                protocol,
                {
                    "requester": VirtualDutPortRef(
                        "peripheral_fabric", "status"
                    ),
                    "completer": VirtualDutPortRef("status", "apb"),
                },
            ),
        )
        return SystemProtocol(
            "apb_star",
            {
                item.name: item
                for item in (manager, fabric, control, status)
            },
            {item.name: item for item in links},
        )

    @staticmethod
    def _write(address: int, data: int) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef("manager", "apb"),
            CanonicalEvent(
                "WRITE",
                None,
                {
                    "addr": address,
                    "prot": 0,
                    "data": data,
                    "strb": 0b1111,
                },
            ),
        )

    @staticmethod
    def _read(address: int) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef("manager", "apb"),
            CanonicalEvent("READ", None, {"addr": address, "prot": 0}),
        )

    def test_routes_two_windows_and_returns_each_completion(self) -> None:
        session = self._system().open_session()
        state = session.initial_state()

        control_write = session.step(state, self._write(0x1000, 0x11223344))
        status_write = session.step(
            control_write.state, self._write(0x2000, 0xAABBCCDD)
        )
        control_read = session.step(status_write.state, self._read(0x1000))
        status_read = session.step(control_read.state, self._read(0x2000))

        for transition in (
            control_write,
            status_write,
            control_read,
            status_read,
        ):
            self.assertIsNone(transition.fault)
        self.assertEqual(
            ("upstream_bus", "control_bus", "control_bus", "upstream_bus"),
            tuple(item.link for item in control_write.emissions),
        )
        self.assertEqual(
            ("upstream_bus", "status_bus", "status_bus", "upstream_bus"),
            tuple(item.link for item in status_write.emissions),
        )
        self.assertEqual(0x11223344, control_read.emissions[-1].event.payload["data"])
        self.assertEqual(0xAABBCCDD, status_read.emissions[-1].event.payload["data"])
        self.assertEqual(
            frozenset(((0, 1), (1, 2), (0, 3), (2, 3))),
            frozenset(control_write.state.causal_edges),
        )
        self.assertTrue(session.is_quiescent(status_read.state))

    def test_unmapped_access_completes_with_error_without_an_egress(self) -> None:
        session = self._system().open_session()
        initial = session.initial_state()

        missing = session.step(initial, self._read(0x3000))

        self.assertIsNone(missing.fault)
        self.assertEqual(
            ("upstream_bus", "upstream_bus"),
            tuple(item.link for item in missing.emissions),
        )
        self.assertEqual(
            ("READ", "READ_RESPONSE"),
            tuple(item.event.kind for item in missing.emissions),
        )
        self.assertTrue(missing.emissions[-1].event.payload["error"])
        self.assertEqual(
            initial.dut_states["control"],
            missing.state.dut_states["control"],
        )
        self.assertEqual(
            initial.dut_states["status"],
            missing.state.dut_states["status"],
        )

    def test_route_configuration_rejects_ambiguous_or_unbound_ports(self) -> None:
        protocol = build_apb4_link()
        with self.assertRaisesRegex(ValueError, "overlap"):
            build_apb_address_fabric_vdut(
                "ambiguous",
                protocol,
                (
                    AddressRoute("first", 0x1000, 0x100, "first"),
                    AddressRoute("second", 0x1080, 0x100, "second"),
                ),
            )
        with self.assertRaisesRegex(ValueError, "output window"):
            build_apb_address_fabric_vdut(
                "unencodable",
                protocol,
                (
                    AddressRoute(
                        "target",
                        0,
                        0x100,
                        "target",
                        output_base_address=1 << 32,
                    ),
                ),
            )

        completer = ApbCompleterAttachment(protocol)
        requester = ApbRequesterAttachment(protocol)
        ingress = PortAttachmentBinding(
            ProtocolPort("upstream", protocol, completer.role), completer
        )
        known = PortAttachmentBinding(
            ProtocolPort("known", protocol, requester.role), requester
        )
        with self.assertRaisesRegex(ValueError, "unknown egress"):
            SingleIngressAddressFabricBackend(
                ingress,
                {"known": known},
                (AddressRoute("missing", 0, 0x100, "missing"),),
            )
        invalid = PortAttachmentBinding(
            ProtocolPort("target", protocol, completer.role), completer
        )
        with self.assertRaisesRegex(TypeError, "requester bindings"):
            SingleIngressAddressFabricBackend(
                ingress,
                {"target": invalid},
                (AddressRoute("target", 0, 0x100, "target"),),
            )


if __name__ == "__main__":
    unittest.main()
