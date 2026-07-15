"""Port-facing backend contracts and small protocol-neutral fixtures.

Concrete backends such as ``backend.address_space`` are imported from their
leaf modules so loading the transition foundation does not pull higher layers
back into itself.
"""

from .base import VirtualDutModel
from .simple import (
    CaptureModel,
    CaptureState,
    FunctionModel,
    FunctionModelState,
    NoOpModel,
)
from .transition import DutEffect, DutTransition, PortEmission, PortInput

__all__ = [
    "CaptureModel",
    "CaptureState",
    "DutEffect",
    "DutTransition",
    "FunctionModel",
    "FunctionModelState",
    "NoOpModel",
    "PortEmission",
    "PortInput",
    "VirtualDutModel",
]
