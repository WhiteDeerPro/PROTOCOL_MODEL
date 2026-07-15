"""Single-boundary-role AMBA VirtualDut endpoint recipes."""

from .ahb import build_ahb_address_space_vdut
from .apb import build_apb_address_space_vdut
from .axi4 import build_axi4_address_space_vdut
from .axi4_lite import build_axi4_lite_address_space_vdut
from .axi4_stream import build_axi4_stream_capture_vdut
from .empty import (
    build_ahb_blackhole_sink_vdut,
    build_ahb_idle_source_vdut,
    build_apb_blackhole_sink_vdut,
    build_apb_idle_source_vdut,
    build_axi4_blackhole_sink_vdut,
    build_axi4_idle_source_vdut,
)

__all__ = [
    "build_ahb_address_space_vdut",
    "build_ahb_blackhole_sink_vdut",
    "build_ahb_idle_source_vdut",
    "build_apb_address_space_vdut",
    "build_apb_blackhole_sink_vdut",
    "build_apb_idle_source_vdut",
    "build_axi4_address_space_vdut",
    "build_axi4_blackhole_sink_vdut",
    "build_axi4_idle_source_vdut",
    "build_axi4_lite_address_space_vdut",
    "build_axi4_stream_capture_vdut",
]
