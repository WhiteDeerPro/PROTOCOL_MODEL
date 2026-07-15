"""AXI4 LinkProtocol definitions and state-driven generators."""

from .burst import (
    beat_address,
    beat_byte_addresses,
    byte_lane_bounds,
    byte_lane_mask,
    stays_in_address_space,
    stays_in_4kb,
    transfer_container_lane_bounds,
    transfer_container_lane_mask,
    transfer_bytes,
    transfer_count,
)
from .definition import (
    AXI4_FAMILY,
    Axi4Config,
    build_axi4_link,
    build_axi4_read_link,
)
from .exclusive import Axi4ExclusiveMonitor, Axi4ExclusiveState
from .generation import (
    Axi4ReadGenerationPolicy,
    Axi4ReadGenerator,
    Axi4ReadSchedule,
    Axi4WriteGenerationPolicy,
    Axi4WriteGenerator,
)
from .observation import (
    Axi4ObservationPolicy,
    Axi4ObservationSession,
    Axi4ObservationState,
)
from .profiles import build_axi4_read_only_profile
from .write import Axi4WriteMonitor, Axi4WriteState

__all__ = [
    "AXI4_FAMILY",
    "Axi4Config",
    "Axi4ExclusiveMonitor",
    "Axi4ExclusiveState",
    "Axi4ObservationPolicy",
    "Axi4ObservationSession",
    "Axi4ObservationState",
    "Axi4ReadGenerationPolicy",
    "Axi4ReadGenerator",
    "Axi4ReadSchedule",
    "Axi4WriteGenerationPolicy",
    "Axi4WriteGenerator",
    "Axi4WriteMonitor",
    "Axi4WriteState",
    "beat_address",
    "beat_byte_addresses",
    "build_axi4_link",
    "build_axi4_read_link",
    "build_axi4_read_only_profile",
    "byte_lane_bounds",
    "byte_lane_mask",
    "stays_in_address_space",
    "stays_in_4kb",
    "transfer_container_lane_bounds",
    "transfer_container_lane_mask",
    "transfer_bytes",
    "transfer_count",
]
