"""Control-protocol integration recipes."""

from .interrupt import (
    build_edge_interrupt_controller_vdut,
    build_edge_interrupt_target_vdut,
)

__all__ = [
    "build_edge_interrupt_controller_vdut",
    "build_edge_interrupt_target_vdut",
]
