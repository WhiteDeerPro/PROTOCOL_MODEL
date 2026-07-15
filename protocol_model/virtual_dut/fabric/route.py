"""Address route declarations for constructed fabric backends."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Collection

from ..address.access import AddressAccess


@dataclass(frozen=True)
class AddressRoute:
    """Map one input address window to one fabric egress port."""

    name: str
    base_address: int
    size_bytes: int
    egress_port: str
    output_base_address: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("address route requires a name")
        if (
            not isinstance(self.base_address, int)
            or isinstance(self.base_address, bool)
            or self.base_address < 0
        ):
            raise ValueError("address route base must be a non-negative integer")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes <= 0
        ):
            raise ValueError("address route size must be a positive integer")
        if not self.egress_port:
            raise ValueError("address route requires an egress port")
        if self.output_base_address is not None and (
            not isinstance(self.output_base_address, int)
            or isinstance(self.output_base_address, bool)
            or self.output_base_address < 0
        ):
            raise ValueError(
                "address route output base must be a non-negative integer"
            )

    @property
    def limit_address(self) -> int:
        return self.base_address + self.size_bytes

    def contains(self, access: AddressAccess) -> bool:
        return (
            self.base_address <= access.address
            and access.address + access.size <= self.limit_address
        )

    def translate(self, access: AddressAccess) -> AddressAccess:
        if not self.contains(access):
            raise ValueError("address access is outside the route window")
        if self.output_base_address is None:
            return access
        return replace(
            access,
            address=self.output_base_address + access.address - self.base_address,
        )


def validate_address_routes(
    routes: tuple[AddressRoute, ...],
    egress_ports: Collection[str],
) -> tuple[AddressRoute, ...]:
    """Normalize and validate a complete single-ingress route table."""

    route_items = tuple(routes)
    if not route_items:
        raise ValueError("address fabric requires at least one route")
    route_names = {item.name for item in route_items}
    if len(route_names) != len(route_items):
        raise ValueError("address fabric route names must be unique")
    ports = set(egress_ports)
    unknown_ports = {item.egress_port for item in route_items} - ports
    if unknown_ports:
        raise ValueError(
            f"address routes reference unknown egress ports: {sorted(unknown_ports)!r}"
        )
    unused_ports = ports - {item.egress_port for item in route_items}
    if unused_ports:
        raise ValueError(
            f"address fabric egresses have no route: {sorted(unused_ports)!r}"
        )
    ordered_routes = tuple(
        sorted(route_items, key=lambda item: item.base_address)
    )
    for previous, current in zip(ordered_routes, ordered_routes[1:]):
        if current.base_address < previous.limit_address:
            raise ValueError(
                f"address routes {previous.name!r} and {current.name!r} overlap"
            )
    return ordered_routes
