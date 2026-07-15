"""AXI4-Lite native LinkProtocol and its explicit AXI4 embedding."""

from .definition import AXI4_LITE_FAMILY, Axi4LiteConfig, build_axi4_lite_link
from .embedding import Axi4LiteToAxi4
from .observation import Axi4LiteObservationSession

__all__ = [
    "AXI4_LITE_FAMILY",
    "Axi4LiteConfig",
    "Axi4LiteObservationSession",
    "Axi4LiteToAxi4",
    "build_axi4_lite_link",
]
