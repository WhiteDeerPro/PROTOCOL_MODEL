"""Stable construction facade for concrete virtual modules.

Protocol-independent attachments and backend state live in their named
subpackages. Protocol-specific ``InterfaceAttachment`` implementations live
under ``protocol_model.integrations``; family-specific multi-port participant
adapters can remain with the protocol family. This facade keeps the objects
commonly used to declare and assemble a VirtualDut.
"""

from .address import (
    AccessProtection,
    AccessResult,
    AccessStatus,
    AddressAccess,
    AddressBurst,
    AddressBurstResult,
    AddressRead,
    AddressSpace,
    AddressStep,
    AddressTarget,
    AddressWrite,
    ByteOrder,
    MemoryRegion,
    PROTECTION_ATTRIBUTE,
    RegisterPermission,
    RegisterRegion,
    RegisterSpec,
)
from .arbitration import round_robin_grant, round_robin_select
from .backend.advance import ExplicitlyAdvanceableBackend
from .backend.backing import BackingLine, FullLineBackingCore
from .backend.base import VirtualDutBackend
from .backend.cache import CacheCore, CacheLinePayload, CacheLineStore
from .backend.simple import (
    CaptureBackend,
    FunctionBackend,
    NoOpBackend,
)
from .backend.stepped_emission import (
    EmissionBatchScheduling,
    EmissionOffer,
    EmissionWaitContext,
    EmissionWaitPolicy,
    SteppedEmissionBackend,
    SteppedEmissionProfile,
    constant_emission_wait,
)
from .backend.memory_copy import MemoryCopyDescriptor
from .backend.sensor_fifo import (
    SensorEmptyPolicy,
    SensorFifoConfig,
    SensorFullPolicy,
    SensorSampleContext,
    incrementing_sample_policy,
)
from .backend.transition import (
    DutEffect,
    DutTransition,
    PortEmission,
    PortInput,
)
from .binding import InterfaceAttachmentBinding, VirtualDutBuilder
from .boundary import (
    DutBehaviorTag,
    InterfacePort,
    TransportDirection,
    TransportPort,
    VirtualDut,
)
from .attachments.stream import StreamTransfer
from .attachments.notification import Notification, NotificationCompletion
from .fabric.route import AddressRoute
from .recipes import (
    build_scheduled_address_crossbar_vdut,
    build_address_operation_translation_vdut,
    build_address_translation_vdut,
    build_blackhole_sink_vdut,
    build_explicit_eoi_interrupt_target_vdut,
    build_idle_source_vdut,
    build_priority_interrupt_controller_vdut,
    build_queued_address_responder_vdut,
    build_sensor_fifo_vdut,
    build_serialized_memory_copy_vdut,
)

__all__ = [
    "AccessResult",
    "AccessProtection",
    "AccessStatus",
    "AddressAccess",
    "AddressBurst",
    "AddressBurstResult",
    "AddressRead",
    "AddressRoute",
    "AddressSpace",
    "AddressStep",
    "AddressTarget",
    "AddressWrite",
    "ByteOrder",
    "BackingLine",
    "CacheCore",
    "CacheLinePayload",
    "CacheLineStore",
    "CaptureBackend",
    "DutEffect",
    "DutBehaviorTag",
    "DutTransition",
    "EmissionBatchScheduling",
    "EmissionOffer",
    "EmissionWaitContext",
    "EmissionWaitPolicy",
    "ExplicitlyAdvanceableBackend",
    "FunctionBackend",
    "FullLineBackingCore",
    "MemoryRegion",
    "MemoryCopyDescriptor",
    "NoOpBackend",
    "Notification",
    "NotificationCompletion",
    "PortEmission",
    "InterfaceAttachmentBinding",
    "PortInput",
    "PROTECTION_ATTRIBUTE",
    "InterfacePort",
    "TransportDirection",
    "TransportPort",
    "RegisterPermission",
    "RegisterRegion",
    "RegisterSpec",
    "SensorEmptyPolicy",
    "SensorFifoConfig",
    "SensorFullPolicy",
    "SensorSampleContext",
    "StreamTransfer",
    "SteppedEmissionBackend",
    "SteppedEmissionProfile",
    "VirtualDut",
    "VirtualDutBuilder",
    "VirtualDutBackend",
    "build_address_operation_translation_vdut",
    "build_address_translation_vdut",
    "build_blackhole_sink_vdut",
    "build_explicit_eoi_interrupt_target_vdut",
    "build_idle_source_vdut",
    "build_priority_interrupt_controller_vdut",
    "build_queued_address_responder_vdut",
    "build_sensor_fifo_vdut",
    "build_scheduled_address_crossbar_vdut",
    "build_serialized_memory_copy_vdut",
    "constant_emission_wait",
    "incrementing_sample_policy",
    "round_robin_grant",
    "round_robin_select",
]
