"""Typed projections of address interconnect boundaries.

The projector reads an explicit SystemProtocol address-router contract or an
immutable boundary projection exposed by a constructed backend.  A star-like
topology alone is not treated as evidence that a VirtualDut routes traffic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from html import escape
import json
from math import lcm
from types import MappingProxyType
from typing import Mapping

from protocol_model.system.elaboration import ElaboratedSystemProtocol
from protocol_model.system.protocol import SystemProtocol
from protocol_model.system.topology import InterfaceConnection, VirtualDutPortRef
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.fabric.projection import (
    ADDRESS_ROUTER_PROJECTION,
    AddressRouterBoundaryProjection,
)

from .policy import DiagramDetail
from .view import (
    EvidenceBasis,
    ProjectionIntent,
    TimeBasis,
    ViewDescriptor,
    ViewKind,
    ViewScope,
)


ADDRESS_INTERCONNECT_VIEW_SCHEMA = (
    "protocol-model.address-interconnect-view/v1"
)


class InterconnectSide(str, Enum):
    INGRESS = "ingress"
    EGRESS = "egress"


class AddressInterconnectFactSource(str, Enum):
    """Which explicit declaration supplied the router boundary facts."""

    SYSTEM_CONTRACT = "system_contract"
    BACKEND_PROJECTION = "backend_projection"
    SYSTEM_CONTRACT_AND_BACKEND_PROJECTION = (
        "system_contract_and_backend_projection"
    )


@dataclass(frozen=True)
class RouteWindowView:
    """One route window, optionally enriched by system resolution."""

    ref: str
    route: str
    input_base_address: int
    output_base_address: int
    size_bytes: int
    receiver: VirtualDutPortRef | None = None
    claim: str | None = None

    def __post_init__(self) -> None:
        if not self.ref or not self.route:
            raise ValueError("route window view requires a stable ref and name")
        for value, subject in (
            (self.input_base_address, "input base"),
            (self.output_base_address, "output base"),
            (self.size_bytes, "size"),
        ):
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"route window {subject} must be an integer")
        if self.input_base_address < 0 or self.output_base_address < 0:
            raise ValueError("route window bases must be non-negative")
        if self.size_bytes <= 0:
            raise ValueError("route window size must be positive")
        if self.receiver is not None and not isinstance(
            self.receiver, VirtualDutPortRef
        ):
            raise TypeError("route window receiver requires VirtualDutPortRef")
        if self.claim is not None and (
            not isinstance(self.claim, str) or not self.claim
        ):
            raise ValueError("route window claim must be a non-empty string")


@dataclass(frozen=True)
class InterfaceMapPortView:
    """One real interconnect port and the peer port connected to it."""

    ref: str
    side: InterconnectSide
    fabric_port: VirtualDutPortRef
    fabric_role: str
    peer_port: VirtualDutPortRef
    peer_role: str
    connection: str
    protocol_name: str
    interface_family: str
    enabled_events: tuple[str, ...]
    route_windows: tuple[RouteWindowView, ...] = ()
    fabric_clock_domain: str | None = None
    fabric_reset_domain: str | None = None
    peer_clock_domain: str | None = None
    peer_reset_domain: str | None = None
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.ref or not self.connection or not self.protocol_name:
            raise ValueError(
                "interface-map port requires ref, connection, and protocol"
            )
        if not isinstance(self.fabric_port, VirtualDutPortRef) or not isinstance(
            self.peer_port, VirtualDutPortRef
        ):
            raise TypeError("interface-map endpoints require VirtualDutPortRef")
        if not self.fabric_role or not self.peer_role or not self.interface_family:
            raise ValueError("interface-map port requires roles and a family")
        object.__setattr__(self, "side", InterconnectSide(self.side))
        object.__setattr__(self, "enabled_events", tuple(self.enabled_events))
        object.__setattr__(self, "route_windows", tuple(self.route_windows))
        if any(
            not isinstance(name, str) or not name for name in self.enabled_events
        ):
            raise ValueError("interface-map enabled events must be named")
        if any(
            not isinstance(route, RouteWindowView)
            for route in self.route_windows
        ):
            raise TypeError("interface-map routes require RouteWindowView")
        object.__setattr__(
            self, "parameters", MappingProxyType(dict(self.parameters))
        )


@dataclass(frozen=True)
class AddressInterconnectView:
    """Protocol-independent N-ingress/M-egress interface-map facts."""

    system: str
    interconnect: str
    fact_source: AddressInterconnectFactSource
    evidence_basis: EvidenceBasis
    ingress: tuple[InterfaceMapPortView, ...]
    egress: tuple[InterfaceMapPortView, ...]

    def __post_init__(self) -> None:
        if not self.system or not self.interconnect:
            raise ValueError("address interconnect view requires system and DUT")
        object.__setattr__(
            self, "fact_source", AddressInterconnectFactSource(self.fact_source)
        )
        object.__setattr__(
            self, "evidence_basis", EvidenceBasis(self.evidence_basis)
        )
        object.__setattr__(self, "ingress", tuple(self.ingress))
        object.__setattr__(self, "egress", tuple(self.egress))
        if not self.ingress or not self.egress:
            raise ValueError("address interconnect view requires both sides")
        if any(
            not isinstance(item, InterfaceMapPortView)
            for item in (*self.ingress, *self.egress)
        ):
            raise TypeError(
                "address interconnect sides require InterfaceMapPortView"
            )
        if any(item.side is not InterconnectSide.INGRESS for item in self.ingress):
            raise ValueError("address interconnect ingress contains an egress")
        if any(item.side is not InterconnectSide.EGRESS for item in self.egress):
            raise ValueError("address interconnect egress contains an ingress")
        refs = [item.ref for item in (*self.ingress, *self.egress)]
        if len(set(refs)) != len(refs):
            raise ValueError("address interconnect port refs must be unique")

    def descriptor(
        self, *, detail: DiagramDetail = DiagramDetail.STANDARD
    ) -> ViewDescriptor:
        return ViewDescriptor(
            view_kind=ViewKind.INTERCONNECT_INTERFACE_MAP,
            scope=ViewScope.SYSTEM,
            evidence_basis=self.evidence_basis,
            source_schema=ADDRESS_INTERCONNECT_VIEW_SCHEMA,
            projection_intent=ProjectionIntent.DIRECT,
            time_basis=TimeBasis.NONE,
            detail=detail,
        )


def _router_contract(system: SystemProtocol, interconnect: str):
    address_map = system.address_map
    if address_map is None:
        return None
    matches = tuple(
        item for item in address_map.routers if item.router == interconnect
    )
    if len(matches) > 1:
        raise ValueError(
            f"multiple address-router contracts reference {interconnect!r}"
        )
    return None if not matches else matches[0]


def _backend_projection(system: SystemProtocol, interconnect: str):
    dut = system.virtual_duts[interconnect]
    if dut.backend is None:
        return None
    projection = dut.backend.boundary_projections().get(
        ADDRESS_ROUTER_PROJECTION
    )
    if projection is not None and not isinstance(
        projection, AddressRouterBoundaryProjection
    ):
        raise TypeError("address-router boundary projection has an invalid type")
    return projection


def _connected_port(
    system: SystemProtocol,
    reference: VirtualDutPortRef,
) -> tuple[str, InterfaceConnection, str, str, VirtualDutPortRef]:
    matches: list[
        tuple[str, InterfaceConnection, str, str, VirtualDutPortRef]
    ] = []
    for name, connection in system.connections.items():
        if not isinstance(connection, InterfaceConnection):
            continue
        local = tuple(
            (role, endpoint)
            for role, endpoint in connection.endpoints.items()
            if endpoint == reference
        )
        if not local:
            continue
        if len(local) != 1 or len(connection.endpoints) != 2:
            raise ValueError(
                "address interconnect view currently requires binary "
                f"connections at {reference.qualified_name!r}"
            )
        local_role, _ = local[0]
        peers = tuple(
            (role, endpoint)
            for role, endpoint in connection.endpoints.items()
            if endpoint != reference
        )
        if len(peers) != 1:
            raise ValueError(
                f"cannot identify one peer for {reference.qualified_name!r}"
            )
        peer_role, peer = peers[0]
        matches.append((name, connection, local_role, peer_role, peer))
    if len(matches) != 1:
        raise ValueError(
            f"address interconnect port {reference.qualified_name!r} requires "
            f"exactly one InterfaceConnection, found {len(matches)}"
        )
    return matches[0]


def _route_views(
    interconnect: str,
    routes,
    *,
    contract_name: str | None,
    address_plan,
) -> Mapping[str, tuple[RouteWindowView, ...]]:
    by_egress: dict[str, list[RouteWindowView]] = {}
    for route in routes:
        receiver = None
        claim = None
        output_base = (
            route.base_address
            if route.output_base_address is None
            else route.output_base_address
        )
        if address_plan is not None and contract_name is not None:
            paths = tuple(
                path
                for path in address_plan.paths
                if path.router_contract == contract_name
                and path.route == route.name
            )
            if not paths:
                raise ValueError(
                    f"resolved address plan has no path for route {route.name!r}"
                )
            receivers = {path.receiver for path in paths}
            claims = {path.claim.name for path in paths}
            output_windows = {
                (path.output_window.base_address, path.output_window.size_bytes)
                for path in paths
            }
            if len(receivers) != 1 or len(claims) != 1 or len(output_windows) != 1:
                raise ValueError(
                    f"route {route.name!r} resolves inconsistently across ingresses"
                )
            receiver = next(iter(receivers))
            claim = next(iter(claims))
            output_base, resolved_size = next(iter(output_windows))
            if resolved_size != route.size_bytes:
                raise ValueError(
                    f"route {route.name!r} resolved with a different size"
                )
        view = RouteWindowView(
            ref=f"route:{interconnect}/{route.name}",
            route=route.name,
            input_base_address=route.base_address,
            output_base_address=output_base,
            size_bytes=route.size_bytes,
            receiver=receiver,
            claim=claim,
        )
        by_egress.setdefault(route.egress_port, []).append(view)
    return MappingProxyType(
        {name: tuple(values) for name, values in by_egress.items()}
    )


def _port_view(
    system: SystemProtocol,
    interconnect: str,
    port_name: str,
    side: InterconnectSide,
    route_windows: tuple[RouteWindowView, ...],
) -> InterfaceMapPortView:
    fabric_ref = VirtualDutPortRef(interconnect, port_name)
    connection_name, connection, fabric_role, peer_role, peer_ref = (
        _connected_port(system, fabric_ref)
    )
    fabric_port = system.virtual_duts[interconnect].port(port_name)
    peer_port = system.virtual_duts[peer_ref.dut].port(peer_ref.port)
    if not isinstance(fabric_port, InterfacePort) or not isinstance(
        peer_port, InterfacePort
    ):
        raise TypeError("address interconnect map requires InterfacePort values")
    if fabric_port.role != fabric_role or peer_port.role != peer_role:
        raise ValueError(
            f"connection {connection_name!r} role disagrees with a port declaration"
        )
    if (
        fabric_port.protocol != connection.protocol
        or peer_port.protocol != connection.protocol
    ):
        raise ValueError(
            f"connection {connection_name!r} protocol disagrees with a port"
        )
    return InterfaceMapPortView(
        ref=f"port:{fabric_ref.qualified_name}",
        side=side,
        fabric_port=fabric_ref,
        fabric_role=fabric_role,
        peer_port=peer_ref,
        peer_role=peer_role,
        connection=connection_name,
        protocol_name=connection.protocol.name,
        interface_family=connection.protocol.interface_family,
        enabled_events=tuple(sorted(connection.protocol.enabled_event_kinds)),
        route_windows=route_windows,
        fabric_clock_domain=fabric_port.clock_domain,
        fabric_reset_domain=fabric_port.reset_domain,
        peer_clock_domain=peer_port.clock_domain,
        peer_reset_domain=peer_port.reset_domain,
        parameters=connection.parameters,
    )


def project_address_interconnect(
    source: SystemProtocol | ElaboratedSystemProtocol,
    *,
    interconnect: str,
) -> AddressInterconnectView:
    """Project one explicitly declared address router into a typed view.

    Passing an ``ElaboratedSystemProtocol`` enriches route windows with the
    resolved receiver and claim.  Passing a declaration preserves a declared
    or backend-projected view and does not silently elaborate the system.
    """

    if isinstance(source, ElaboratedSystemProtocol):
        system = source.spec
        address_plan = source.address_plan
    elif isinstance(source, SystemProtocol):
        system = source
        address_plan = None
    else:
        raise TypeError(
            "address interconnect projection requires SystemProtocol or "
            "ElaboratedSystemProtocol"
        )
    if interconnect not in system.virtual_duts:
        raise ValueError(
            f"address interconnect view references unknown DUT {interconnect!r}"
        )

    contract = _router_contract(system, interconnect)
    backend_projection = _backend_projection(system, interconnect)
    if contract is None and backend_projection is None:
        raise ValueError(
            f"VirtualDut {interconnect!r} has no address-router contract or "
            "boundary projection"
        )
    if contract is not None:
        selected = AddressRouterBoundaryProjection(
            contract.ingress_ports,
            contract.egress_ports,
            contract.routes,
        )
        if backend_projection is not None and backend_projection != selected:
            raise ValueError(
                f"address-router contract and backend disagree for {interconnect!r}"
            )
        fact_source = (
            AddressInterconnectFactSource.SYSTEM_CONTRACT
            if backend_projection is None
            else (
                AddressInterconnectFactSource
                .SYSTEM_CONTRACT_AND_BACKEND_PROJECTION
            )
        )
    else:
        assert backend_projection is not None
        selected = backend_projection
        fact_source = AddressInterconnectFactSource.BACKEND_PROJECTION

    contract_name = None if contract is None else contract.name
    if address_plan is not None and contract is None:
        address_plan = None
    route_views = _route_views(
        interconnect,
        selected.routes,
        contract_name=contract_name,
        address_plan=address_plan,
    )
    ingress = tuple(
        _port_view(
            system,
            interconnect,
            port_name,
            InterconnectSide.INGRESS,
            (),
        )
        for port_name in selected.ingress_ports
    )
    egress = tuple(
        _port_view(
            system,
            interconnect,
            port_name,
            InterconnectSide.EGRESS,
            route_views.get(port_name, ()),
        )
        for port_name in selected.egress_ports
    )
    return AddressInterconnectView(
        system.name,
        interconnect,
        fact_source,
        (
            EvidenceBasis.RESOLVED
            if address_plan is not None
            else EvidenceBasis.DECLARED
        ),
        ingress,
        egress,
    )


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _address_interval(base: int, size: int) -> str:
    return f"0x{base:x}..0x{base + size - 1:x}"


def _route_label(route: RouteWindowView, *, diagnostic: bool) -> str:
    source = _address_interval(route.input_base_address, route.size_bytes)
    target = _address_interval(route.output_base_address, route.size_bytes)
    label = source if source == target else f"{source} → {target}"
    if diagnostic:
        label = f"{route.route}: {label}"
        if route.receiver is not None:
            label += f" → {route.receiver.qualified_name}"
        if route.claim is not None:
            label += f" [{route.claim}]"
    return label


def _endpoint_label(
    item: InterfaceMapPortView,
    detail: DiagramDetail,
) -> str:
    lines = [item.peer_port.dut]
    if detail is not DiagramDetail.OVERVIEW:
        lines.append(f"{item.peer_port.port} · {item.peer_role}")
    if detail is DiagramDetail.DIAGNOSTIC:
        lines.extend(
            (
                f"connection: {item.connection}",
                f"family: {item.interface_family}",
                "events: " + ", ".join(item.enabled_events),
            )
        )
        domains = []
        if item.peer_clock_domain is not None:
            domains.append(f"peer clock={item.peer_clock_domain}")
        if item.peer_reset_domain is not None:
            domains.append(f"peer reset={item.peer_reset_domain}")
        if domains:
            lines.append(" · ".join(domains))
    if item.side is InterconnectSide.EGRESS and item.route_windows:
        windows = item.route_windows
        if detail is DiagramDetail.STANDARD:
            windows = windows[:2]
        if detail is not DiagramDetail.OVERVIEW:
            lines.extend(
                _route_label(
                    route, diagnostic=detail is DiagramDetail.DIAGNOSTIC
                )
                for route in windows
            )
            if detail is DiagramDetail.STANDARD and len(item.route_windows) > 2:
                lines.append(f"+{len(item.route_windows) - 2} windows")
    return "\n".join(lines)


def _port_cell(
    item: InterfaceMapPortView,
    detail: DiagramDetail,
    *,
    colspan: int,
    port_id: str,
) -> str:
    if detail is DiagramDetail.OVERVIEW:
        label = escape(item.fabric_role)
    elif detail is DiagramDetail.DIAGNOSTIC:
        domains = []
        if item.fabric_clock_domain is not None:
            domains.append(f"clock={item.fabric_clock_domain}")
        if item.fabric_reset_domain is not None:
            domains.append(f"reset={item.fabric_reset_domain}")
        domain_label = ""
        if domains:
            domain_label = (
                '<BR/><FONT POINT-SIZE="8">fabric '
                + escape(" · ".join(domains))
                + "</FONT>"
            )
        label = (
            f"{escape(item.fabric_port.port)} · "
            f"{escape(item.fabric_role)}<BR/>"
            f'<FONT POINT-SIZE="8">{escape(item.connection)}</FONT>'
            f"{domain_label}"
        )
    else:
        label = (
            f"{escape(item.fabric_port.port)}<BR/>"
            f"{escape(item.fabric_role)}"
        )
    return (
        f'<TD PORT="{port_id}" COLSPAN="{colspan}" BGCOLOR="#dbeafe" '
        f'CELLPADDING="6">{label}</TD>'
    )


def interconnect_interface_map_dot(
    view: AddressInterconnectView,
    *,
    detail: DiagramDetail = DiagramDetail.STANDARD,
    title: str | None = None,
) -> str:
    """Serialize an N×M interconnect boundary view to Graphviz DOT.

    The central rectangle is a presentation of one real VirtualDut.  It does
    not claim a physical shared bus, crosspoint count, or internal lane count.
    """

    if not isinstance(view, AddressInterconnectView):
        raise TypeError("interconnect renderer requires AddressInterconnectView")
    detail = DiagramDetail(detail)
    columns = lcm(len(view.ingress), len(view.egress))
    ingress_span = columns // len(view.ingress)
    egress_span = columns // len(view.egress)
    ingress_cells = "".join(
        _port_cell(
            item,
            detail,
            colspan=ingress_span,
            port_id=f"ingress{index}",
        )
        for index, item in enumerate(view.ingress)
    )
    egress_cells = "".join(
        _port_cell(
            item,
            detail,
            colspan=egress_span,
            port_id=f"egress{index}",
        )
        for index, item in enumerate(view.egress)
    )
    if detail is DiagramDetail.OVERVIEW:
        body = f"{len(view.ingress)} × {len(view.egress)} interconnect"
    elif detail is DiagramDetail.DIAGNOSTIC:
        body = (
            f"{len(view.ingress)} ingress × {len(view.egress)} egress<BR/>"
            f'<FONT POINT-SIZE="9">facts: {escape(view.fact_source.value)} · '
            f"evidence: {escape(view.evidence_basis.value)}</FONT>"
        )
    else:
        body = (
            f"{len(view.ingress)} ingress × {len(view.egress)} egress<BR/>"
            '<FONT POINT-SIZE="9">address route boundary</FONT>'
        )

    lines = [
        "digraph interconnect_interface_map {",
        "  rankdir=TB;",
        f"  label={_quoted(title or view.system + ' · interconnect interface map')};",
        '  labelloc="t";',
        '  graph [bgcolor="white", pad=0.28, nodesep=0.5, ranksep=0.72, '
        'splines=polyline, ordering=out];',
        '  node [fontname="sans-serif", fontsize=10, shape=box, '
        'style="rounded,filled", fillcolor="#ffffff", margin="0.14,0.09"];',
        '  edge [fontname="sans-serif", fontsize=8, color="#52606d", '
        'penwidth=2.0];',
        '  fabric [shape=plain, '
        f'id={_quoted("dut:" + view.interconnect)}, label=<<TABLE BORDER="1" '
        'CELLBORDER="1" CELLSPACING="0" CELLPADDING="0" COLOR="#ea580c">',
        f'    <TR><TD COLSPAN="{columns}" BGCOLOR="#ffedd5" CELLPADDING="7">'
        f"<B>{escape(view.interconnect)} · VirtualDut</B></TD></TR>",
        f"    <TR>{ingress_cells}</TR>",
        f'    <TR><TD COLSPAN="{columns}" BGCOLOR="#fff7ed" '
        f'CELLPADDING="8">{body}</TD></TR>',
        f"    <TR>{egress_cells}</TR>",
        "  </TABLE>>];",
    ]

    ingress_nodes: list[str] = []
    egress_nodes: list[str] = []
    for side, items in (
        (InterconnectSide.INGRESS, view.ingress),
        (InterconnectSide.EGRESS, view.egress),
    ):
        for index, item in enumerate(items):
            prefix = "ingress_peer" if side is InterconnectSide.INGRESS else "egress_peer"
            node_id = f"{prefix}{index}"
            fill = "#eff6ff" if side is InterconnectSide.INGRESS else "#ecfdf5"
            color = "#2563eb" if side is InterconnectSide.INGRESS else "#059669"
            lines.append(
                f"  {node_id} [id={_quoted('port:' + item.peer_port.qualified_name)}, "
                f"fillcolor={_quoted(fill)}, color={_quoted(color)}, "
                f"label={_quoted(_endpoint_label(item, detail))}];"
            )
            edge_label = item.protocol_name
            if detail is DiagramDetail.DIAGNOSTIC:
                edge_label += f"\n{item.connection}"
                if item.parameters:
                    edge_label += "\nparameters: " + ", ".join(
                        f"{name}={value}"
                        for name, value in sorted(item.parameters.items())
                    )
            edge_id = f"connection:{item.connection}"
            if side is InterconnectSide.INGRESS:
                ingress_nodes.append(node_id)
                lines.append(
                    f"  {node_id} -> fabric:ingress{index}:n [dir=none, "
                    f"id={_quoted(edge_id)}, label={_quoted(edge_label)}];"
                )
            else:
                egress_nodes.append(node_id)
                lines.append(
                    f"  fabric:egress{index}:s -> {node_id} [dir=none, "
                    f"id={_quoted(edge_id)}, label={_quoted(edge_label)}];"
                )
    lines.append(f"  {{ rank=source; {'; '.join(ingress_nodes)}; }}")
    lines.append(f"  {{ rank=sink; {'; '.join(egress_nodes)}; }}")
    for nodes in (ingress_nodes, egress_nodes):
        for left, right in zip(nodes, nodes[1:]):
            lines.append(
                f"  {left} -> {right} [style=invis, weight=80];"
            )
    if detail is DiagramDetail.DIAGNOSTIC:
        lines.extend(
            (
                '  note [shape=note, fillcolor="#f8fafc", color="#64748b", '
                'label="boundary projection only\\ninternal lanes/crosspoints '
                'are not inferred"];',
                "  fabric -> note [style=invis];",
            )
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


def address_interconnect_map_dot(
    source: SystemProtocol | ElaboratedSystemProtocol,
    *,
    interconnect: str,
    detail: DiagramDetail = DiagramDetail.STANDARD,
    title: str | None = None,
) -> str:
    """Project and serialize one address interconnect in a single call."""

    return interconnect_interface_map_dot(
        project_address_interconnect(source, interconnect=interconnect),
        detail=detail,
        title=title,
    )


__all__ = [
    "ADDRESS_INTERCONNECT_VIEW_SCHEMA",
    "AddressInterconnectFactSource",
    "AddressInterconnectView",
    "InterfaceMapPortView",
    "InterconnectSide",
    "RouteWindowView",
    "address_interconnect_map_dot",
    "interconnect_interface_map_dot",
    "project_address_interconnect",
]
