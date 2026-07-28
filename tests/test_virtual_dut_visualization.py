from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints.empty import (
    build_apb_idle_source_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.memory_copy import (
    build_amba_serialized_memory_copy_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.queued import (
    build_amba_queued_address_responder_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.sensor_fifo import (
    build_amba_sensor_fifo_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics import (
    build_axi4_lite_address_fabric_vdut,
    build_axi4_lite_address_crossbar_vdut,
)
from protocol_model.integrations.recipes.amba.bridges.serial_address import (
    build_amba_serial_address_bridge_vdut,
)
from protocol_model.integrations.recipes.control.interrupt import (
    build_edge_interrupt_controller_vdut,
    build_edge_interrupt_target_vdut,
)
from protocol_model.protocols.control.interrupt import (
    build_interrupt_notification_interface,
)
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.axi.axi4_lite import build_axi4_lite_interface
from protocol_model.system import (
    InterfaceConnection,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address import AddressSpace, MemoryRegion
from protocol_model.virtual_dut.backend.queued_address import (
    constant_address_delay,
)
from protocol_model.virtual_dut.backend.memory_copy import MemoryCopyDescriptor
from protocol_model.virtual_dut.backend.sensor_fifo import (
    SensorFifoConfig,
    incrementing_sample_policy,
)
from protocol_model.virtual_dut.backend.simple import CaptureBackend
from protocol_model.virtual_dut.boundary import InterfacePort, VirtualDut
from protocol_model.virtual_dut.fabric import AddressRoute
from protocol_model.visualization import (
    DiagramDetail,
    DutRealizationView,
    expanded_system_topology_dot,
    project_virtual_dut,
    system_bus_strip_dot,
    virtual_dut_structure_dot,
)


class VirtualDutVisualizationTest(unittest.TestCase):
    @staticmethod
    def _system() -> SystemProtocol:
        protocol = build_apb4_interface()
        source = build_apb_idle_source_vdut("source", protocol)
        target = build_amba_queued_address_responder_vdut(
            "target",
            protocol,
            AddressSpace(
                (MemoryRegion("ram", 0x100, base_address=0x1000),)
            ),
            capacity=2,
            delay_policy=constant_address_delay(2),
            port_name="apb",
        )
        return SystemProtocol.from_interface(
            "queued_apb",
            connection_name="bus",
            protocol=protocol,
            endpoints={
                "requester": (source, "apb"),
                "completer": (target, "apb"),
            },
        )

    def test_queued_responder_projects_visible_constructed_parts(self) -> None:
        target = self._system().virtual_duts["target"]
        structure = project_virtual_dut(target)

        self.assertEqual(DutRealizationView.CONSTRUCTED, structure.realization)
        self.assertEqual(
            {
                "port",
                "attachment",
                "storage",
                "control",
                "behavior",
            },
            {component.kind for component in structure.components},
        )
        labels = "\n".join(
            component.label for component in structure.components
        )
        self.assertIn("address completer", labels)
        self.assertIn("complete-request FIFO", labels)
        self.assertIn("address access handler", labels)

        port = next(
            component
            for component in structure.components
            if component.kind == "port"
        )
        attachment = next(
            component
            for component in structure.components
            if component.kind == "attachment"
        )
        self.assertEqual("apb4 · completer", port.attributes["interface"])
        self.assertEqual("READ, WRITE", attachment.attributes["in"])
        self.assertEqual(
            "READ_RESPONSE,\nWRITE_RESPONSE",
            attachment.attributes["out"],
        )
        self.assertEqual(
            "ApbCompleterAttachment",
            attachment.attributes["implementation"],
        )
        handler = next(
            component
            for component in structure.components
            if component.kind == "behavior"
        )
        self.assertEqual("AddressSpace", handler.attributes["implementation"])

        dot = virtual_dut_structure_dot(structure)
        self.assertIn("rankdir=LR", dot)
        self.assertIn("cluster_virtual_dut", dot)
        self.assertIn("VirtualDut boundary", dot)
        self.assertIn("DELAYING → READY → service", dot)
        self.assertNotIn("style=dashed, constraint=false", dot)
        self.assertNotIn("operation: AddressRead", dot)
        self.assertNotIn("ApbCompleterAttachment", dot)
        self.assertNotIn("implementation:", dot)

        diagnostic = virtual_dut_structure_dot(
            structure, detail=DiagramDetail.DIAGNOSTIC
        )
        self.assertIn("ApbCompleterAttachment", diagnostic)
        self.assertIn('label="completion"', diagnostic)

    def test_detail_policy_is_render_only_and_preserves_custom_title(self) -> None:
        target = self._system().virtual_duts["target"]
        structure = project_virtual_dut(target)
        components = structure.components
        flows = structure.flows

        standard = virtual_dut_structure_dot(structure)
        explicit_standard = virtual_dut_structure_dot(
            structure, detail=DiagramDetail.STANDARD
        )
        overview = virtual_dut_structure_dot(
            structure,
            title="Queued target at a glance",
            detail=DiagramDetail.OVERVIEW,
        )

        self.assertEqual(standard, explicit_standard)
        self.assertIn('label="Queued target at a glance"', overview)
        self.assertEqual(components, structure.components)
        self.assertEqual(flows, structure.flows)

    def test_expanded_topology_keeps_scenario_outside_dut_clusters(self) -> None:
        system = self._system()
        dot = expanded_system_topology_dot(
            system,
            external_sources={
                VirtualDutPortRef("source", "apb"):
                    "RandomTrafficController\nscenario-owned RNG",
            },
        )

        self.assertIn("RandomTrafficController", dot)
        self.assertIn("scenario drive", dot)
        self.assertIn('label="apb4\\napb ↔ apb"', dot)
        self.assertNotIn("shape=diamond", dot)
        self.assertIn("address completer", dot)
        self.assertNotIn("ApbCompleterAttachment", dot)
        self.assertIn("complete-request FIFO", dot)

    def test_bus_strip_folds_an_explicit_single_ingress_fabric(self) -> None:
        protocol = build_axi4_lite_interface()
        fabric = build_axi4_lite_address_fabric_vdut(
            "fabric",
            protocol,
            (
                AddressRoute("control", 0x1000, 0x100, "control"),
                AddressRoute("memory", 0x2000, 0x200, "memory"),
            ),
        )
        manager = VirtualDut(
            "manager",
            {"axi": InterfacePort("axi", protocol, "manager")},
            backend=CaptureBackend(),
        )
        control = VirtualDut(
            "control",
            {"axi": InterfacePort("axi", protocol, "subordinate")},
            backend=CaptureBackend(),
        )
        memory = VirtualDut(
            "memory",
            {"axi": InterfacePort("axi", protocol, "subordinate")},
            backend=CaptureBackend(),
        )
        system = SystemProtocol(
            "one_manager_bus",
            {
                item.name: item
                for item in (manager, fabric, control, memory)
            },
            {
                connection.name: connection
                for connection in (
                    InterfaceConnection(
                        "upstream",
                        protocol,
                        {
                            "manager": VirtualDutPortRef("manager", "axi"),
                            "subordinate": VirtualDutPortRef(
                                "fabric", "upstream"
                            ),
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
            },
        )

        dot = system_bus_strip_dot(system, fabric="fabric")

        self.assertIn("folded bus-strip view", dot)
        self.assertIn("decoder + response mux", dot)
        self.assertIn("0x1000..0x10ff", dot)
        self.assertIn("0x2000..0x21ff", dot)
        self.assertNotIn("canonical topology remains explicit star", dot)

    def test_bridge_projection_separates_codecs_transform_and_driver(self) -> None:
        bridge = build_amba_serial_address_bridge_vdut(
            "bridge",
            build_axi4_lite_interface(),
            build_apb4_interface(),
            (AddressRoute("peripheral", 0x1000, 0x100, "m_apb"),),
            ingress_port="s_axi",
            egress_port="m_apb",
        )

        structure = project_virtual_dut(bridge)
        labels = "\n".join(
            component.label for component in structure.components
        )
        kinds = {component.kind for component in structure.components}

        self.assertEqual(DutRealizationView.CONSTRUCTED, structure.realization)
        self.assertIn("address completer", labels)
        self.assertIn("address requester", labels)
        self.assertIn("typed translation", labels)
        self.assertIn("serial scheduler", labels)
        self.assertIn("child owner table", labels)
        self.assertTrue({"transform", "control", "correlation"} <= kinds)

        by_kind = {
            component.kind: component
            for component in structure.components
            if component.kind in {"adapter", "transform"}
        }
        self.assertEqual(
            "AddressRead | AddressWrite\n→ AccessResult",
            by_kind["adapter"].attributes["operation"],
        )
        self.assertIn(
            "address route", by_kind["transform"].attributes["pipeline"]
        )
        attachments = {
            component.attributes.get("side"): component
            for component in structure.components
            if component.kind == "attachment"
        }
        self.assertEqual(
            "axi4_lite · subordinate",
            attachments["ingress"].attributes["binding"],
        )
        self.assertEqual(
            "apb4 · requester",
            attachments["egress"].attributes["binding"],
        )
        self.assertEqual(
            "Axi4LiteCompleterAttachment",
            attachments["ingress"].attributes["implementation"],
        )
        self.assertEqual(
            "ApbRequesterAttachment",
            attachments["egress"].attributes["implementation"],
        )

        dot = virtual_dut_structure_dot(structure)
        self.assertIn("rankdir=LR", dot)
        self.assertNotIn("style=dashed, constraint=false", dot)
        diagnostic = virtual_dut_structure_dot(
            structure, detail=DiagramDetail.DIAGNOSTIC
        )
        self.assertIn("style=dashed, constraint=false", diagnostic)
        egress_port = structure.port_components["m_apb"]
        egress_attachment = next(
            component.id
            for component in structure.components
            if component.kind in {"attachment", "adapter"}
            and component.attributes.get("side") == "egress"
        )
        self.assertIn(
            (egress_attachment, egress_port, "solid"),
            {
                (flow.source, flow.destination, flow.style)
                for flow in structure.flows
            },
        )

    def test_scheduled_crossbar_projects_shared_and_per_port_resources(self) -> None:
        crossbar = build_axi4_lite_address_crossbar_vdut(
            "crossbar",
            build_axi4_lite_interface(),
            ("s_manager0", "s_manager1"),
            ("m_target0", "m_target1"),
            (
                AddressRoute(
                    "target0", 0x1000, 0x100, "m_target0",
                    output_base_address=0,
                ),
                AddressRoute(
                    "target1", 0x2000, 0x100, "m_target1",
                    output_base_address=0,
                ),
            ),
            ingress_queue_capacity=3,
        )

        structure = project_virtual_dut(crossbar)
        self.assertEqual(DutRealizationView.CONSTRUCTED, structure.realization)

        by_kind: dict[str, list] = {}
        for component in structure.components:
            by_kind.setdefault(component.kind, []).append(component)
        self.assertEqual(4, len(by_kind["port"]))
        self.assertEqual(4, len(by_kind["attachment"]))
        self.assertEqual(2, len(by_kind["storage"]))
        self.assertEqual(2, len(by_kind["control"]))
        self.assertEqual(1, len(by_kind["routing"]))
        self.assertEqual(1, len(by_kind["correlation"]))

        fifos = {
            component.attributes["ingress"]: component
            for component in by_kind["storage"]
        }
        self.assertEqual({"s_manager0", "s_manager1"}, set(fifos))
        self.assertTrue(
            all(component.attributes["capacity"] == 3 for component in fifos.values())
        )
        arbiters = {
            component.attributes["egress"]: component
            for component in by_kind["control"]
        }
        self.assertEqual({"m_target0", "m_target1"}, set(arbiters))
        self.assertTrue(
            all(
                component.attributes["policy"] == "round-robin"
                for component in arbiters.values()
            )
        )

        route = by_kind["routing"][0]
        owner = by_kind["correlation"][0]
        self.assertIn("m_target0", route.attributes["routes"])
        self.assertIn("m_target1", route.attributes["routes"])
        self.assertEqual("request_id", owner.attributes["key"])
        self.assertEqual(2, owner.attributes["max active"])

        ingress_attachments = {
            component.id
            for component in by_kind["attachment"]
            if component.attributes.get("side") == "ingress"
        }
        egress_attachments = {
            component.id
            for component in by_kind["attachment"]
            if component.attributes.get("side") == "egress"
        }
        self.assertEqual(2, len(ingress_attachments))
        self.assertEqual(2, len(egress_attachments))

        ports_by_side = {
            side: {
                component.id
                for component in by_kind["port"]
                if component.attributes.get("side") == side
            }
            for side in ("ingress", "egress")
        }
        self.assertEqual(2, len(ports_by_side["ingress"]))
        self.assertEqual(2, len(ports_by_side["egress"]))

        flow_edges = {
            (flow.source, flow.destination, flow.style)
            for flow in structure.flows
        }
        for component in fifos.values():
            self.assertTrue(
                any(
                    source in ingress_attachments
                    and destination == route.id
                    and style == "solid"
                    for source, destination, style in flow_edges
                )
            )
            self.assertIn((route.id, component.id, "solid"), flow_edges)
        for component in arbiters.values():
            self.assertTrue(
                all(
                    (fifo.id, component.id, "solid") in flow_edges
                    for fifo in fifos.values()
                )
            )
            self.assertIn((component.id, owner.id, "dotted"), flow_edges)
            self.assertIn((owner.id, component.id, "dotted"), flow_edges)
        self.assertTrue(
            all(
                any(
                    source in {component.id for component in arbiters.values()}
                    and destination == attachment
                    and style == "solid"
                    for source, destination, style in flow_edges
                )
                and (attachment, owner.id, "dashed") in flow_edges
                for attachment in egress_attachments
            )
        )
        self.assertTrue(
            all(
                (owner.id, attachment, "dashed") in flow_edges
                for attachment in ingress_attachments
            )
        )

        dot = virtual_dut_structure_dot(structure)
        self.assertIn("rankdir=LR", dot)
        self.assertIn("shared address decoder / remap", dot)
        self.assertIn("round-robin arbiter / cursor", dot)
        self.assertIn("active owner / return table", dot)
        self.assertNotIn("style=dotted, constraint=false", dot)
        self.assertNotIn("style=dashed, constraint=false", dot)
        self.assertNotIn("Axi4LiteCompleterAttachment", dot)
        self.assertNotIn("implementation:", dot)
        self.assertNotIn("in: AR, AW, W", dot)
        self.assertNotIn("side: ingress", dot)
        self.assertIn("{ rank=source; component_0; component_1; }", dot)
        self.assertIn("{ rank=sink; component_2; component_3; }", dot)
        self.assertIn("{ rank=same; component_4; component_5; }", dot)
        self.assertIn("{ rank=same; component_6; component_7; }", dot)
        self.assertIn(
            "component_4 -> component_9 [style=invis", dot
        )
        self.assertIn(
            "component_9 -> component_6 [style=invis", dot
        )

        overview = virtual_dut_structure_dot(
            structure, detail=DiagramDetail.OVERVIEW
        )
        self.assertIn('label="crossbar · VirtualDut"', overview)
        self.assertIn("capacity: 3", overview)
        self.assertNotIn("routes:", overview)
        self.assertNotIn('label="request"', overview)
        self.assertNotIn("style=dotted", overview)

        diagnostic = virtual_dut_structure_dot(
            structure, detail=DiagramDetail.DIAGNOSTIC
        )
        self.assertIn("ScheduledAddressCrossbarBackend", diagnostic)
        self.assertIn("Axi4LiteCompleterAttachment", diagnostic)
        self.assertIn("implementation:", diagnostic)
        self.assertIn("in: AR, AW, W", diagnostic)
        self.assertIn("side: ingress", diagnostic)
        self.assertIn("style=dotted, constraint=false", diagnostic)

    def test_idle_source_exposes_empty_mode_without_scenario_driver(self) -> None:
        source = build_apb_idle_source_vdut("source", build_apb4_interface())
        structure = project_virtual_dut(source)

        attachment = next(
            component
            for component in structure.components
            if component.kind == "attachment"
        )
        backend = next(
            component
            for component in structure.components
            if component.kind == "behavior"
        )
        self.assertEqual("idle_source", attachment.attributes["mode"])
        self.assertEqual("none (idle)", attachment.attributes["operation"])
        self.assertEqual("no autonomous behavior", backend.label)

        dot = virtual_dut_structure_dot(structure)
        self.assertNotIn("no autonomous emission", dot)
        self.assertNotIn("style=dotted, constraint=false", dot)
        self.assertNotIn("RandomTrafficController", dot)

        diagnostic = virtual_dut_structure_dot(
            structure, detail=DiagramDetail.DIAGNOSTIC
        )
        self.assertIn("no autonomous emission", diagnostic)
        self.assertIn("style=dotted, constraint=false", diagnostic)

    def test_capture_boundary_is_receive_only(self) -> None:
        protocol = build_axi4_lite_interface()
        source = VirtualDut(
            "source",
            {"axi": InterfacePort("axi", protocol, "manager")},
            backend=CaptureBackend(),
        )
        structure = project_virtual_dut(source)

        backend = next(
            component
            for component in structure.components
            if component.kind == "behavior"
        )
        self.assertEqual("received-event capture", backend.label)
        self.assertEqual("none", backend.attributes["emission"])
        self.assertEqual(1, len(structure.flows))
        self.assertEqual(
            (structure.port_components["axi"], "backend", "solid"),
            (
                structure.flows[0].source,
                structure.flows[0].destination,
                structure.flows[0].style,
            ),
        )

    def test_sensor_and_dma_project_stateful_construction_parts(self) -> None:
        protocol = build_axi4_lite_interface()
        sensor = build_amba_sensor_fifo_vdut(
            "sensor",
            protocol,
            SensorFifoConfig(0, 4, 3),
            incrementing_sample_policy(start=0x100),
            port_name="axi",
        )
        dma = build_amba_serialized_memory_copy_vdut(
            "dma",
            protocol,
            MemoryCopyDescriptor(0x1000, 0x2000, 12, 4, source_stride=0),
            port_name="axi",
        )

        sensor_view = project_virtual_dut(sensor)
        dma_view = project_virtual_dut(dma)

        self.assertEqual(DutRealizationView.CONSTRUCTED, sensor_view.realization)
        self.assertEqual(DutRealizationView.CONSTRUCTED, dma_view.realization)
        sensor_labels = "\n".join(
            component.label for component in sensor_view.components
        )
        dma_labels = "\n".join(
            component.label for component in dma_view.components
        )
        self.assertIn("sensor sample FIFO", sensor_labels)
        self.assertIn("read-to-pop data register", sensor_labels)
        self.assertIn("serialized copy FSM", dma_labels)
        self.assertIn("one-beat read buffer", dma_labels)
        self.assertNotIn("opaque", sensor_labels + dma_labels)

    def test_interrupt_projectors_show_queue_delivery_and_eoi(self) -> None:
        protocol = build_interrupt_notification_interface()
        controller = build_edge_interrupt_controller_vdut(
            "interrupt_controller",
            protocol,
            ingress_ports=("sensor_irq", "dma_irq"),
            capacity=4,
        )
        target = build_edge_interrupt_target_vdut("cpu", protocol)

        controller_view = project_virtual_dut(controller)
        target_view = project_virtual_dut(target)
        controller_labels = "\n".join(
            component.label for component in controller_view.components
        )
        target_labels = "\n".join(
            component.label for component in target_view.components
        )

        self.assertIn("retained edge notifications", controller_labels)
        self.assertIn("priority / arrival-order select", controller_labels)
        self.assertIn("one active target delivery", controller_labels)
        self.assertIn("single active interrupt", target_labels)
        self.assertIn("explicit EOI service", target_labels)


if __name__ == "__main__":
    unittest.main()
