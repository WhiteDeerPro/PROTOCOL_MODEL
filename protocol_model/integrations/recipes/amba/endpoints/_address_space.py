"""Private assembly helper shared by passive AMBA address endpoints."""

from __future__ import annotations

from protocol_model.interface import InterfaceProtocol
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.attachments.base import InterfaceAttachment
from protocol_model.virtual_dut.backend.address_space import PassiveAddressSpaceBackend
from protocol_model.virtual_dut.binding import InterfaceAttachmentBinding, VirtualDutBuilder
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort


def build_passive_address_space_vdut(
    name: str,
    protocol: InterfaceProtocol,
    address_space: AddressSpace,
    attachment: InterfaceAttachment,
    *,
    port_name: str,
    capability: object | None,
    description: str,
) -> VirtualDut:
    """Bind one completer attachment to a passive AddressSpace backend."""

    binding = InterfaceAttachmentBinding(
        InterfacePort(
            port_name,
            protocol,
            attachment.role,
            capability=capability,
        ),
        attachment,
    )
    backend = PassiveAddressSpaceBackend(address_space, {binding.name: binding})
    return (
        VirtualDutBuilder(name)
        .bind(binding)
        .with_backend(backend)
        .describe(description)
        .build()
    )
