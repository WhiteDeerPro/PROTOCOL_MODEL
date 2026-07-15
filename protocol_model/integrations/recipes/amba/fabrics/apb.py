"""APB-bound address fabric VirtualDut recipes."""

from __future__ import annotations

from typing import Mapping

from protocol_model.link import LinkProtocol
from protocol_model.virtual_dut.attachments.base import ProtocolAttachment
from protocol_model.virtual_dut.binding import (
    PortAttachmentBinding,
    VirtualDutBuilder,
)
from protocol_model.virtual_dut.boundary.module import DutFacet, VirtualDut
from protocol_model.virtual_dut.boundary.port import ProtocolPort
from protocol_model.virtual_dut.fabric.route import AddressRoute
from protocol_model.virtual_dut.fabric.single_ingress import (
    SingleIngressAddressFabricBackend,
)

from protocol_model.integrations.attachments.amba.apb import (
    ApbCompleterAttachment,
    ApbRequesterAttachment,
)


def _binding(
    name: str,
    protocol: LinkProtocol,
    attachment: ProtocolAttachment,
    capability: object | None,
) -> PortAttachmentBinding:
    return PortAttachmentBinding(
        ProtocolPort(name, protocol, attachment.role, capability=capability),
        attachment,
    )


def build_apb_address_fabric_vdut(
    name: str,
    protocol: LinkProtocol,
    routes: tuple[AddressRoute, ...],
    *,
    ingress_port: str = "upstream",
    capabilities: Mapping[str, object] | None = None,
) -> VirtualDut:
    """Construct a synchronous APB decoder and response-mux VirtualDut."""

    address_limit = 1 << int(protocol.parameters["address_width"])
    for route in routes:
        if route.limit_address > address_limit:
            raise ValueError(
                f"route {route.name!r} input window exceeds APB address width"
            )
        output_base = (
            route.base_address
            if route.output_base_address is None
            else route.output_base_address
        )
        if output_base + route.size_bytes > address_limit:
            raise ValueError(
                f"route {route.name!r} output window exceeds APB address width"
            )

    egress_names = tuple(sorted({item.egress_port for item in routes}))
    capability_by_port = dict(capabilities or {})
    port_names = {ingress_port, *egress_names}
    unknown_capabilities = set(capability_by_port) - port_names
    if unknown_capabilities:
        raise ValueError(
            f"capabilities reference unknown fabric ports: "
            f"{sorted(unknown_capabilities)!r}"
        )

    ingress = _binding(
        ingress_port,
        protocol,
        ApbCompleterAttachment(protocol),
        capability_by_port.get(ingress_port),
    )
    egress = {
        port: _binding(
            port,
            protocol,
            ApbRequesterAttachment(protocol),
            capability_by_port.get(port),
        )
        for port in egress_names
    }
    backend = SingleIngressAddressFabricBackend(ingress, egress, routes)
    builder = (
        VirtualDutBuilder(name)
        .bind(ingress)
        .with_model(backend)
        .with_facets(DutFacet.ROUTING)
        .describe("single-ingress APB address fabric (decoder + response mux)")
    )
    for binding in egress.values():
        builder.bind(binding)
    return builder.build()
