"""Port-facing backend contracts and small protocol-neutral fixtures.

Concrete backends such as ``backend.address_space`` are imported from their
leaf modules so loading the transition foundation does not pull higher layers
back into itself.
"""

from .advance import ExplicitlyAdvanceableBackend
from .base import VirtualDutBackend
from .backing import (
    BackingCommitConflict,
    BackingLine,
    BackingLineRecord,
    BackingMutation,
    FullLineBackingCore,
    LineBackingState,
    PreparedBackingPatch,
    PreparedBackingWrite,
)
from .cache import (
    CacheCore,
    CacheLinePayload,
    CacheLineStore,
    CacheLineStoreMutation,
    CacheLineStoreState,
    StoredCacheLine,
)
from .simple import (
    CaptureBackend,
    CaptureState,
    FunctionBackend,
    FunctionBackendState,
    NoOpBackend,
)
from .stepped_emission import (
    DeferredPortEmission,
    EmissionBatchOrderingKeyPolicy,
    EmissionBatchScheduling,
    EmissionOffer,
    EmissionWaitContext,
    EmissionWaitPolicy,
    SteppedEmissionBackend,
    SteppedEmissionProfile,
    SteppedEmissionState,
    constant_emission_wait,
)
from .transition import DutEffect, DutTransition, PortEmission, PortInput

__all__ = [
    "BackingCommitConflict",
    "BackingLine",
    "BackingLineRecord",
    "BackingMutation",
    "CaptureBackend",
    "CaptureState",
    "CacheCore",
    "CacheLinePayload",
    "CacheLineStore",
    "CacheLineStoreMutation",
    "CacheLineStoreState",
    "DeferredPortEmission",
    "DutEffect",
    "DutTransition",
    "EmissionBatchOrderingKeyPolicy",
    "EmissionBatchScheduling",
    "EmissionOffer",
    "EmissionWaitContext",
    "EmissionWaitPolicy",
    "ExplicitlyAdvanceableBackend",
    "FunctionBackend",
    "FunctionBackendState",
    "FullLineBackingCore",
    "LineBackingState",
    "NoOpBackend",
    "PortEmission",
    "PortInput",
    "PreparedBackingPatch",
    "PreparedBackingWrite",
    "SteppedEmissionBackend",
    "SteppedEmissionProfile",
    "SteppedEmissionState",
    "StoredCacheLine",
    "VirtualDutBackend",
    "constant_emission_wait",
]
