"""Immutable boundary facts exposed by constructed address routers."""

from __future__ import annotations

from dataclasses import dataclass

from .route import AddressRoute, validate_address_routes


ADDRESS_ROUTER_PROJECTION = "address_router"


@dataclass(frozen=True)
class AddressRouterBoundaryProjection:
    """Protocol-neutral route facts promised by one router backend.

    This projection contains only stable boundary configuration.  FIFO
    occupancy, arbitration cursors, and completion owners remain private
    runtime state of the VirtualDut backend.
    """

    ingress_ports: tuple[str, ...]
    egress_ports: tuple[str, ...]
    routes: tuple[AddressRoute, ...]

    def __post_init__(self) -> None:
        ingresses = tuple(self.ingress_ports)
        egresses = tuple(self.egress_ports)
        if not ingresses:
            raise ValueError("address router projection requires an ingress")
        if not egresses:
            raise ValueError("address router projection requires an egress")
        for ports, subject in (
            (ingresses, "ingress"),
            (egresses, "egress"),
        ):
            if any(not isinstance(port, str) or not port for port in ports):
                raise ValueError(
                    f"address router projection {subject} names must be "
                    "non-empty strings"
                )
            if len(set(ports)) != len(ports):
                raise ValueError(
                    f"address router projection {subject} names must be unique"
                )
        overlap = set(ingresses).intersection(egresses)
        if overlap:
            raise ValueError(
                "address router projection port roles overlap: "
                f"{sorted(overlap)!r}"
            )
        routes = validate_address_routes(tuple(self.routes), egresses)
        object.__setattr__(self, "ingress_ports", ingresses)
        object.__setattr__(self, "egress_ports", egresses)
        object.__setattr__(self, "routes", routes)


__all__ = [
    "ADDRESS_ROUTER_PROJECTION",
    "AddressRouterBoundaryProjection",
]
