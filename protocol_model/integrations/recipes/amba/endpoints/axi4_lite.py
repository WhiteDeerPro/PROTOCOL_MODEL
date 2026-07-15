"""AXI4-Lite-bound AddressSpace endpoint recipe."""

from __future__ import annotations

from protocol_model.integrations.attachments.amba.axi.axi4_lite import (
    Axi4LiteCompleterAttachment,
)
from protocol_model.link import LinkProtocol
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.boundary.module import VirtualDut

from ._address_space import build_passive_address_space_vdut


def build_axi4_lite_address_space_vdut(
    name: str,
    protocol: LinkProtocol,
    address_space: AddressSpace,
    *,
    port_name: str = "axi",
    capability: object | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Construct one passive AXI4-Lite subordinate AddressSpace endpoint."""

    return build_passive_address_space_vdut(
        name,
        protocol,
        address_space,
        Axi4LiteCompleterAttachment(protocol, byte_order=byte_order),
        port_name=port_name,
        capability=capability,
        description="passive AXI4-Lite AddressSpace endpoint",
    )
