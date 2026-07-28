"""Reusable AXI4 InterfaceProtocol refinements."""

from __future__ import annotations

from protocol_model.interface import InterfaceProtocol

from .definition import Axi4Config, build_axi4_interface


def build_axi4_read_only_profile(
    config: Axi4Config | None = None,
) -> InterfaceProtocol:
    """Retain the five-channel AXI shape but disable write-channel events."""

    return build_axi4_interface(config).forbid_events(
        "axi4_read_only",
        ("AW", "W", "B"),
        reason="inactive in the read-only interface profile",
    )


def build_axi4_write_only_profile(
    config: Axi4Config | None = None,
) -> InterfaceProtocol:
    """Retain the five-channel AXI shape but disable read-channel events."""

    return build_axi4_interface(config).forbid_events(
        "axi4_write_only",
        ("AR", "R"),
        reason="inactive in the write-only interface profile",
    )


__all__ = [
    "build_axi4_read_only_profile",
    "build_axi4_write_only_profile",
]
