"""Weak structural topology declarations for SystemProtocol."""

from .model import InterfaceConnection, VirtualDutPortRef
from .ownership import PortOwnerKind, PortOwnerRef
from .transport import DirectedTransportConnection

__all__ = [
    "DirectedTransportConnection",
    "InterfaceConnection",
    "PortOwnerKind",
    "PortOwnerRef",
    "VirtualDutPortRef",
]
