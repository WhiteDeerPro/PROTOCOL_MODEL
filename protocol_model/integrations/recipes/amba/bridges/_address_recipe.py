"""Shared endpoint and shape selection for AMBA address bridges."""

from __future__ import annotations

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.ahb import AHB_FAMILY
from protocol_model.protocols.amba.apb import APB_FAMILY
from protocol_model.protocols.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.protocols.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.fabric.route import AddressRoute
from protocol_model.virtual_dut.translation.address import (
    AddressShapeGuardStage,
)

from protocol_model.integrations.attachments.amba.ahb import (
    AhbRequesterAttachment,
)
from protocol_model.integrations.attachments.amba.apb import (
    ApbRequesterAttachment,
)
from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4RequesterAttachment,
)
from protocol_model.integrations.attachments.amba.axi.axi4_lite import (
    Axi4LiteRequesterAttachment,
)


AMBA_ADDRESS_EGRESS_FAMILIES = frozenset(
    (AXI4_FAMILY, AXI4_LITE_FAMILY, AHB_FAMILY, APB_FAMILY)
)


def validate_amba_route_address_widths(
    routes: tuple[AddressRoute, ...],
    ingress_protocol: InterfaceProtocol,
    egress_protocol: InterfaceProtocol,
) -> None:
    """Reject route windows that either bound interface cannot represent."""

    ingress_limit = 1 << int(ingress_protocol.parameters["address_width"])
    egress_limit = 1 << int(egress_protocol.parameters["address_width"])
    for route in routes:
        if route.limit_address > ingress_limit:
            raise ValueError(
                f"address route {route.name!r} exceeds the ingress address width"
            )
        output_base = (
            route.base_address
            if route.output_base_address is None
            else route.output_base_address
        )
        if output_base + route.size_bytes > egress_limit:
            raise ValueError(
                f"address route {route.name!r} exceeds the egress address width "
                "after remapping"
            )


def amba_address_requester_attachment(
    protocol: InterfaceProtocol,
    byte_order: ByteOrder,
    *,
    axi_wire_id: int,
):
    """Select an address requester from the target interface family."""

    if protocol.interface_family == AXI4_FAMILY:
        return Axi4RequesterAttachment(
            protocol, wire_id=axi_wire_id, byte_order=byte_order
        )
    if protocol.interface_family == AXI4_LITE_FAMILY:
        return Axi4LiteRequesterAttachment(protocol, byte_order=byte_order)
    if protocol.interface_family == AHB_FAMILY:
        return AhbRequesterAttachment(protocol, byte_order=byte_order)
    if protocol.interface_family == APB_FAMILY:
        return ApbRequesterAttachment(protocol)
    raise ValueError(
        f"no single-access AMBA requester for family {protocol.interface_family!r}"
    )


def amba_target_shape_stage(
    protocol: InterfaceProtocol, *, name: str
) -> AddressShapeGuardStage:
    """Describe the access geometry accepted by one requester attachment."""

    bus_bytes = int(protocol.parameters["data_width"]) // 8
    address_limit = 1 << int(protocol.parameters["address_width"])
    exact_size = (
        bus_bytes
        if protocol.interface_family in {APB_FAMILY, AXI4_LITE_FAMILY}
        else None
    )

    require_full_write = False
    if protocol.interface_family == APB_FAMILY:
        require_full_write = (
            "strb" not in protocol.event_kinds["WRITE"].schema.fields
        )
    elif protocol.interface_family == AHB_FAMILY:
        require_full_write = (
            "strb" not in protocol.event_kinds["WRITE_DATA"].schema.fields
        )

    return AddressShapeGuardStage(
        bus_bytes,
        exact_size=exact_size,
        require_full_write=require_full_write,
        address_limit=address_limit,
        name=name,
    )


__all__ = [
    "AMBA_ADDRESS_EGRESS_FAMILIES",
    "amba_address_requester_attachment",
    "amba_target_shape_stage",
    "validate_amba_route_address_widths",
]
