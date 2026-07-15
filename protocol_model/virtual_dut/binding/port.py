"""Static binding between one VirtualDut port and one attachment."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol

from ..attachments.base import ProtocolAttachment
from ..boundary.port import ProtocolPort


@dataclass(frozen=True)
class PortAttachmentBinding:
    """Immutable local implementation binding; runtime state lives elsewhere."""

    port: ProtocolPort
    attachment: ProtocolAttachment

    def __post_init__(self) -> None:
        if not isinstance(self.port, ProtocolPort):
            raise TypeError("attachment binding requires a ProtocolPort")
        if not isinstance(self.attachment, ProtocolAttachment):
            raise TypeError("attachment binding requires a ProtocolAttachment")
        attachment_protocol = self.attachment.protocol
        if not isinstance(attachment_protocol, LinkProtocol):
            raise TypeError("attachment must declare a LinkProtocol")
        if not isinstance(self.attachment.role, str) or not self.attachment.role:
            raise TypeError("attachment must declare a non-empty protocol role")
        if not attachment_protocol.has_same_transport_as(self.port.protocol):
            raise ValueError(
                f"attachment protocol {attachment_protocol.name!r} does not match "
                f"port protocol {self.port.protocol.name!r}"
            )
        if self.attachment.role != self.port.role:
            raise ValueError(
                f"attachment role {self.attachment.role!r} does not match "
                f"port role {self.port.role!r}"
            )

    @property
    def name(self) -> str:
        return self.port.name
