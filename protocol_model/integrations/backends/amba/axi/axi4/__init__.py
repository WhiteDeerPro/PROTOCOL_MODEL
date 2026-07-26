"""AXI4 protocol-bound VirtualDut execution slices.

Each module keeps the protocol-local configuration, runtime state, ownership
records, and controller that share one lifecycle. Recipes remain in
:mod:`protocol_model.integrations.recipes`.
"""

from .address_space import (
    Axi4AddressSpaceBackend,
    Axi4AddressSpaceBackendState,
)
from .read import (
    Axi4PendingRead,
    Axi4ReadCrossbarBackend,
    Axi4ReadCrossbarState,
    Axi4ReadRouteLock,
    Axi4ReadRouteTableProfile,
)
from .write import (
    Axi4PendingWrite,
    Axi4WriteCrossbarBackend,
    Axi4WriteCrossbarState,
    Axi4WriteRouteLock,
    Axi4WriteRouteTableProfile,
)

__all__ = [
    "Axi4AddressSpaceBackend",
    "Axi4AddressSpaceBackendState",
    "Axi4PendingRead",
    "Axi4PendingWrite",
    "Axi4ReadCrossbarBackend",
    "Axi4ReadCrossbarState",
    "Axi4ReadRouteLock",
    "Axi4ReadRouteTableProfile",
    "Axi4WriteCrossbarBackend",
    "Axi4WriteCrossbarState",
    "Axi4WriteRouteLock",
    "Axi4WriteRouteTableProfile",
]
