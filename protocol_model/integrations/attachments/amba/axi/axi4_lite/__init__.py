"""AXI4-Lite translations for address operations."""

from .common import Axi4LiteCompleterState, Axi4LiteRequesterState
from .completer import Axi4LiteCompleterAttachment
from .requester import Axi4LiteRequesterAttachment

__all__ = [
    "Axi4LiteCompleterAttachment",
    "Axi4LiteCompleterState",
    "Axi4LiteRequesterAttachment",
    "Axi4LiteRequesterState",
]
