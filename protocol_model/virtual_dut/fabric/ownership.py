"""Cross-port ownership records shared by address-fabric controllers."""

from __future__ import annotations

from dataclasses import dataclass

from ..address.access import AddressAccess


@dataclass(frozen=True)
class RoutedAddressRequest:
    """Ownership retained until one routed endpoint request completes."""

    request_id: int
    ingress_port: str
    egress_port: str
    input_access: AddressAccess
    output_access: AddressAccess
    reply_context: object | None = None


__all__ = ["RoutedAddressRequest"]
