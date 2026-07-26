"""AMBA attachment selection for a serialized memory-copy engine."""

from __future__ import annotations

from protocol_model.integrations.attachments.amba.ahb import (
    AhbRequesterAttachment,
)
from protocol_model.integrations.attachments.amba.apb import (
    ApbRequesterAttachment,
)
from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4RequesterAttachment,
)
from protocol_model.integrations.attachments.amba.axi.axi4_lite import (
    Axi4LiteRequesterAttachment,
)
from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.ahb import AHB_FAMILY
from protocol_model.protocols.amba.apb import APB_FAMILY
from protocol_model.protocols.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.protocols.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.backend.memory_copy import MemoryCopyDescriptor
from protocol_model.virtual_dut.binding import InterfaceAttachmentBinding
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.recipes.memory_copy import (
    build_serialized_memory_copy_vdut,
)


def _validate_descriptor_geometry(
    protocol: InterfaceProtocol,
    descriptor: MemoryCopyDescriptor,
) -> None:
    """Validate fixed beat geometry and the protocol address range."""

    if not isinstance(protocol, InterfaceProtocol):
        raise TypeError("AMBA memory copy requires an InterfaceProtocol")
    if not isinstance(descriptor, MemoryCopyDescriptor):
        raise TypeError(
            "AMBA memory copy requires a MemoryCopyDescriptor"
        )
    supported_families = {
        AXI4_FAMILY,
        AXI4_LITE_FAMILY,
        AHB_FAMILY,
        APB_FAMILY,
    }
    if protocol.interface_family not in supported_families:
        raise ValueError(
            "serialized AMBA memory copy supports AXI4, AXI4-Lite, AHB, "
            "and APB requester attachments"
        )
    data_width = int(protocol.parameters.get("data_width", 0))
    address_width = int(protocol.parameters.get("address_width", 0))
    if data_width <= 0 or data_width % 8:
        raise ValueError("AMBA memory copy requires a byte-aligned data width")
    if address_width <= 0:
        raise ValueError("AMBA memory copy requires a positive address width")
    bus_bytes = data_width // 8
    if protocol.interface_family in {AXI4_LITE_FAMILY, APB_FAMILY}:
        if descriptor.beat_bytes != bus_bytes:
            raise ValueError(
                f"{protocol.name} memory-copy beat size must equal the "
                f"{bus_bytes}-byte data bus width"
            )
    elif descriptor.beat_bytes > bus_bytes:
        raise ValueError(
            f"{protocol.name} memory-copy beat size cannot exceed the "
            f"{bus_bytes}-byte data bus width"
        )

    address_limit = 1 << address_width
    addresses = (
        ("source", descriptor.source_address, descriptor.source_for_beat),
        (
            "destination",
            descriptor.destination_address,
            descriptor.destination_for_beat,
        ),
    )
    for subject, first, address_for_beat in addresses:
        last = (
            first
            if descriptor.beat_count == 0
            else address_for_beat(descriptor.beat_count - 1)
        )
        extent = 0 if descriptor.beat_count == 0 else descriptor.beat_bytes
        if first >= address_limit or last + extent > address_limit:
            raise ValueError(
                f"memory-copy {subject} range exceeds the "
                f"{address_width}-bit address space"
            )


def build_amba_serialized_memory_copy_vdut(
    name: str,
    protocol: InterfaceProtocol,
    descriptor: MemoryCopyDescriptor,
    *,
    port_name: str = "bus",
    capability: object | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
    axi4_wire_id: int = 0,
) -> VirtualDut:
    """Construct a one-port DMA fixture for a supported AMBA address interface."""

    _validate_descriptor_geometry(protocol, descriptor)

    normalized_order = (
        byte_order
        if isinstance(byte_order, ByteOrder)
        else ByteOrder(byte_order)
    )
    if protocol.interface_family == AXI4_FAMILY:
        attachment = Axi4RequesterAttachment(
            protocol,
            wire_id=axi4_wire_id,
            byte_order=normalized_order,
        )
    elif protocol.interface_family == AXI4_LITE_FAMILY:
        attachment = Axi4LiteRequesterAttachment(
            protocol, byte_order=normalized_order
        )
    elif protocol.interface_family == AHB_FAMILY:
        attachment = AhbRequesterAttachment(
            protocol, byte_order=normalized_order
        )
    elif protocol.interface_family == APB_FAMILY:
        attachment = ApbRequesterAttachment(protocol)
    else:
        raise ValueError("validated AMBA memory-copy family was lost")

    binding = InterfaceAttachmentBinding(
        InterfacePort(
            port_name,
            protocol,
            attachment.role,
            capability=capability,
        ),
        attachment,
    )
    return build_serialized_memory_copy_vdut(
        name,
        binding,
        descriptor,
        description=(
            f"serialized {protocol.name} memory-copy requester"
        ),
    )


__all__ = ["build_amba_serialized_memory_copy_vdut"]
