"""System-scope protocols and topology elaboration."""

from .elaboration import ElaboratedSystemProtocol, elaborate_system_protocol
from .protocol import ProtocolLink, SystemProtocol, VirtualDutPortRef
from .session import (
    SystemAction,
    SystemEvent,
    SystemSession,
    SystemSessionState,
    SystemTrace,
)

__all__ = [
    "ElaboratedSystemProtocol",
    "ProtocolLink",
    "SystemProtocol",
    "SystemAction",
    "SystemEvent",
    "SystemSession",
    "SystemSessionState",
    "SystemTrace",
    "VirtualDutPortRef",
    "elaborate_system_protocol",
]
