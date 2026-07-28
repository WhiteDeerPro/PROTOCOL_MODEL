"""Protocol-independent recipes that assemble concrete VirtualDut modules."""

from .address_crossbar import build_scheduled_address_crossbar_vdut
from .address_translation import (
    build_address_operation_translation_vdut,
    build_address_translation_vdut,
)
from .empty import build_blackhole_sink_vdut, build_idle_source_vdut
from .interrupt import (
    build_explicit_eoi_interrupt_target_vdut,
    build_priority_interrupt_controller_vdut,
)
from .memory_copy import build_serialized_memory_copy_vdut
from .queued_address import build_queued_address_responder_vdut
from .sensor_fifo import build_sensor_fifo_vdut

__all__ = [
    "build_scheduled_address_crossbar_vdut",
    "build_address_operation_translation_vdut",
    "build_address_translation_vdut",
    "build_blackhole_sink_vdut",
    "build_explicit_eoi_interrupt_target_vdut",
    "build_idle_source_vdut",
    "build_priority_interrupt_controller_vdut",
    "build_queued_address_responder_vdut",
    "build_sensor_fifo_vdut",
    "build_serialized_memory_copy_vdut",
]
