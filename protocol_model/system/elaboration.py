"""Topology and ownership elaboration for SystemProtocol."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.semantics import SemanticFragment, compose_fragments
from protocol_model.virtual_dut.boundary.port import ProtocolPort

from .protocol import SystemProtocol, VirtualDutPortRef


@dataclass(frozen=True)
class ElaboratedSystemProtocol:
    spec: SystemProtocol
    semantics: SemanticFragment
    owner_by_port: Mapping[VirtualDutPortRef, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "owner_by_port", MappingProxyType(dict(self.owner_by_port))
        )


def _resolve_port(
    system: SystemProtocol, reference: VirtualDutPortRef
) -> ProtocolPort:
    try:
        dut = system.virtual_duts[reference.dut]
    except KeyError as exc:
        raise ValueError(f"unknown VirtualDut {reference.dut!r}") from exc
    try:
        return dut.port(reference.port)
    except KeyError as exc:
        raise ValueError(
            f"unknown port {reference.port!r} on VirtualDut {reference.dut!r}"
        ) from exc


def elaborate_system_protocol(system: SystemProtocol) -> ElaboratedSystemProtocol:
    owners: dict[VirtualDutPortRef, str] = {}
    fragments: list[SemanticFragment] = []

    for dut_name, dut in system.virtual_duts.items():
        if dut.semantics is not None:
            fragments.append(dut.semantics.namespaced(f"dut.{dut_name}"))

    for link_name, link in system.links.items():
        for role, reference in link.endpoints.items():
            port = _resolve_port(system, reference)
            if port.role != role:
                raise ValueError(
                    f"{reference.qualified_name} has role {port.role!r}, "
                    f"not bound role {role!r}"
                )
            if port.protocol != link.protocol:
                raise ValueError(
                    f"{reference.qualified_name} uses {port.protocol.name!r}, "
                    f"not link protocol {link.protocol.name!r}"
                )
            if reference in owners:
                raise ValueError(
                    f"VirtualDut port {reference.qualified_name!r} is multiply owned"
                )
            owners[reference] = f"link:{link_name}"
        fragments.append(link.protocol.semantics.namespaced(f"link.{link_name}"))

    for boundary_name, reference in system.boundary.items():
        _resolve_port(system, reference)
        if reference in owners:
            raise ValueError(
                f"boundary port {reference.qualified_name!r} is already connected"
            )
        if reference in system.boundary.values() and any(
            other_name != boundary_name and other_ref == reference
            for other_name, other_ref in system.boundary.items()
        ):
            raise ValueError(
                f"VirtualDut port {reference.qualified_name!r} has multiple boundary names"
            )
        owners[reference] = f"boundary:{boundary_name}"

    declared = {
        VirtualDutPortRef(dut_name, port_name)
        for dut_name, dut in system.virtual_duts.items()
        for port_name in dut.ports
    }
    unowned = declared - set(owners)
    if unowned:
        names = sorted(item.qualified_name for item in unowned)
        raise ValueError(f"unconnected VirtualDut ports: {names!r}")

    if system.semantics is not None:
        fragments.append(system.semantics.namespaced(f"system.{system.name}"))

    return ElaboratedSystemProtocol(
        spec=system,
        semantics=compose_fragments(f"{system.name}.elaborated", *fragments),
        owner_by_port=owners,
    )
