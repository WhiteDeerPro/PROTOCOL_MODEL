"""AXI4 channel-preserving bindings for transaction-level fabrics."""

from __future__ import annotations

from typing import Mapping

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.virtual_dut.attachments import (
    CanonicalEventRelayAttachment,
)
from protocol_model.virtual_dut.binding import (
    InterfaceAttachmentBinding,
    VirtualDutBuilder,
)
from protocol_model.virtual_dut.boundary.module import (
    DutBehaviorTag,
    VirtualDut,
)
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.fabric.route import AddressRoute

from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4BurstAssemblyProfile,
)
from protocol_model.integrations.backends.amba.axi.axi4.read import (
    Axi4ReadCrossbarBackend,
    Axi4ReadRouteTableProfile,
)
from protocol_model.integrations.backends.amba.axi.axi4.write import (
    Axi4WriteCrossbarBackend,
    Axi4WriteRouteTableProfile,
)


def _port_names(names: tuple[str, ...], *, subject: str) -> tuple[str, ...]:
    normalized = tuple(names)
    if not normalized:
        raise ValueError(f"AXI4 read fabric requires {subject} ports")
    if any(not isinstance(name, str) or not name for name in normalized):
        raise ValueError(f"AXI4 read fabric {subject} names must be non-empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"AXI4 read fabric {subject} names must be unique")
    return normalized


def _binding(
    name: str,
    protocol: InterfaceProtocol,
    role: str,
    capability: object | None,
) -> InterfaceAttachmentBinding:
    attachment = CanonicalEventRelayAttachment(protocol, role)
    return InterfaceAttachmentBinding(
        InterfacePort(name, protocol, role, capability=capability),
        attachment,
    )


def build_axi4_read_demux_vdut(
    name: str,
    protocol: InterfaceProtocol,
    egress_ports: tuple[str, ...],
    routes: tuple[AddressRoute, ...],
    *,
    ingress_port: str = "s_axi",
    table_profile: Axi4ReadRouteTableProfile | None = None,
    capabilities: Mapping[str, object] | None = None,
) -> VirtualDut:
    """Construct the read-only slice of one AXI4 manager-to-M-device fabric.

    The protocol must expose only AR/R or explicitly forbid every other event
    kind.  A five-channel ``build_axi4_read_only_profile()`` therefore retains
    the AXI boundary shape without promising AW/W/B behavior.  Internally, the
    backend routes AR and uses a bounded RID destination-lock table to return
    R.
    """

    if protocol.interface_family != AXI4_FAMILY:
        raise ValueError("AXI4 read demux requires an AXI4 interface family")
    if not {"AR", "R"}.issubset(protocol.event_kinds):
        raise ValueError("AXI4 read demux requires AR and R event kinds")
    if not isinstance(ingress_port, str) or not ingress_port:
        raise ValueError("AXI4 read demux ingress name must be non-empty")
    egress_names = _port_names(egress_ports, subject="egress")
    if ingress_port in egress_names:
        raise ValueError("AXI4 read demux ingress and egress names overlap")

    capability_by_port = dict(capabilities or {})
    all_ports = {ingress_port, *egress_names}
    unknown_capabilities = set(capability_by_port) - all_ports
    if unknown_capabilities:
        raise ValueError(
            "capabilities reference unknown AXI4 read demux ports: "
            f"{sorted(unknown_capabilities)!r}"
        )

    ingress_binding = _binding(
        ingress_port,
        protocol,
        "subordinate",
        capability_by_port.get(ingress_port),
    )
    egress_bindings = {
        port: _binding(
            port,
            protocol,
            "manager",
            capability_by_port.get(port),
        )
        for port in egress_names
    }
    backend = Axi4ReadCrossbarBackend(
        {ingress_binding.name: ingress_binding},
        egress_bindings,
        routes,
        table_profile=table_profile,
    )
    builder = (
        VirtualDutBuilder(name)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.ROUTING)
        .describe(
            "AXI4 read demultiplexer "
            "(bounded RID destination-lock table + R return)"
        )
        .bind(ingress_binding)
    )
    for binding in egress_bindings.values():
        builder.bind(binding)
    return builder.build()


