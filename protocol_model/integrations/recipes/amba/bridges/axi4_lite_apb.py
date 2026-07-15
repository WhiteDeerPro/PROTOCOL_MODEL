"""Serialized AXI4-Lite subordinate to APB requester bridge recipe."""

from __future__ import annotations

from typing import Mapping

from protocol_model.link import LinkProtocol
from protocol_model.link.amba.apb import APB_FAMILY
from protocol_model.link.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.binding import PortAttachmentBinding, VirtualDutBuilder
from protocol_model.virtual_dut.boundary.module import DutFacet, VirtualDut
from protocol_model.virtual_dut.boundary.port import ProtocolPort
from protocol_model.virtual_dut.fabric.route import AddressRoute
from protocol_model.virtual_dut.fabric.single_ingress import (
    SingleIngressAddressFabricBackend,
)

from protocol_model.integrations.attachments.amba.apb import ApbRequesterAttachment
from protocol_model.integrations.attachments.amba.axi.axi4_lite import (
    Axi4LiteCompleterAttachment,
)


def build_axi4_lite_to_apb_bridge_vdut(
    name: str,
    axi_protocol: LinkProtocol,
    apb_protocol: LinkProtocol,
    routes: tuple[AddressRoute, ...],
    *,
    axi_port: str = "s_axi",
    apb_port: str = "m_apb",
    capabilities: Mapping[str, object] | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Build a one-active-transfer AXI4-Lite to APB address bridge.

    This first profile preserves address and PPROT-compatible protection,
    requires equal data widths, and uses AddressRoute for decode/remap. It is
    a two-port bridge, not a multi-manager crossbar.
    """

    if axi_protocol.family != AXI4_LITE_FAMILY:
        raise ValueError("bridge ingress requires an AXI4-Lite LinkProtocol")
    if apb_protocol.family != APB_FAMILY:
        raise ValueError("bridge egress requires an APB LinkProtocol")
    if int(axi_protocol.parameters["data_width"]) != int(
        apb_protocol.parameters["data_width"]
    ):
        raise ValueError("first AXI4-Lite to APB bridge requires equal data widths")
    request_fields = set(apb_protocol.channels["READ"].event.fields)
    if "prot" not in request_fields:
        raise ValueError("bridge APB profile must expose PPROT as canonical prot")
    if "strb" not in apb_protocol.channels["WRITE"].event.fields:
        raise ValueError("bridge APB profile must expose PSTRB as canonical strb")
    if not routes:
        raise ValueError("AXI4-Lite to APB bridge requires an address route")
    if {item.egress_port for item in routes} != {apb_port}:
        raise ValueError(
            f"all bridge routes must select the sole APB port {apb_port!r}"
        )

    axi_limit = 1 << int(axi_protocol.parameters["address_width"])
    apb_limit = 1 << int(apb_protocol.parameters["address_width"])
    for route in routes:
        if route.limit_address > axi_limit:
            raise ValueError(
                f"route {route.name!r} input window exceeds AXI4-Lite address width"
            )
        output_base = (
            route.base_address
            if route.output_base_address is None
            else route.output_base_address
        )
        if output_base + route.size_bytes > apb_limit:
            raise ValueError(
                f"route {route.name!r} output window exceeds APB address width"
            )

    capability_by_port = dict(capabilities or {})
    unknown = set(capability_by_port) - {axi_port, apb_port}
    if unknown:
        raise ValueError(
            f"capabilities reference unknown bridge ports {sorted(unknown)!r}"
        )

    ingress_attachment = Axi4LiteCompleterAttachment(
        axi_protocol, byte_order=byte_order
    )
    egress_attachment = ApbRequesterAttachment(apb_protocol)
    ingress = PortAttachmentBinding(
        ProtocolPort(
            axi_port,
            axi_protocol,
            ingress_attachment.role,
            capability=capability_by_port.get(axi_port),
        ),
        ingress_attachment,
    )
    egress = PortAttachmentBinding(
        ProtocolPort(
            apb_port,
            apb_protocol,
            egress_attachment.role,
            capability=capability_by_port.get(apb_port),
        ),
        egress_attachment,
    )
    backend = SingleIngressAddressFabricBackend(
        ingress, {apb_port: egress}, routes
    )
    return (
        VirtualDutBuilder(name)
        .bind(ingress)
        .bind(egress)
        .with_model(backend)
        .with_facets(DutFacet.TRANSFORMING, DutFacet.ROUTING)
        .describe(
            "serialized AXI4-Lite subordinate to APB requester address bridge"
        )
        .build()
    )
