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
from .base import AttachmentEmission, InterfaceAttachment
from .address_operation import (
    AddressAccessOperationAdapter,
    AddressOperationCompleterAttachment,
    AddressOperationDecode,
)
from .empty import EmptyEndpointAttachment, EmptyEndpointMode
from .notification import (
    Notification,
    NotificationCompletion,
    NotificationCompletionDecode,
    NotificationDecode,
    NotificationHandlerAttachment,
    NotificationNotifierAttachment,
)
from .relay import CanonicalEventRelayAttachment
from .stream import (
    StreamReceiverAttachment,
    StreamTransfer,
    StreamTransferDecode,
    StreamTransmitterAttachment,
)
from .validation import incoming_event_fault, outgoing_event_fault

__all__ = [
    "AddressAccessOperationAdapter",
    "AddressCompleterAttachment",
    "AddressCompletion",
    "AddressCompletionDecode",
    "AddressRequest",
    "AddressRequestDecode",
    "AddressRequesterAttachment",
    "AddressOperationCompleterAttachment",
    "AddressOperationDecode",
    "AttachmentEmission",
    "CanonicalEventRelayAttachment",
    "EmptyEndpointAttachment",
    "EmptyEndpointMode",
    "Notification",
    "NotificationCompletion",
    "NotificationCompletionDecode",
    "NotificationDecode",
    "NotificationHandlerAttachment",
    "NotificationNotifierAttachment",
    "InterfaceAttachment",
    "StreamReceiverAttachment",
    "StreamTransfer",
    "StreamTransferDecode",
    "StreamTransmitterAttachment",
    "incoming_event_fault",
    "outgoing_event_fault",
]
