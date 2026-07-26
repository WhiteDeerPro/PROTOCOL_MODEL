"""Static binding between one VirtualDut port and one attachment."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.interface import InterfaceProtocol

from ..attachments.base import InterfaceAttachment
from ..boundary.port import InterfacePort


@dataclass(frozen=True)
class InterfaceAttachmentBinding:
    """Immutable local implementation binding; runtime state lives elsewhere."""

    port: InterfacePort
    attachment: InterfaceAttachment

    def __post_init__(self) -> None:
        if not isinstance(self.port, InterfacePort):
            raise TypeError("attachment binding requires an InterfacePort")
        if not isinstance(self.attachment, InterfaceAttachment):
            raise TypeError("attachment binding requires an InterfaceAttachment")
        attachment_protocol = self.attachment.protocol
        if not isinstance(attachment_protocol, InterfaceProtocol):
            raise TypeError("attachment must declare an InterfaceProtocol")
        if not isinstance(self.attachment.role, str) or not self.attachment.role:
            raise TypeError("attachment must declare a non-empty protocol role")
        if not attachment_protocol.has_same_interface_shape_as(self.port.protocol):
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
