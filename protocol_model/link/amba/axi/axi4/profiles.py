"""Reusable AXI4 LinkProtocol refinements."""

from __future__ import annotations

from protocol_model.link import LinkProtocol

from .definition import Axi4Config, build_axi4_link


def build_axi4_read_only_profile(
    config: Axi4Config | None = None,
) -> LinkProtocol:
    """Retain the five-channel AXI shape but disable write-channel events."""

    return build_axi4_link(config).forbid_events(
        "axi4_read_only",
        ("AW", "W", "B"),
        reason="inactive in the read-only link profile",
    )
