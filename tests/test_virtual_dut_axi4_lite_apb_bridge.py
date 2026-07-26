from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints import (
    build_apb_address_space_vdut,
)
from protocol_model.semantics import CanonicalEvent
from protocol_model.system import (
    InterfaceConnection,
    SystemAction,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address import (
    AddressSpace,
    MemoryRegion,
)
from protocol_model.virtual_dut.backend import CaptureBackend
from protocol_model.virtual_dut.boundary import InterfacePort, VirtualDut
from protocol_model.virtual_dut.fabric import AddressRoute
from protocol_model.integrations.recipes.amba.bridges import (
    build_axi4_lite_to_apb_bridge_vdut,
)
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.axi.axi4_lite import build_axi4_lite_interface


class Axi4LiteToApbBridgeTest(unittest.TestCase):
    def _system(self) -> SystemProtocol:
        axi = build_axi4_lite_interface()
        apb = build_apb4_interface()
        manager = VirtualDut(
            "manager",
            {"axi": InterfacePort("axi", axi, "manager")},
            backend=CaptureBackend(),
        )
        bridge = build_axi4_lite_to_apb_bridge_vdut(
            "bridge",
            axi,
            apb,
            (AddressRoute("peripheral", 0x1000, 0x100, "m_apb"),),
        )
        peripheral = build_apb_address_space_vdut(
            "peripheral",
            apb,
            AddressSpace((MemoryRegion("ram", 0x100, base_address=0x1000),)),
        )
        links = (
            InterfaceConnection(
                "axi",
                axi,
                {
                    "manager": VirtualDutPortRef("manager", "axi"),
                    "subordinate": VirtualDutPortRef("bridge", "s_axi"),
                },
            ),
            InterfaceConnection(
                "apb",
                apb,
                {
                    "requester": VirtualDutPortRef("bridge", "m_apb"),
                    "completer": VirtualDutPortRef("peripheral", "apb"),
                },
            ),
        )
        return SystemProtocol(
            "axi4_lite_apb",
            {item.name: item for item in (manager, bridge, peripheral)},
            {item.name: item for item in links},
        )

    @staticmethod
    def action(kind: str, payload: dict[str, object]) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef("manager", "axi"),
            CanonicalEvent(kind, None, payload),
        )

    def test_translates_write_read_and_decode_error_across_two_links(self) -> None:
        session = self._system().open_session()
        state = session.initial_state()

        data = session.step(
            state,
            self.action("W", {"data": 0x11223344, "strb": 0b1111}),
        )
        written = session.step(
            data.state,
            self.action("AW", {"addr": 0x1000, "prot": 0b101}),
        )
        read = session.step(
            written.state,
            self.action("AR", {"addr": 0x1000, "prot": 0b010}),
        )
        missing = session.step(
            read.state,
            self.action("AR", {"addr": 0x2000, "prot": 0}),
        )

        for transition in (data, written, read, missing):
            self.assertIsNone(transition.fault)
        self.assertEqual(
            ("axi", "apb", "apb", "axi"),
            tuple(item.connection for item in written.emissions),
        )
        self.assertEqual("B", written.emissions[-1].event.kind)
        self.assertEqual(0x11223344, read.emissions[-1].event.payload["data"])
        self.assertEqual("DECERR", missing.emissions[-1].event.payload["resp"])
        self.assertEqual(
            ("axi", "axi"), tuple(item.connection for item in missing.emissions)
        )
        self.assertTrue(session.is_quiescent(missing.state))

    def test_rejects_width_or_protection_profiles_it_cannot_preserve(self) -> None:
        axi = build_axi4_lite_interface()
        apb = build_apb4_interface()
        route = (AddressRoute("peripheral", 0, 0x100, "m_apb"),)

        with self.assertRaisesRegex(ValueError, "equal data widths"):
            build_axi4_lite_to_apb_bridge_vdut(
                "width_bridge",
                axi,
                build_apb4_interface(data_width=16),
                route,
            )
        with self.assertRaisesRegex(ValueError, "PPROT"):
            build_axi4_lite_to_apb_bridge_vdut(
                "protection_bridge",
                axi,
                build_apb4_interface(pprot_present=False),
                route,
            )
        with self.assertRaisesRegex(ValueError, "PSTRB"):
            build_axi4_lite_to_apb_bridge_vdut(
                "strobe_bridge",
                axi,
                build_apb4_interface(pstrb_present=False),
                route,
            )


if __name__ == "__main__":
    unittest.main()
