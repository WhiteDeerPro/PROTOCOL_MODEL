"""Protocol-independent recipes that assemble concrete VirtualDut modules."""

from .empty import build_blackhole_sink_vdut, build_idle_source_vdut

__all__ = ["build_blackhole_sink_vdut", "build_idle_source_vdut"]
