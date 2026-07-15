"""Presentation-only selection policies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LaneDisplayPolicy:
    """Select lanes for a projection without adding protocol semantics.

    ``hidden_lanes`` is an explicit presentation choice. ``hide_inactive``
    can omit lanes with no visible activity in a particular trace. Neither
    option demonstrates that a lane obeyed a quiet constraint.
    """

    hidden_lanes: frozenset[str] = frozenset()
    hide_inactive: bool = False

    def __post_init__(self) -> None:
        if any(not lane for lane in self.hidden_lanes):
            raise ValueError("hidden lane names must not be empty")

    def shows(self, lane: str, *, active: bool) -> bool:
        if not lane:
            raise ValueError("lane name must not be empty")
        return lane not in self.hidden_lanes and (active or not self.hide_inactive)
