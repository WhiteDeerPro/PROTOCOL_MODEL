"""Same-family multi-port AMBA address-fabric recipes."""

from .ahb import build_ahb_address_fabric_vdut
from .apb import build_apb_address_fabric_vdut
from .axi4 import (
    Axi4BurstAssemblyProfile,
    Axi4ReadRouteTableProfile,
    Axi4WriteRouteTableProfile,
    build_axi4_read_crossbar_vdut,
    build_axi4_read_demux_vdut,
    build_axi4_write_crossbar_vdut,
)
from .axi4_lite import build_axi4_lite_address_fabric_vdut
from .axi4_lite_crossbar import build_axi4_lite_address_crossbar_vdut

__all__ = [
    "Axi4BurstAssemblyProfile",
    "build_ahb_address_fabric_vdut",
    "build_apb_address_fabric_vdut",
    "Axi4ReadRouteTableProfile",
    "Axi4WriteRouteTableProfile",
    "build_axi4_read_crossbar_vdut",
    "build_axi4_read_demux_vdut",
    "build_axi4_write_crossbar_vdut",
    "build_axi4_lite_address_crossbar_vdut",
    "build_axi4_lite_address_fabric_vdut",
]
