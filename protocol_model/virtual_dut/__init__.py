"""Stable construction facade for concrete virtual modules.

Protocol-independent attachments and backend state live in their named
subpackages. Protocol-specific adapters live under ``protocol_model.integrations``;
this facade keeps the objects commonly used to declare and assemble a
VirtualDut.
"""

from .address import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressRead,
    AddressSpace,
    AddressSpaceState,
    AddressStep,
    AddressWrite,
    ByteOrder,
    MemoryRegion,
    MemoryRegionState,
    RegisterPermission,
    RegisterRegion,
    RegisterRegionState,
    RegisterSpec,
)
from .backend.base import VirtualDutModel
from .backend.simple import (
    CaptureModel,
    CaptureState,
    FunctionModel,
    FunctionModelState,
    NoOpModel,
)
from .backend.transition import (
    DutEffect,
    DutTransition,
    PortEmission,
    PortInput,
)
from .binding import PortAttachmentBinding, VirtualDutBuilder
from .boundary import DutFacet, ProtocolPort, VirtualDut
from .attachments.stream import StreamTransfer
from .fabric.route import AddressRoute
from .recipes import build_blackhole_sink_vdut, build_idle_source_vdut

__all__ = [
    "AccessResult",
    "AccessStatus",
    "AddressAccess",
    "AddressRead",
    "AddressRoute",
    "AddressSpace",
    "AddressSpaceState",
    "AddressStep",
    "AddressWrite",
    "ByteOrder",
    "CaptureModel",
    "CaptureState",
    "DutEffect",
    "DutFacet",
    "DutTransition",
    "FunctionModel",
    "FunctionModelState",
    "MemoryRegion",
    "MemoryRegionState",
    "NoOpModel",
    "PortEmission",
    "PortAttachmentBinding",
    "PortInput",
    "ProtocolPort",
    "RegisterPermission",
    "RegisterRegion",
    "RegisterRegionState",
    "RegisterSpec",
    "StreamTransfer",
    "VirtualDut",
    "VirtualDutBuilder",
    "VirtualDutModel",
    "build_blackhole_sink_vdut",
    "build_idle_source_vdut",
]
