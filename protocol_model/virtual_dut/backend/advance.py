"""Optional explicit-progress contract for stateful VirtualDut backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .transition import DutTransition


@runtime_checkable
class ExplicitlyAdvanceableBackend(Protocol):
    """Backend that can progress without accepting another port event.

    This is a caller-owned scheduling seam, not an autonomous clock or task.
    A system/scenario decides when to request progress and remains responsible
    for any time or clock-domain meaning attached to that decision.
    """

    def advance(self, state: object, *, steps: int = 1) -> DutTransition:
        ...


__all__ = ["ExplicitlyAdvanceableBackend"]
