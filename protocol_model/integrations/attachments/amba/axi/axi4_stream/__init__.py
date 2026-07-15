"""AXI4-Stream translations for protocol-neutral stream transfers."""

from .receiver import Axi4StreamReceiverAttachment
from .transmitter import Axi4StreamTransmitterAttachment

__all__ = [
    "Axi4StreamReceiverAttachment",
    "Axi4StreamTransmitterAttachment",
]
