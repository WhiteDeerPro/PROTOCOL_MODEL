"""Runtime ownership state for constructed address fabric backends."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..address.access import AddressAccess


@dataclass(frozen=True)
class RoutedAddressRequest:
    """Cross-port ownership retained until the endpoint completes a request."""

    request_id: int
    ingress_port: str
    egress_port: str
    input_access: AddressAccess
    output_access: AddressAccess
    reply_context: object | None = None


@dataclass(frozen=True)
class AddressFabricState:
    ingress_state: object
    egress_states: Mapping[str, object]
    pending: Mapping[int, RoutedAddressRequest]
    next_request_id: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "egress_states", MappingProxyType(dict(self.egress_states))
        )
        object.__setattr__(self, "pending", MappingProxyType(dict(self.pending)))