def build_axi4_read_crossbar_vdut(
    name: str,
    protocol: InterfaceProtocol,
    ingress_ports: tuple[str, ...],
    egress_ports: tuple[str, ...],
    routes: tuple[AddressRoute, ...],
    *,
    table_profile: Axi4ReadRouteTableProfile | None = None,
    capabilities: Mapping[str, object] | None = None,
) -> VirtualDut:
    """Construct a transaction-level AXI4 read-only AR/R N×M crossbar.

    The protocol must expose only AR/R or explicitly forbid every other event
    kind.  Canonical AR events are already accepted transactions, so their
    caller order is the grant order of one execution witness.  The backend
    preserves raw downstream IDs, derives manager-local destination locks and
    subordinate-local return-owner FIFOs from one pending-burst ledger, and
    forwards each R beat to its original ingress.  Arbitration-algorithm
    experiments can later refine admission without changing this ownership
    contract.
    """

    if protocol.interface_family != AXI4_FAMILY:
        raise ValueError("AXI4 read crossbar requires an AXI4 interface family")
    if not {"AR", "R"}.issubset(protocol.event_kinds):
        raise ValueError("AXI4 read crossbar requires AR and R event kinds")
    ingress_names = _port_names(ingress_ports, subject="ingress")
    egress_names = _port_names(egress_ports, subject="egress")
    overlap = set(ingress_names).intersection(egress_names)
    if overlap:
        raise ValueError(
            "AXI4 read crossbar ingress and egress names overlap: "
            f"{sorted(overlap)!r}"
        )

    capability_by_port = dict(capabilities or {})
    all_ports = {*ingress_names, *egress_names}
    unknown_capabilities = set(capability_by_port) - all_ports
    if unknown_capabilities:
        raise ValueError(
            "capabilities reference unknown AXI4 read crossbar ports: "
            f"{sorted(unknown_capabilities)!r}"
        )

    ingress_bindings = {
        port: _binding(
            port,
            protocol,
            "subordinate",
            capability_by_port.get(port),
        )
        for port in ingress_names
    }
    egress_bindings = {
        port: _binding(
            port,
            protocol,
            "manager",
            capability_by_port.get(port),
        )
        for port in egress_names
    }
    backend = Axi4ReadCrossbarBackend(
        ingress_bindings,
        egress_bindings,
        routes,
        table_profile=table_profile,
    )
    builder = (
        VirtualDutBuilder(name)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.ROUTING)
        .describe(
            "AXI4 read crossbar "
            "(N×M route + raw-ID serialized return ownership)"
        )
    )
    for binding in (*ingress_bindings.values(), *egress_bindings.values()):
        builder.bind(binding)
    return builder.build()


def build_axi4_write_crossbar_vdut(
    name: str,
    protocol: InterfaceProtocol,
    ingress_ports: tuple[str, ...],
    egress_ports: tuple[str, ...],
    routes: tuple[AddressRoute, ...],
    *,
    assembly_profile: Axi4BurstAssemblyProfile | None = None,
    table_profile: Axi4WriteRouteTableProfile | None = None,
    capabilities: Mapping[str, object] | None = None,
) -> VirtualDut:
    """Construct a transaction-level AXI4 write-only AW/W/B N×M crossbar.

    Each ingress assembles ID-less W data with AW descriptors in acceptance
    order.  A complete burst is forwarded as one store-and-forward batch;
    the backend retains raw-ID destination locks and B return ownership until
    completion.  This profile deliberately leaves pin-cycle cut-through and
    READY generation to a later refinement.
    """

    if protocol.interface_family != AXI4_FAMILY:
        raise ValueError("AXI4 write crossbar requires an AXI4 interface family")
    if not {"AW", "W", "B"}.issubset(protocol.event_kinds):
        raise ValueError("AXI4 write crossbar requires AW, W, and B event kinds")
    ingress_names = _port_names(ingress_ports, subject="ingress")
    egress_names = _port_names(egress_ports, subject="egress")
    overlap = set(ingress_names).intersection(egress_names)
    if overlap:
        raise ValueError(
            "AXI4 write crossbar ingress and egress names overlap: "
            f"{sorted(overlap)!r}"
        )

    capability_by_port = dict(capabilities or {})
    all_ports = {*ingress_names, *egress_names}
    unknown_capabilities = set(capability_by_port) - all_ports
    if unknown_capabilities:
        raise ValueError(
            "capabilities reference unknown AXI4 write crossbar ports: "
            f"{sorted(unknown_capabilities)!r}"
        )

    ingress_bindings = {
        port: _binding(
            port,
            protocol,
            "subordinate",
            capability_by_port.get(port),
        )
        for port in ingress_names
    }
    egress_bindings = {
        port: _binding(
            port,
            protocol,
            "manager",
            capability_by_port.get(port),
        )
        for port in egress_names
    }
    backend = Axi4WriteCrossbarBackend(
        ingress_bindings,
        egress_bindings,
        routes,
        assembly_profile=assembly_profile,
        table_profile=table_profile,
    )
    builder = (
        VirtualDutBuilder(name)
        .with_backend(backend)
        .with_behavior_tags(DutBehaviorTag.ROUTING)
        .describe(
            "AXI4 write crossbar "
            "(N×M store-and-forward AW/W + raw-ID B ownership)"
        )
    )
    for binding in (*ingress_bindings.values(), *egress_bindings.values()):
        builder.bind(binding)
    return builder.build()


__all__ = [
    "Axi4BurstAssemblyProfile",
    "Axi4ReadRouteTableProfile",
    "Axi4WriteRouteTableProfile",
    "build_axi4_read_crossbar_vdut",
    "build_axi4_read_demux_vdut",
    "build_axi4_write_crossbar_vdut",
]
