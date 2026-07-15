"""AXI4-bound AddressSpace endpoint VirtualDut recipe."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.binding import PortAttachmentBinding, VirtualDutBuilder
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import ProtocolPort

from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4AddressSpaceAttachment,
)

from .axi4_backend import Axi4AddressSpaceBackend


def build_axi4_address_space_vdut(
    name: str,
    protocol: LinkProtocol,
    address_space: AddressSpace,
    *,
    port_name: str = "axi",
    capability: object | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Construct one burst-aware normal-access AXI4 subordinate endpoint."""

    attachment = Axi4AddressSpaceAttachment(
        protocol, byte_order=byte_order
    )
    binding = PortAttachmentBinding(
        ProtocolPort(
            port_name,
            protocol,
            attachment.role,
            capability=capability,
        ),
        attachment,
    )
    backend = Axi4AddressSpaceBackend(address_space, binding)
    return (
        VirtualDutBuilder(name)
        .bind(binding)
        .with_model(backend)
        .describe("burst-aware AXI4 AddressSpace endpoint")
        .build()
    )
