from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.fabrics import (
    build_axi4_lite_address_fabric_vdut,
    build_axi4_lite_address_crossbar_vdut,
)
from protocol_model.protocols.amba.axi.axi4_lite import (
    build_axi4_lite_interface,
)
from protocol_model.system import (
    AddressClaim,
    AddressMapContract,
    AddressRouterContract,
    AddressWindow,
    InterfaceConnection,
    SystemProtocol,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.backend import CaptureBackend
from protocol_model.virtual_dut.boundary import InterfacePort, VirtualDut
from protocol_model.virtual_dut.fabric import AddressRoute
from protocol_model.visualization import (
    AddressInterconnectFactSource,
    DiagramDetail,
    EvidenceBasis,
    ViewKind,
    address_interconnect_map_dot,
    interconnect_interface_map_dot,
    project_address_interconnect,
)


class AddressInterconnectVisualizationTest(unittest.TestCase):
    @staticmethod
    def _endpoint(name: str, protocol, role: str) -> VirtualDut:
        return VirtualDut(
            name,
            {"axi": InterfacePort("axi", protocol, role)},
            backend=CaptureBackend(),
        )

    @classmethod
    def _system(cls) -> SystemProtocol:
        protocol = build_axi4_lite_interface()
        routes = (
            AddressRoute(
                "target0",
                0x1000,
                0x100,
                "m_target0",
                output_base_address=0,
            ),
            AddressRoute(
                "target1",
                0x2000,
                0x100,
                "m_target1",
                output_base_address=0,
            ),
        )
        contract = AddressRouterContract(
            "main_crossbar",
            "crossbar",
            ("s_manager0", "s_manager1"),
            ("m_target0", "m_target1"),
            routes,
        )
        builder = SystemProtocolBuilder("two_by_two")
        for dut in (
            cls._endpoint("manager0", protocol, "manager"),
            cls._endpoint("manager1", protocol, "manager"),
            cls._endpoint("target0", protocol, "subordinate"),
            cls._endpoint("target1", protocol, "subordinate"),
        ):
            builder.add_dut(dut)
        builder.construct_address_router(
            contract,
            lambda declared: build_axi4_lite_address_crossbar_vdut(
                declared.router,
                protocol,
                declared.ingress_ports,
                declared.egress_ports,
                declared.routes,
                ingress_queue_capacity=2,
            ),
        )
        for name, manager, fabric_port in (
            ("manager0_bus", "manager0", "s_manager0"),
            ("manager1_bus", "manager1", "s_manager1"),
        ):
            builder.connect(
                name,
                protocol,
                {
                    "manager": VirtualDutPortRef(manager, "axi"),
                    "subordinate": VirtualDutPortRef(
                        "crossbar", fabric_port
                    ),
                },
            )
        for name, fabric_port, target in (
            ("target0_bus", "m_target0", "target0"),
            ("target1_bus", "m_target1", "target1"),
        ):
            builder.connect(
                name,
                protocol,
                {
                    "manager": VirtualDutPortRef("crossbar", fabric_port),
                    "subordinate": VirtualDutPortRef(target, "axi"),
                },
            )
            builder.add_address_claim(
                AddressClaim(
                    f"{target}_local",
                    VirtualDutPortRef(target, "axi"),
                    AddressWindow(0, 0x100),
                )
            )
        return builder.build()

    def test_resolved_two_by_two_projection_keeps_ports_and_routes(self) -> None:
        system = self._system()
        view = project_address_interconnect(
            system.elaborate(), interconnect="crossbar"
        )

        self.assertEqual(EvidenceBasis.RESOLVED, view.evidence_basis)
        self.assertEqual(
            AddressInterconnectFactSource
            .SYSTEM_CONTRACT_AND_BACKEND_PROJECTION,
            view.fact_source,
        )
        self.assertEqual(2, len(view.ingress))
        self.assertEqual(2, len(view.egress))
        self.assertEqual(
            ("port:crossbar.s_manager0", "port:crossbar.s_manager1"),
            tuple(item.ref for item in view.ingress),
        )
        self.assertEqual(
            ("subordinate", "subordinate"),
            tuple(item.fabric_role for item in view.ingress),
        )
        self.assertEqual(
            ("manager", "manager"),
            tuple(item.fabric_role for item in view.egress),
        )

        target0_route = view.egress[0].route_windows[0]
        self.assertEqual(0x1000, target0_route.input_base_address)
        self.assertEqual(0, target0_route.output_base_address)
        self.assertEqual(
            VirtualDutPortRef("target0", "axi"), target0_route.receiver
        )
        self.assertEqual("target0_local", target0_route.claim)

        descriptor = view.descriptor(detail=DiagramDetail.OVERVIEW)
        self.assertEqual(
            ViewKind.INTERCONNECT_INTERFACE_MAP, descriptor.view_kind
        )
        self.assertEqual(DiagramDetail.OVERVIEW, descriptor.detail)

    def test_renderer_separates_view_kind_from_detail(self) -> None:
        view = project_address_interconnect(
            self._system().elaborate(), interconnect="crossbar"
        )
        standard = interconnect_interface_map_dot(view)
        overview = interconnect_interface_map_dot(
            view, detail=DiagramDetail.OVERVIEW
        )
        diagnostic = interconnect_interface_map_dot(
            view, detail=DiagramDetail.DIAGNOSTIC
        )

        for dot in (standard, overview, diagnostic):
            self.assertIn("port:manager0.axi", dot)
            self.assertIn("connection:manager0_bus", dot)
        self.assertIn("2 ingress × 2 egress", standard)
        self.assertIn("2 × 2 interconnect", overview)
        self.assertIn("2 ingress × 2 egress", diagnostic)
        self.assertIn("s_manager0", standard)
        self.assertIn("0x1000..0x10ff → 0x0..0xff", standard)
        self.assertNotIn("manager0_bus\\n", standard)
        self.assertNotIn("request ↔ completion", standard)
        self.assertNotIn("ScheduledAddressCrossbarBackend", standard)
        self.assertNotIn("s_manager0", overview)
        self.assertIn("connection: manager0_bus", diagnostic)
        self.assertIn(
            "facts: system_contract_and_backend_projection", diagnostic
        )
        self.assertIn("internal lanes/crosspoints are not inferred", diagnostic)

    def test_backend_projection_supports_declared_view_without_contract(self) -> None:
        system = self._system()
        declaration = SystemProtocol(
            system.name,
            system.virtual_duts,
            system.connections,
        )
        view = project_address_interconnect(
            declaration, interconnect="crossbar"
        )

        self.assertEqual(EvidenceBasis.DECLARED, view.evidence_basis)
        self.assertEqual(
            AddressInterconnectFactSource.BACKEND_PROJECTION,
            view.fact_source,
        )
        self.assertIsNone(view.egress[0].route_windows[0].receiver)
        dot = address_interconnect_map_dot(
            declaration, interconnect="crossbar"
        )
        self.assertIn("address route boundary", dot)

    def test_same_projection_covers_one_by_two_address_fabric(self) -> None:
        protocol = build_axi4_lite_interface()
        routes = (
            AddressRoute("control", 0x1000, 0x100, "control"),
            AddressRoute("memory", 0x2000, 0x200, "memory"),
        )
        fabric = build_axi4_lite_address_fabric_vdut(
            "fabric", protocol, routes
        )
        manager = self._endpoint("manager", protocol, "manager")
        control = self._endpoint("control", protocol, "subordinate")
        memory = self._endpoint("memory", protocol, "subordinate")
        connections = (
            InterfaceConnection(
                "upstream",
                protocol,
                {
                    "manager": VirtualDutPortRef("manager", "axi"),
                    "subordinate": VirtualDutPortRef("fabric", "upstream"),
                },
            ),
            InterfaceConnection(
                "control_bus",
                protocol,
                {
                    "manager": VirtualDutPortRef("fabric", "control"),
                    "subordinate": VirtualDutPortRef("control", "axi"),
                },
            ),
            InterfaceConnection(
                "memory_bus",
                protocol,
                {
                    "manager": VirtualDutPortRef("fabric", "memory"),
                    "subordinate": VirtualDutPortRef("memory", "axi"),
                },
            ),
        )
        system = SystemProtocol(
            "one_by_two",
            {
                item.name: item
                for item in (manager, fabric, control, memory)
            },
            {item.name: item for item in connections},
        )

        view = project_address_interconnect(system, interconnect="fabric")
        self.assertEqual(1, len(view.ingress))
        self.assertEqual(2, len(view.egress))
        dot = interconnect_interface_map_dot(view)
        self.assertIn('COLSPAN="2"', dot)
        self.assertIn('PORT="ingress0" COLSPAN="2"', dot)
        self.assertIn('PORT="egress0" COLSPAN="1"', dot)

    def test_star_shape_without_explicit_router_facts_is_rejected(self) -> None:
        system = self._system()
        original = system.virtual_duts["crossbar"]
        opaque = VirtualDut(
            "crossbar",
            original.ports,
            backend=CaptureBackend(),
        )
        star = SystemProtocol(
            system.name,
            {
                name: opaque if name == "crossbar" else dut
                for name, dut in system.virtual_duts.items()
            },
            system.connections,
        )

        with self.assertRaisesRegex(
            ValueError, "no address-router contract or boundary projection"
        ):
            project_address_interconnect(star, interconnect="crossbar")

    def test_contract_and_backend_projection_must_match(self) -> None:
        system = self._system()
        current = system.address_map
        assert current is not None
        original = current.routers[0]
        changed_routes = tuple(
            AddressRoute(
                route.name,
                route.base_address + 0x4000,
                route.size_bytes,
                route.egress_port,
                output_base_address=route.output_base_address,
            )
            for route in original.routes
        )
        changed = AddressRouterContract(
            original.name,
            original.router,
            original.ingress_ports,
            original.egress_ports,
            changed_routes,
        )
        mismatch = SystemProtocol(
            system.name,
            system.virtual_duts,
            system.connections,
            address_map=AddressMapContract(current.claims, (changed,)),
        )

        with self.assertRaisesRegex(ValueError, "contract and backend disagree"):
            project_address_interconnect(mismatch, interconnect="crossbar")


if __name__ == "__main__":
    unittest.main()
