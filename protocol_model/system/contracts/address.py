"""Explicit address authority and router-boundary declarations."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.virtual_dut.fabric.route import (
    AddressRoute,
    validate_address_routes,
)

from ..topology.model import VirtualDutPortRef


@dataclass(frozen=True, order=True)
class AddressWindow:
    """One half-open address interval ``[base, base + size)``."""

    base_address: int
    size_bytes: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.base_address, int)
            or isinstance(self.base_address, bool)
            or self.base_address < 0
        ):
            raise ValueError("address window base must be a non-negative integer")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes <= 0
        ):
            raise ValueError("address window size must be a positive integer")

    @property
    def limit_address(self) -> int:
        return self.base_address + self.size_bytes

    def contains(self, other: "AddressWindow") -> bool:
        return (
            self.base_address <= other.base_address
            and other.limit_address <= self.limit_address
        )

    def overlaps(self, other: "AddressWindow") -> bool:
        return (
            self.base_address < other.limit_address
            and other.base_address < self.limit_address
        )


@dataclass(frozen=True)
class AddressClaim:
    """A receiver boundary's promise to accept one local address window."""

    name: str
    endpoint: VirtualDutPortRef
    window: AddressWindow

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("address claim requires a name")
        if not isinstance(self.endpoint, VirtualDutPortRef):
            raise TypeError("address claim endpoint requires VirtualDutPortRef")
        if not isinstance(self.window, AddressWindow):
            raise TypeError("address claim requires AddressWindow")


@dataclass(frozen=True)
class AddressRouterContract:
    """Declared address behavior at one routing VirtualDut boundary.

    This contract is an explicit input.  Its presence does not follow from a
    star-shaped topology, and it does not describe the router's private
    arbitration, queue, lease, or completion-owner state.
    """

    name: str
    router: str
    ingress_ports: tuple[str, ...]
    egress_ports: tuple[str, ...]
    routes: tuple[AddressRoute, ...]

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("address router contract requires a name")
        if not self.router:
            raise ValueError("address router contract requires a router")
        ingresses = tuple(self.ingress_ports)
        egresses = tuple(self.egress_ports)
        if not ingresses:
            raise ValueError("address router requires at least one ingress")
        if not egresses:
            raise ValueError("address router requires at least one egress")
        for ports, subject in (
            (ingresses, "ingress"),
            (egresses, "egress"),
        ):
            if any(not isinstance(port, str) or not port for port in ports):
                raise ValueError(
                    f"address router {subject} ports must be non-empty strings"
                )
            if len(set(ports)) != len(ports):
                raise ValueError(
                    f"address router {subject} ports must be unique"
                )
        shared = set(ingresses) & set(egresses)
        if shared:
            raise ValueError(
                "address router ingress and egress ports must be disjoint: "
                f"{sorted(shared)!r}"
            )
        routes = tuple(self.routes)
        if any(not isinstance(route, AddressRoute) for route in routes):
            raise TypeError("address router routes require AddressRoute values")
        routes = validate_address_routes(routes, egresses)
        object.__setattr__(self, "ingress_ports", ingresses)
        object.__setattr__(self, "egress_ports", egresses)
        object.__setattr__(self, "routes", routes)


@dataclass(frozen=True)
class AddressMapContract:
    """System authority joining receiver claims and explicit router maps."""

    claims: tuple[AddressClaim, ...] = ()
    routers: tuple[AddressRouterContract, ...] = ()

    def __post_init__(self) -> None:
        claims = tuple(self.claims)
        routers = tuple(self.routers)
        if any(not isinstance(claim, AddressClaim) for claim in claims):
            raise TypeError("address map claims require AddressClaim values")
        if any(
            not isinstance(router, AddressRouterContract) for router in routers
        ):
            raise TypeError(
                "address map routers require AddressRouterContract values"
            )
        claim_names = [claim.name for claim in claims]
        if len(set(claim_names)) != len(claim_names):
            raise ValueError("address claim names must be unique")
        router_names = [router.name for router in routers]
        if len(set(router_names)) != len(router_names):
            raise ValueError("address router contract names must be unique")
        router_duts = [router.router for router in routers]
        if len(set(router_duts)) != len(router_duts):
            raise ValueError(
                "a VirtualDut may have only one address router contract in V1"
            )

        claims_by_endpoint: dict[VirtualDutPortRef, list[AddressClaim]] = {}
        for claim in claims:
            claims_by_endpoint.setdefault(claim.endpoint, []).append(claim)
        for endpoint, endpoint_claims in claims_by_endpoint.items():
            ordered = sorted(
                endpoint_claims,
                key=lambda claim: claim.window.base_address,
            )
            for previous, current in zip(ordered, ordered[1:]):
                if previous.window.overlaps(current.window):
                    raise ValueError(
                        f"address claims {previous.name!r} and "
                        f"{current.name!r} overlap at "
                        f"{endpoint.qualified_name!r}"
                    )

        object.__setattr__(self, "claims", claims)
        object.__setattr__(self, "routers", routers)


__all__ = [
    "AddressClaim",
    "AddressMapContract",
    "AddressRouterContract",
    "AddressWindow",
]
