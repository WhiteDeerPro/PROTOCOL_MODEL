"""Protocol-bearing ports on a concrete VirtualDut boundary."""

from __future__ import annotations

from dataclasses import dataclass, field

from protocol_model.interface import InterfaceProtocol


@dataclass(frozen=True)
class InterfacePort:
    """One InterfaceProtocol role attached to a concrete VirtualDut boundary."""

    name: str
    protocol: InterfaceProtocol
    role: str
    capability: object | None = field(default=None, repr=False)
    clock_domain: str | None = None
    reset_domain: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("interface port requires a name")
        if self.role not in self.protocol.roles:
            raise ValueError(
                f"port role {self.role!r} is not in protocol {self.protocol.name!r}"
            )
