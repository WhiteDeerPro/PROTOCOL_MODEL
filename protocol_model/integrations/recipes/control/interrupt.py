"""Concrete edge-interrupt interface integration recipes."""

from __future__ import annotations

from collections.abc import Iterable

from protocol_model.integrations.attachments.control.interrupt import (
    InterruptHandlerAttachment,
    InterruptNotifierAttachment,
)
from protocol_model.interface import InterfaceProtocol
from protocol_model.semantics import ResourceExhaustionPolicy
from protocol_model.virtual_dut.binding.port import InterfaceAttachmentBinding
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.recipes.interrupt import (
    build_explicit_eoi_interrupt_target_vdut,
    build_priority_interrupt_controller_vdut,
)


def build_edge_interrupt_controller_vdut(
    name: str,
    protocol: InterfaceProtocol,
    *,
    ingress_ports: Iterable[str],
    target_port: str = "target",
    capacity: int = 8,
    exhaustion_policy: ResourceExhaustionPolicy | str = (
        ResourceExhaustionPolicy.BLOCK
    ),
) -> VirtualDut:
    """Bind several edge notification inputs to one priority controller."""

    ingress_names = tuple(ingress_ports)
    if not ingress_names or any(not item for item in ingress_names):
        raise ValueError("interrupt controller requires named ingress ports")
    if len(set(ingress_names)) != len(ingress_names):
        raise ValueError("interrupt controller ingress ports must be unique")
    if not target_port or target_port in ingress_names:
        raise ValueError("interrupt target port must be distinct and non-empty")

    ingress_bindings = {
        port_name: InterfaceAttachmentBinding(
            InterfacePort(port_name, protocol, "handler"),
            InterruptHandlerAttachment(protocol),
        )
        for port_name in ingress_names
    }
    target_binding = InterfaceAttachmentBinding(
        InterfacePort(target_port, protocol, "notifier"),
        InterruptNotifierAttachment(protocol),
    )
    return build_priority_interrupt_controller_vdut(
        name,
        ingress_bindings,
        target_binding,
        capacity=capacity,
        exhaustion_policy=exhaustion_policy,
        description=(
            "edge interrupt controller with priority arbitration and one "
            "active target delivery"
        ),
    )


def build_edge_interrupt_target_vdut(
    name: str,
    protocol: InterfaceProtocol,
    *,
    port_name: str = "interrupt",
) -> VirtualDut:
    """Build a target fixture that produces EOI on explicit advance."""

    binding = InterfaceAttachmentBinding(
        InterfacePort(port_name, protocol, "handler"),
        InterruptHandlerAttachment(protocol),
    )
    return build_explicit_eoi_interrupt_target_vdut(name, binding)


__all__ = [
    "build_edge_interrupt_controller_vdut",
    "build_edge_interrupt_target_vdut",
]
