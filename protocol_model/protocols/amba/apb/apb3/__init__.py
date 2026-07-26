"""AMBA 3 APB (APB3) InterfaceProtocol."""

from .definition import Apb3Config, build_apb3_interface
from .observation import (
    Apb3ObservationSession,
    Apb3ObservationState,
    Apb3Signals,
)

__all__ = [
    "Apb3Config",
    "Apb3ObservationSession",
    "Apb3ObservationState",
    "Apb3Signals",
    "build_apb3_interface",
]
