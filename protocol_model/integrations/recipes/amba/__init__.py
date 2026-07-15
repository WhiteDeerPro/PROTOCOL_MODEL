"""VirtualDut recipes whose exposed ports use AMBA link families."""

from .endpoints import (
    build_ahb_address_space_vdut,
    build_ahb_blackhole_sink_vdut,
    build_ahb_idle_source_vdut,
    build_apb_address_space_vdut,
    build_apb_blackhole_sink_vdut,
    build_apb_idle_source_vdut,
    build_axi4_address_space_vdut,
    build_axi4_blackhole_sink_vdut,
    build_axi4_idle_source_vdut,
    build_axi4_lite_address_space_vdut,
    build_axi4_stream_capture_vdut,
)
from .fabrics import (
    build_ahb_address_fabric_vdut,
    build_apb_address_fabric_vdut,
    build_axi4_lite_address_fabric_vdut,
)
from .bridges import (
    Axi4ToApbBridgeProfile,
    build_axi4_lite_to_apb_bridge_vdut,
    build_axi4_to_apb_bridge_vdut,
)

__all__ = [
    "build_ahb_address_fabric_vdut",
    "build_ahb_address_space_vdut",
    "build_ahb_blackhole_sink_vdut",
    "build_ahb_idle_source_vdut",
    "build_apb_address_fabric_vdut",
    "build_apb_address_space_vdut",
    "build_apb_blackhole_sink_vdut",
    "build_apb_idle_source_vdut",
    "build_axi4_address_space_vdut",
    "build_axi4_blackhole_sink_vdut",
    "build_axi4_idle_source_vdut",
    "build_axi4_lite_address_fabric_vdut",
    "build_axi4_lite_address_space_vdut",
    "build_axi4_lite_to_apb_bridge_vdut",
    "build_axi4_to_apb_bridge_vdut",
    "build_axi4_stream_capture_vdut",
    "Axi4ToApbBridgeProfile",
]
