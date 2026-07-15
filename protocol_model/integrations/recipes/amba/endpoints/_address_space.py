"""Private assembly helper shared by passive AMBA address endpoints."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.attachments.base import ProtocolAttachment
from protocol_model.virtual_dut.backend.address_space import PassiveAddressSpaceBackend
from protocol_model.virtual_dut.binding import PortAttachmentBinding, VirtualDutBuilder
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import ProtocolPort


def build_passive_address_space_vdut(
    name: str,
    protocol: LinkProtocol,
    address_space: AddressSpace,
    attachment: ProtocolAttachment,
    *,
    port_name: str,
    capability: object | None,
    description: str,
) -> VirtualDut:
    """Bind one completer attachment to a passive AddressSpace backend."""

    binding = PortAttachmentBinding(
        ProtocolPort(
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
        .with_model(backend)
        .describe(description)
        .build()
    )
