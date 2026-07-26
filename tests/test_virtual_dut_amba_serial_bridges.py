from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.bridges.serial_address import (
    build_amba_serial_address_bridge_vdut,
)
from protocol_model.integrations.recipes.amba.bridges.serial import (
    build_amba_serial_bridge_vdut,
)
from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4BurstAssemblyProfile,
)
from protocol_model.integrations.recipes.amba.endpoints.ahb import (
    build_ahb_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.apb import (
    build_apb_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.axi4 import (
    build_axi4_address_space_vdut,
)
from protocol_model.protocols.amba.ahb.ahb_lite import (
    AhbLiteConfig,
    build_ahb_lite_interface,
)
from protocol_model.protocols.amba.ahb.ahb5 import build_ahb5_interface
from protocol_model.protocols.amba.apb.apb3 import build_apb3_interface
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.apb.apb5 import build_apb5_interface
from protocol_model.protocols.amba.axi.axi4 import Axi4Config, build_axi4_interface
from protocol_model.protocols.amba.axi.axi4_lite import (
    Axi4LiteConfig,
    build_axi4_lite_interface,
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


class AmbaSerialAddressBridgeTest(unittest.TestCase):
    @staticmethod
    def _manager(name: str, port: str, protocol, role: str) -> VirtualDut:
        return VirtualDut(
            name,
            {port: InterfacePort(port, protocol, role)},
            backend=CaptureBackend(),
        )

    @staticmethod
    def _action(
        dut: str, port: str, kind: str, payload: dict[str, object], key=None
    ) -> SystemAction:
        return SystemAction(
            VirtualDutPortRef(dut, port),
            CanonicalEvent(kind, key, payload),
        )

    def test_axi4_lite_to_ahb_lite_maps_protection_and_returns_data(self) -> None:
        axi = build_axi4_lite_interface()
        ahb = build_ahb_lite_interface()
        manager = self._manager("manager", "axi", axi, "manager")
        bridge = build_amba_serial_address_bridge_vdut(
            "bridge",
            axi,
            ahb,
            (AddressRoute("ram", 0x1000, 0x100, "m_ahb"),),
            ingress_port="s_axi",
            egress_port="m_ahb",
        )
        memory = build_ahb_address_space_vdut(
            "memory",
            ahb,
            AddressSpace((MemoryRegion("ram", 0x100, base_address=0x1000),)),
        )
        system = SystemProtocol(
            "axi_lite_to_ahb",
            {item.name: item for item in (manager, bridge, memory)},
            {
                "axi": InterfaceConnection(
                    "axi",
                    axi,
                    {
                        "manager": VirtualDutPortRef("manager", "axi"),
                        "subordinate": VirtualDutPortRef("bridge", "s_axi"),
                    },
                ),
                "ahb": InterfaceConnection(
                    "ahb",
                    ahb,
                    {
                        "manager": VirtualDutPortRef("bridge", "m_ahb"),
                        "subordinate": VirtualDutPortRef("memory", "ahb"),
                    },
                ),
            },
        )
        session = system.open_session()
        state = session.initial_state()

        data = session.step(
            state,
            self._action(
                "manager", "axi", "W", {"data": 0x11223344, "strb": 0b1111}
            ),
        )
        written = session.step(
            data.state,
            self._action(
                "manager", "axi", "AW", {"addr": 0x1000, "prot": 0b101}
            ),
        )
        read = session.step(
            written.state,
            self._action(
                "manager", "axi", "AR", {"addr": 0x1000, "prot": 0b001}
            ),
        )

        for transition in (data, written, read):
            self.assertIsNone(transition.fault)
        ahb_write = next(
            event.event
            for event in written.emissions
            if event.connection == "ahb" and event.event.kind == "WRITE"
        )
        self.assertEqual(0b0010, ahb_write.payload["prot"])
        self.assertEqual("B", written.emissions[-1].event.kind)
        self.assertEqual(0x11223344, read.emissions[-1].event.payload["data"])
        self.assertTrue(session.is_quiescent(read.state))

    def test_ahb_lite_to_apb4_maps_protection_and_rejects_narrow_read_locally(
        self,
    ) -> None:
        ahb = build_ahb_lite_interface()
        apb = build_apb4_interface()
        manager = self._manager("manager", "ahb", ahb, "manager")
        bridge = build_amba_serial_address_bridge_vdut(
            "bridge",
            ahb,
            apb,
            (AddressRoute("peripheral", 0x2000, 0x100, "m_apb"),),
            ingress_port="s_ahb",
            egress_port="m_apb",
        )
        peripheral = build_apb_address_space_vdut(
            "peripheral",
            apb,
            AddressSpace((MemoryRegion("ram", 0x100, base_address=0x2000),)),
        )
        system = SystemProtocol(
            "ahb_to_apb",
            {item.name: item for item in (manager, bridge, peripheral)},
            {
                "ahb": InterfaceConnection(
                    "ahb",
                    ahb,
                    {
                        "manager": VirtualDutPortRef("manager", "ahb"),
                        "subordinate": VirtualDutPortRef("bridge", "s_ahb"),
                    },
                ),
                "apb": InterfaceConnection(
                    "apb",
                    apb,
                    {
                        "requester": VirtualDutPortRef("bridge", "m_apb"),
                        "completer": VirtualDutPortRef("peripheral", "apb"),
                    },
                ),
            },
        )
        session = system.open_session()
        state = session.initial_state()
        common = {
            "addr": 0x2000,
            "burst": "SINGLE",
            "trans": "NONSEQ",
            "prot": 0b0011,
            "lock": False,
        }

        full = session.step(
            state,
            self._action(
                "manager", "ahb", "READ", {**common, "size": 2}
            ),
        )
        narrow = session.step(
            full.state,
            self._action(
                "manager", "ahb", "READ", {**common, "size": 1}
            ),
        )

        self.assertIsNone(full.fault)
        apb_read = next(
            event.event
            for event in full.emissions
            if event.connection == "apb" and event.event.kind == "READ"
        )
        self.assertEqual(0b001, apb_read.payload["prot"])
        self.assertIsNone(narrow.fault)
        self.assertEqual("ERROR", narrow.emissions[-1].event.payload["resp"])
        self.assertFalse(any(event.connection == "apb" for event in narrow.emissions))
        self.assertTrue(session.is_quiescent(narrow.state))

    def test_axi4_lite_to_axi4_reuses_the_same_backend_and_plan_shape(self) -> None:
        lite = build_axi4_lite_interface()
        axi = build_axi4_interface(Axi4Config(data_width=32, id_width=2))
        manager = self._manager("manager", "lite", lite, "manager")
        bridge = build_amba_serial_address_bridge_vdut(
            "bridge",
            lite,
            axi,
            (AddressRoute("memory", 0x3000, 0x100, "m_axi"),),
            ingress_port="s_lite",
            egress_port="m_axi",
            axi_wire_id=2,
        )
        memory = build_axi4_address_space_vdut(
            "memory",
            axi,
            AddressSpace((MemoryRegion("ram", 0x100, base_address=0x3000),)),
        )
        system = SystemProtocol(
            "axi_lite_to_axi",
            {item.name: item for item in (manager, bridge, memory)},
            {
                "lite": InterfaceConnection(
                    "lite",
                    lite,
                    {
                        "manager": VirtualDutPortRef("manager", "lite"),
                        "subordinate": VirtualDutPortRef("bridge", "s_lite"),
                    },
                ),
                "axi": InterfaceConnection(
                    "axi",
                    axi,
                    {
                        "manager": VirtualDutPortRef("bridge", "m_axi"),
                        "subordinate": VirtualDutPortRef("memory", "axi"),
                    },
                ),
            },
        )
        session = system.open_session()
        transition = session.step(
            session.initial_state(),
            self._action(
                "manager", "lite", "AR", {"addr": 0x3000, "prot": 0b010}
            ),
        )

        self.assertIsNone(transition.fault)
        axi_request = next(
            event.event
            for event in transition.emissions
            if event.connection == "axi" and event.event.kind == "AR"
        )
        self.assertEqual(2, axi_request.key)
        self.assertEqual(0b010, axi_request.payload["prot"])
        self.assertEqual("R", transition.emissions[-1].event.kind)
        self.assertTrue(session.is_quiescent(transition.state))

    def test_route_remap_must_fit_both_interface_address_widths(self) -> None:
        axi = build_axi4_lite_interface(Axi4LiteConfig(address_width=16))
        ahb = build_ahb_lite_interface(AhbLiteConfig(address_width=12))

        with self.assertRaisesRegex(ValueError, "egress address width"):
            build_amba_serial_address_bridge_vdut(
                "bridge",
                axi,
                ahb,
                (
                    AddressRoute(
                        "window",
                        0x1000,
                        0x100,
                        "m_ahb",
                        output_base_address=0xF80,
                    ),
                ),
                ingress_port="s_axi",
                egress_port="m_ahb",
            )

    def test_one_composition_root_builds_intra_and_inter_family_profiles(
        self,
    ) -> None:
        profiles = (
            ("axi_lite_to_apb3", build_axi4_lite_interface(), build_apb3_interface()),
            ("axi_lite_to_ahb5", build_axi4_lite_interface(), build_ahb5_interface()),
            ("ahb_lite_to_axi_lite", build_ahb_lite_interface(), build_axi4_lite_interface()),
            ("ahb5_to_apb4", build_ahb5_interface(), build_apb4_interface()),
            ("apb3_to_apb5", build_apb3_interface(), build_apb5_interface()),
            ("apb4_to_ahb_lite", build_apb4_interface(), build_ahb_lite_interface()),
        )

        for name, ingress, egress in profiles:
            with self.subTest(name=name):
                bridge = build_amba_serial_address_bridge_vdut(
                    name,
                    ingress,
                    egress,
                    (AddressRoute("window", 0x1000, 0x100, "out"),),
                    ingress_port="in",
                    egress_port="out",
                )

                self.assertIs(ingress, bridge.port("in").protocol)
                self.assertIs(egress, bridge.port("out").protocol)
                self.assertEqual(
                    "AddressOperationTranslationBridgeBackend",
                    bridge.realization_name,
                )

    def test_unified_serial_builder_closes_current_amba_address_variants(self) -> None:
        protocols = (
            build_axi4_interface(Axi4Config(data_width=32)),
            build_axi4_lite_interface(),
            build_ahb_lite_interface(),
            build_ahb5_interface(),
            build_apb3_interface(),
            build_apb4_interface(),
            build_apb5_interface(),
        )

        for ingress in protocols:
            for egress in protocols:
                with self.subTest(
                    ingress=ingress.name, egress=egress.name
                ):
                    bridge = build_amba_serial_bridge_vdut(
                        "bridge",
                        ingress,
                        egress,
                        (AddressRoute("window", 0, 0x100, "out"),),
                        ingress_port="in",
                        egress_port="out",
                    )
                    self.assertEqual(
                        "AddressOperationTranslationBridgeBackend",
                        bridge.realization_name,
                    )

        with self.assertRaisesRegex(ValueError, "only meaningful"):
            build_amba_serial_bridge_vdut(
                "bridge",
                build_axi4_lite_interface(),
                build_apb4_interface(),
                (AddressRoute("window", 0, 0x100, "out"),),
                ingress_port="in",
                egress_port="out",
                assembly_profile=Axi4BurstAssemblyProfile(),
            )


if __name__ == "__main__":
    unittest.main()
