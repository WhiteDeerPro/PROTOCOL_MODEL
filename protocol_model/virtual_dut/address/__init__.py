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
from .attributes import AccessProtection, PROTECTION_ATTRIBUTE
from .burst import AddressBurst, AddressBurstResult
from .memory import MemoryRegion, MemoryRegionState
from .register import (
    RegisterPermission,
    RegisterRegion,
    RegisterRegionState,
    RegisterSpec,
)
from .space import AddressRegion, AddressSpace, AddressSpaceState
from .target import AddressTarget

__all__ = [
    "AccessResult",
    "AccessProtection",
    "AccessStatus",
    "AddressAccess",
    "AddressBurst",
    "AddressBurstResult",
    "AddressRead",
    "AddressRegion",
    "AddressSpace",
    "AddressSpaceState",
    "AddressStep",
    "AddressTarget",
    "AddressWrite",
    "ByteOrder",
    "MemoryRegion",
    "MemoryRegionState",
    "PROTECTION_ATTRIBUTE",
    "RegisterPermission",
    "RegisterRegion",
    "RegisterRegionState",
    "RegisterSpec",
]
