"""AMBA APB5 InterfaceProtocol."""

from .definition import Apb5CheckType, Apb5Config, build_apb5_interface
from .observation import (
    Apb5ObservationSession,
    Apb5ObservationState,
    Apb5Signals,
)

__all__ = [
    "Apb5CheckType",
    "Apb5Config",
    "Apb5ObservationSession",
    "Apb5ObservationState",
    "Apb5Signals",
    "build_apb5_interface",
]
