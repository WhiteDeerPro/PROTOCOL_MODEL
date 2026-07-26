"""System-scope protocols and topology elaboration."""

from .construction import AddressRouterFactory, SystemProtocolBuilder
from .contracts import (
    AddressClaim,
    AddressMapContract,
    AddressRouterContract,
    AddressWindow,
)
from .elaboration import ElaboratedSystemProtocol, elaborate_system_protocol
from .protocol import SystemConnection, SystemProtocol
from .resolution import (
    ResolvedAddressPath,
    ResolvedAddressPlan,
    ResolvedTransportHop,
    ResolvedTransportPlan,
)
from .session import (
    DutAdvanceAction,
    SystemAction,
    SystemEvent,
    SystemSession,
    SystemSessionState,
    SystemTrace,
)
from .topology import (
    DirectedTransportConnection,
    InterfaceConnection,
    PortOwnerKind,
    PortOwnerRef,
    VirtualDutPortRef,
)

__all__ = [
    "AddressClaim",
    "AddressMapContract",
    "AddressRouterContract",
    "AddressRouterFactory",
    "AddressWindow",
    "ElaboratedSystemProtocol",
    "DutAdvanceAction",
    "DirectedTransportConnection",
    "InterfaceConnection",
    "PortOwnerKind",
    "PortOwnerRef",
    "ResolvedAddressPath",
    "ResolvedAddressPlan",
    "ResolvedTransportHop",
    "ResolvedTransportPlan",
    "SystemConnection",
    "SystemProtocol",
    "SystemProtocolBuilder",
    "SystemAction",
    "SystemEvent",
    "SystemSession",
    "SystemSessionState",
    "SystemTrace",
    "VirtualDutPortRef",
    "elaborate_system_protocol",
]
