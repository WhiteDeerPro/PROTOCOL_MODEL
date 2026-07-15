"""Same-family multi-port AMBA address-fabric recipes."""

from .ahb import build_ahb_address_fabric_vdut
from .apb import build_apb_address_fabric_vdut
from .axi4_lite import build_axi4_lite_address_fabric_vdut

__all__ = [
    "build_ahb_address_fabric_vdut",
    "build_apb_address_fabric_vdut",
    "build_axi4_lite_address_fabric_vdut",
]
