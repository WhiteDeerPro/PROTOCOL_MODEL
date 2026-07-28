"""Concrete multi-port bridge VirtualDut recipes with AMBA boundaries."""

from .axi4_apb import build_axi4_to_apb_bridge_vdut
from .axi4_lite_apb import build_axi4_lite_to_apb_bridge_vdut
from .axi4_ahb import build_axi4_to_ahb_lite_bridge_vdut
from .serial import build_amba_serial_bridge_vdut
from .serial_address import build_amba_serial_address_bridge_vdut
from .serial_burst import build_amba_serial_burst_bridge_vdut

__all__ = [
    "build_amba_serial_bridge_vdut",
    "build_amba_serial_address_bridge_vdut",
    "build_amba_serial_burst_bridge_vdut",
    "build_axi4_lite_to_apb_bridge_vdut",
    "build_axi4_to_ahb_lite_bridge_vdut",
    "build_axi4_to_apb_bridge_vdut",
]
