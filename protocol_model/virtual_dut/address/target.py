"""Protocol-neutral stateful targets for address operations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .access import AddressAccess, AddressStep


@runtime_checkable
class AddressTarget(Protocol):
    """State core that executes one complete protocol-neutral access.

    Interface attachments, transport packets, queues, and scheduling remain
    outside this contract.  ``AddressSpace`` and individual address regions
    satisfy it structurally, which lets several protocol-specific boundaries
    reuse one local state authority without invoking another protocol's
    attachment wrapper.
    """

    def initial_state(self) -> object:
        ...

    def access(self, state: object, request: AddressAccess) -> AddressStep:
        ...


__all__ = ["AddressTarget"]
