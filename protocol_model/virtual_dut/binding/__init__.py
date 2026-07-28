"""Static VirtualDut port attachment bindings and construction."""

from .builder import VirtualDutBuilder
from .port import InterfaceAttachmentBinding

__all__ = ["InterfaceAttachmentBinding", "VirtualDutBuilder"]
