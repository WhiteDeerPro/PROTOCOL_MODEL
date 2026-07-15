"""Protocol-independent address operations and constructed regions."""

from .access import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressRead,
    AddressStep,
    AddressWrite,
    ByteOrder,
)
from .memory import MemoryRegion, MemoryRegionState
from .register import (
    RegisterPermission,
    RegisterRegion,
    RegisterRegionState,
    RegisterSpec,
)
from .space import AddressRegion, AddressSpace, AddressSpaceState

__all__ = [
    "AccessResult",
    "AccessStatus",
    "AddressAccess",
    "AddressRead",
    "AddressRegion",
    "AddressSpace",
    "AddressSpaceState",
    "AddressStep",
    "AddressWrite",
    "ByteOrder",
    "MemoryRegion",
    "MemoryRegionState",
    "RegisterPermission",
    "RegisterRegion",
    "RegisterRegionState",
    "RegisterSpec",
]
