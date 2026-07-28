"""AXI4-Lite binding for the scheduled address crossbar VirtualDut."""

from __future__ import annotations

from typing import Mapping

from protocol_model.interface import InterfaceProtocol
from protocol_model.semantics import ResourceExhaustionPolicy
from protocol_model.protocols.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.attachments.base import InterfaceAttachment
from protocol_model.virtual_dut.binding.port import InterfaceAttachmentBinding
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.fabric.route import AddressRoute
from protocol_model.virtual_dut.recipes.address_crossbar import (
    build_scheduled_address_crossbar_vdut,
)

from protocol_model.integrations.attachments.amba.axi.axi4_lite import (
    Axi4LiteCompleterAttachment,
    Axi4LiteRequesterAttachment,
)


def _binding(
    name: str,
    protocol: InterfaceProtocol,
    attachment: InterfaceAttachment,
    capability: object | None,
) -> InterfaceAttachmentBinding:
    return InterfaceAttachmentBinding(
        InterfacePort(name, protocol, attachment.role, capability=capability),
        attachment,
    )


def _port_names(names: tuple[str, ...], *, subject: str) -> tuple[str, ...]:
    normalized = tuple(names)
    if not normalized:
        raise ValueError(f"AXI4-Lite crossbar requires {subject} ports")
    if any(not isinstance(name, str) or not name for name in normalized):
        raise ValueError(f"AXI4-Lite crossbar {subject} names must be non-empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"AXI4-Lite crossbar {subject} names must be unique")
    return normalized


def build_axi4_lite_address_crossbar_vdut(
    name: str,
    protocol: InterfaceProtocol,
    ingress_ports: tuple[str, ...],
    egress_ports: tuple[str, ...],
    routes: tuple[AddressRoute, ...],
    *,
    ingress_queue_capacity: int,
    exhaustion_policy: ResourceExhaustionPolicy | str = (
        ResourceExhaustionPolicy.BLOCK
    ),
    capabilities: Mapping[str, object] | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Construct a finite queued, round-robin AXI4-Lite N×M crossbar."""

    ingress_names = _port_names(ingress_ports, subject="ingress")
    egress_names = _port_names(egress_ports, subject="egress")
    if protocol.interface_family != AXI4_LITE_FAMILY:
        raise ValueError(
            "AXI4-Lite crossbar requires an AXI4-Lite InterfaceProtocol family"
        )
    overlap = set(ingress_names).intersection(egress_names)
    if overlap:
        raise ValueError(
            "AXI4-Lite crossbar ingress and egress names overlap: "
            f"{sorted(overlap)!r}"
        )

    address_limit = 1 << int(protocol.parameters["address_width"])
    for route in routes:
        if route.limit_address > address_limit:
            raise ValueError(
                f"route {route.name!r} input window exceeds AXI4-Lite "
                "address width"
            )
        output_base = (
            route.base_address
            if route.output_base_address is None
            else route.output_base_address
        )
        if output_base + route.size_bytes > address_limit:
            raise ValueError(
                f"route {route.name!r} output window exceeds AXI4-Lite "
                "address width"
            )

    capability_by_port = dict(capabilities or {})
    port_names = set(ingress_names).union(egress_names)
    unknown_capabilities = set(capability_by_port) - port_names
    if unknown_capabilities:
        raise ValueError(
            "capabilities reference unknown crossbar ports: "
            f"{sorted(unknown_capabilities)!r}"
        )

    ingress_bindings = {
        port: _binding(
            port,
            protocol,
            Axi4LiteCompleterAttachment(protocol, byte_order=byte_order),
            capability_by_port.get(port),
        )
        for port in ingress_names
    }
    egress_bindings = {
        port: _binding(
            port,
            protocol,
            Axi4LiteRequesterAttachment(protocol, byte_order=byte_order),
            capability_by_port.get(port),
        )
        for port in egress_names
    }
    return build_scheduled_address_crossbar_vdut(
        name,
        ingress_bindings,
        egress_bindings,
        routes,
        ingress_queue_capacity=ingress_queue_capacity,
        exhaustion_policy=exhaustion_policy,
        description=(
            "scheduled AXI4-Lite address crossbar "
            "(per-ingress FIFO + per-egress round-robin)"
        ),
    )


__all__ = ["build_axi4_lite_address_crossbar_vdut"]
