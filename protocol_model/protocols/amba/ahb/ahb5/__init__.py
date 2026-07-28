"""AMBA 5 AHB (AHB5) InterfaceProtocol interface-property profile."""

from .definition import (
    Ahb5Config,
    Ahb5ExclusivePending,
    Ahb5ExclusiveSignalMonitor,
    Ahb5ExclusiveState,
    build_ahb5_interface,
)

__all__ = [
    "Ahb5Config",
    "Ahb5ExclusivePending",
    "Ahb5ExclusiveSignalMonitor",
    "Ahb5ExclusiveState",
    "build_ahb5_interface",
]
