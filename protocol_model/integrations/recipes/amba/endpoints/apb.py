"""APB-bound AddressSpace endpoint recipe."""

from __future__ import annotations

from protocol_model.integrations.attachments.amba.apb import ApbCompleterAttachment
from protocol_model.link import LinkProtocol
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.boundary.module import VirtualDut

from ._address_space import build_passive_address_space_vdut


def build_apb_address_space_vdut(
    name: str,
    protocol: LinkProtocol,
    address_space: AddressSpace,
    *,
    port_name: str = "apb",
    capability: object | None = None,
) -> VirtualDut:
    """Construct one passive APB completer backed by an AddressSpace."""

    return build_passive_address_space_vdut(
        name,
        protocol,
        address_space,
        ApbCompleterAttachment(protocol),
        port_name=port_name,
        capability=capability,
        description="passive APB AddressSpace endpoint",
    )
