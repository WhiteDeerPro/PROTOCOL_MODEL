from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.bridges import (
    build_amba_serial_bridge_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints import (
    build_apb_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics import (
    build_apb_address_fabric_vdut,
)
from protocol_model.protocols.amba.ahb.ahb_lite import build_ahb_lite_interface
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.axi.axi4_lite import build_axi4_lite_interface
from protocol_model.semantics import CanonicalEvent
from protocol_model.system import (
    InterfaceConnection,
    SystemAction,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address import (
    AddressSpace,
    RegisterRegion,
    RegisterSpec,
)
from protocol_model.virtual_dut.backend import CaptureBackend
from protocol_model.virtual_dut.boundary import InterfacePort, VirtualDut
from protocol_model.virtual_dut.fabric import AddressRoute


class AmbaBridgeChainTest(unittest.TestCase):
    """Exercise one address through two bridges and an APB decoder.

    This is deliberately a small, non-coherent network.  It checks that the
    current InterfaceProtocol attachments and VirtualDut backends can be composed
    by SystemProtocol without a pair-specific AXI-to-AHB-to-APB coordinator.
    """

    @staticmethod
    def _build_system() -> SystemProtocol:
        axi = build_axi4_lite_interface()
        ahb = build_ahb_lite_interface()
        apb = build_apb4_interface()

        initiator = VirtualDut(
            "initiator",
            {"axi": InterfacePort("axi", axi, "manager")},
            backend=CaptureBackend(),
            description="externally driven AXI4-Lite requester boundary",
        )
        axi_to_ahb = build_amba_serial_bridge_vdut(
            "axi_to_ahb",
            axi,
            ahb,
            (AddressRoute("peripheral_window", 0x1000, 0x3000, "m_ahb"),),
            ingress_port="s_axi",
            egress_port="m_ahb",
        )
        ahb_to_apb = build_amba_serial_bridge_vdut(
            "ahb_to_apb",
            ahb,
            apb,
            (AddressRoute("peripheral_window", 0x1000, 0x3000, "m_apb"),),
            ingress_port="s_ahb",
            egress_port="m_apb",
        )
        apb_fabric = build_apb_address_fabric_vdut(
            "apb_fabric",
            apb,
            (
                AddressRoute("control", 0x1000, 0x100, "control"),
                AddressRoute("status", 0x2000, 0x100, "status"),
            ),
        )
        control = build_apb_address_space_vdut(
            "control",
            apb,
            AddressSpace(
                (
                    RegisterRegion(
                        "control_registers",
                        (RegisterSpec("value", 0),),
                        base_address=0x1000,
                    ),
                )
            ),
        )
        status = build_apb_address_space_vdut(
            "status",
            apb,
            AddressSpace(
                (
                    RegisterRegion(
                        "status_registers",
                        (RegisterSpec("value", 0),),
                        base_address=0x2000,
                    ),
                )
            ),
        )

        links = (
            InterfaceConnection(
                "axi_link",
                axi,
                {
                    "manager": VirtualDutPortRef("initiator", "axi"),
                    "subordinate": VirtualDutPortRef("axi_to_ahb", "s_axi"),
                },
            ),
            InterfaceConnection(
                "ahb_link",
                ahb,
                {
                    "manager": VirtualDutPortRef("axi_to_ahb", "m_ahb"),
                    "subordinate": VirtualDutPortRef("ahb_to_apb", "s_ahb"),
                },
            ),
            InterfaceConnection(
                "apb_upstream",
                apb,
                {
                    "requester": VirtualDutPortRef("ahb_to_apb", "m_apb"),
                    "completer": VirtualDutPortRef("apb_fabric", "upstream"),
                },
            ),
            InterfaceConnection(
                "apb_control",
                apb,
                {
                    "requester": VirtualDutPortRef("apb_fabric", "control"),
                    "completer": VirtualDutPortRef("control", "apb"),
                },
            ),
            InterfaceConnection(
                "apb_status",
                apb,
                {
                    "requester": VirtualDutPortRef("apb_fabric", "status"),
                    "completer": VirtualDutPortRef("status", "apb"),
                },
            ),
        )
        duts = (
            initiator,
            axi_to_ahb,
            ahb_to_apb,
            apb_fabric,
            control,
            status,
        )
        return SystemProtocol(
            "axi_ahb_apb_peripherals",
            {dut.name: dut for dut in duts},
            {link.name: link for link in links},
        )

    @staticmethod
    def _emit(kind: str, payload: dict[str, object]) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef("initiator", "axi"),
            CanonicalEvent(kind, None, payload),
        )

    def _write(self, session, state, address: int, data: int):
        write_data = session.step(
            state,
            self._emit("W", {"data": data, "strb": 0b1111}),
        )
        self.assertIsNone(write_data.fault)
        completed = session.step(
            write_data.state,
            self._emit("AW", {"addr": address, "prot": 0}),
        )
        self.assertIsNone(completed.fault)
        self.assertEqual("B", completed.emissions[-1].event.kind)
        self.assertEqual("OKAY", completed.emissions[-1].event.payload["resp"])
        return completed

    def _read(self, session, state, address: int):
        completed = session.step(
            state,
            self._emit("AR", {"addr": address, "prot": 0}),
        )
        self.assertIsNone(completed.fault)
        self.assertEqual("R", completed.emissions[-1].event.kind)
        self.assertEqual("OKAY", completed.emissions[-1].event.payload["resp"])
        return completed

    def test_two_bridge_chain_routes_two_apb_endpoints(self) -> None:
        session = self._build_system().open_session()
        state = session.initial_state()

        control_write = self._write(session, state, 0x1000, 0x11223344)
        status_write = self._write(
            session, control_write.state, 0x2000, 0xAABBCCDD
        )
        control_read = self._read(session, status_write.state, 0x1000)
        status_read = self._read(session, control_read.state, 0x2000)

        self.assertEqual(
            0x11223344, control_read.emissions[-1].event.payload["data"]
        )
        self.assertEqual(
            0xAABBCCDD, status_read.emissions[-1].event.payload["data"]
        )
        self.assertIn(
            "apb_control", {event.connection for event in control_read.emissions}
        )
        self.assertNotIn(
            "apb_status", {event.connection for event in control_read.emissions}
        )
        self.assertIn(
            "apb_status", {event.connection for event in status_read.emissions}
        )
        self.assertNotIn(
            "apb_control", {event.connection for event in status_read.emissions}
        )
        self.assertTrue(session.is_quiescent(status_read.state))

    def test_fabric_decode_miss_returns_through_both_bridges_without_endpoint(
        self,
    ) -> None:
        session = self._build_system().open_session()

        missing = session.step(
            session.initial_state(),
            self._emit("AR", {"addr": 0x3000, "prot": 0}),
        )

        self.assertIsNone(missing.fault)
        self.assertEqual("R", missing.emissions[-1].event.kind)
        # APB exposes one error bit, so its decode error returns through AHB
        # ERROR as AXI SLVERR rather than retaining AXI's DECERR distinction.
        self.assertEqual("SLVERR", missing.emissions[-1].event.payload["resp"])
        self.assertEqual(
            (
                "axi_link",
                "ahb_link",
                "apb_upstream",
                "apb_upstream",
                "ahb_link",
                "axi_link",
            ),
            tuple(event.connection for event in missing.emissions),
        )
        self.assertFalse(
            {"apb_control", "apb_status"}
            & {event.connection for event in missing.emissions}
        )
        self.assertTrue(session.is_quiescent(missing.state))


if __name__ == "__main__":
    unittest.main()
