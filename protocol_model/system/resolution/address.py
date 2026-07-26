"""Direct-neighbor address claim and route closure."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ..contracts.address import (
    AddressClaim,
    AddressMapContract,
    AddressWindow,
)
from ..protocol import SystemProtocol
from ..topology.model import InterfaceConnection, VirtualDutPortRef
from ..topology.ownership import PortOwnerKind, PortOwnerRef


@dataclass(frozen=True)
class ResolvedAddressPath:
    """One explicit ingress/route/direct-receiver closure witness."""

    router_contract: str
    route: str
    ingress: VirtualDutPortRef
    egress: VirtualDutPortRef
    connection: str
    receiver: VirtualDutPortRef
    input_window: AddressWindow
    output_window: AddressWindow
    claim: AddressClaim


@dataclass(frozen=True)
class ResolvedAddressPlan:
    """Immutable direct-neighbor address paths derived during elaboration."""

    claims_by_name: Mapping[str, AddressClaim]
    paths: tuple[ResolvedAddressPath, ...]
    paths_by_ingress: Mapping[
        VirtualDutPortRef, tuple[ResolvedAddressPath, ...]
    ]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "claims_by_name",
            MappingProxyType(dict(self.claims_by_name)),
        )
        object.__setattr__(self, "paths", tuple(self.paths))
        object.__setattr__(
            self,
            "paths_by_ingress",
            MappingProxyType(
                {
                    ingress: tuple(paths)
                    for ingress, paths in self.paths_by_ingress.items()
                }
            ),
        )


def resolve_address_map(
    system: SystemProtocol,
    owner_by_port: Mapping[VirtualDutPortRef, PortOwnerRef],
) -> ResolvedAddressPlan | None:
    """Close explicitly declared local routes against direct target claims.

    V1 deliberately does not search through bridge chains or infer routing
    behavior from topology. A route resolves only when its egress connection has a
    directly adjacent endpoint with one claim covering the translated window.
    """

    address_map = system.address_map
    if address_map is None:
        return None
    if not isinstance(address_map, AddressMapContract):
        raise TypeError("address resolution requires AddressMapContract")

    claims_by_name = {claim.name: claim for claim in address_map.claims}
    for claim in address_map.claims:
        _require_port(system, claim.endpoint, subject=f"claim {claim.name!r}")

    paths: list[ResolvedAddressPath] = []
    paths_by_ingress: dict[
        VirtualDutPortRef, list[ResolvedAddressPath]
    ] = {}
    for router in address_map.routers:
        if router.router not in system.virtual_duts:
            raise ValueError(
                f"address router {router.name!r} references unknown "
                f"VirtualDut {router.router!r}"
            )

        ingress_refs = tuple(
            VirtualDutPortRef(router.router, port)
            for port in router.ingress_ports
        )
        egress_refs = {
            port: VirtualDutPortRef(router.router, port)
            for port in router.egress_ports
        }
        for reference in (*ingress_refs, *egress_refs.values()):
            _require_internal_connection_owner(
                system,
                owner_by_port,
                reference,
                subject=f"address router {router.name!r}",
            )

        for route in router.routes:
            egress = egress_refs[route.egress_port]
            owner = owner_by_port[egress]
            connection_name = owner.name
            connection = system.connections[connection_name]
            if not isinstance(connection, InterfaceConnection):
                raise ValueError(
                    f"address route egress {egress.qualified_name!r} must "
                    "use an InterfaceConnection"
                )
            peers = frozenset(connection.endpoints.values()) - {egress}
            input_window = AddressWindow(
                route.base_address,
                route.size_bytes,
            )
            output_window = AddressWindow(
                (
                    route.base_address
                    if route.output_base_address is None
                    else route.output_base_address
                ),
                route.size_bytes,
            )
            matches = tuple(
                claim
                for claim in address_map.claims
                if claim.endpoint in peers
                and claim.window.contains(output_window)
            )
            if len(matches) != 1:
                peer_names = sorted(peer.qualified_name for peer in peers)
                if not matches:
                    raise ValueError(
                        f"address route {router.name!r}.{route.name!r} "
                        f"output 0x{output_window.base_address:x}+"
                        f"0x{output_window.size_bytes:x} has no covering "
                        "direct-neighbor claim on connection "
                        f"{connection_name!r}; "
                        f"peers={peer_names!r}"
                    )
                raise ValueError(
                    f"address route {router.name!r}.{route.name!r} "
                    "matches multiple direct-neighbor claims: "
                    f"{sorted(claim.name for claim in matches)!r}"
                )
            claim = matches[0]
            for ingress in ingress_refs:
                path = ResolvedAddressPath(
                    router.name,
                    route.name,
                    ingress,
                    egress,
                    connection_name,
                    claim.endpoint,
                    input_window,
                    output_window,
                    claim,
                )
                paths.append(path)
                paths_by_ingress.setdefault(ingress, []).append(path)

    return ResolvedAddressPlan(
        claims_by_name,
        tuple(paths),
        {
            ingress: tuple(ingress_paths)
            for ingress, ingress_paths in paths_by_ingress.items()
        },
    )


def _require_port(
    system: SystemProtocol,
    reference: VirtualDutPortRef,
    *,
    subject: str,
) -> None:
    dut = system.virtual_duts.get(reference.dut)
    if dut is None:
        raise ValueError(
            f"{subject} references unknown VirtualDut {reference.dut!r}"
        )
    if reference.port not in dut.ports:
        raise ValueError(
            f"{subject} references unknown port {reference.port!r} "
            f"on VirtualDut {reference.dut!r}"
        )


def _require_internal_connection_owner(
    system: SystemProtocol,
    owner_by_port: Mapping[VirtualDutPortRef, PortOwnerRef],
    reference: VirtualDutPortRef,
    *,
    subject: str,
) -> None:
    _require_port(system, reference, subject=subject)
    owner = owner_by_port.get(reference)
    if owner is None or owner.kind is not PortOwnerKind.INTERFACE_CONNECTION:
        raise ValueError(
            f"{subject} port {reference.qualified_name!r} must be owned "
            "by an internal InterfaceConnection"
        )


__all__ = [
    "ResolvedAddressPath",
    "ResolvedAddressPlan",
    "resolve_address_map",
]
