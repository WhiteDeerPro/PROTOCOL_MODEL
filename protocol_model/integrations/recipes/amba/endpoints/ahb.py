"""AHB-bound AddressSpace endpoint recipe."""

from __future__ import annotations

from protocol_model.integrations.attachments.amba.ahb import AhbCompleterAttachment
from protocol_model.link import LinkProtocol
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.boundary.module import VirtualDut

from ._address_space import build_passive_address_space_vdut


def build_ahb_address_space_vdut(
    name: str,
    protocol: LinkProtocol,
    address_space: AddressSpace,
    *,
    port_name: str = "ahb",
    capability: object | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Construct one passive AHB subordinate backed by an AddressSpace."""

    return build_passive_address_space_vdut(
        name,
        protocol,
        address_space,
        AhbCompleterAttachment(protocol, byte_order=byte_order),
        port_name=port_name,
        capability=capability,
        description="passive AHB AddressSpace endpoint",
    )
