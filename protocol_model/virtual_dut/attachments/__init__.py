"""Protocol-independent attachment contracts.

Concrete protocol adapters are exposed by ``protocol_model.integrations``.
Loading this package therefore does not pull APB, AHB, AXI, or other protocol
implementations into lower backend layers.
"""

from .address import (
    AddressCompleterAttachment,
    AddressCompletion,
    AddressCompletionDecode,
    AddressRequest,
    AddressRequestDecode,
    AddressRequesterAttachment,
)
from .base import AttachmentEmission, ProtocolAttachment
from .empty import EmptyEndpointAttachment, EmptyEndpointMode
from .stream import (
    StreamReceiverAttachment,
    StreamTransfer,
    StreamTransferDecode,
    StreamTransmitterAttachment,
)
from .validation import incoming_event_fault, outgoing_event_fault

__all__ = [
    "AddressCompleterAttachment",
    "AddressCompletion",
    "AddressCompletionDecode",
    "AddressRequest",
    "AddressRequestDecode",
    "AddressRequesterAttachment",
    "AttachmentEmission",
    "EmptyEndpointAttachment",
    "EmptyEndpointMode",
    "ProtocolAttachment",
    "StreamReceiverAttachment",
    "StreamTransfer",
    "StreamTransferDecode",
    "StreamTransmitterAttachment",
    "incoming_event_fault",
    "outgoing_event_fault",
]
