"""One composition root for the supported serial AMBA bridge profiles."""

from __future__ import annotations

from typing import Mapping

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.boundary import VirtualDut
from protocol_model.virtual_dut.fabric import AddressRoute

from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4BurstAssemblyProfile,
)

from .serial_address import build_amba_serial_address_bridge_vdut
from .serial_burst import build_amba_serial_burst_bridge_vdut


def build_amba_serial_bridge_vdut(
    name: str,
    ingress_protocol: InterfaceProtocol,
    egress_protocol: InterfaceProtocol,
    routes: tuple[AddressRoute, ...],
    *,
    ingress_port: str = "ingress",
    egress_port: str = "egress",
    parent_capacity: int = 8,
    assembly_profile: Axi4BurstAssemblyProfile | None = None,
    axi_wire_id: int = 0,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
    capabilities: Mapping[str, object] | None = None,
) -> VirtualDut:
    """Select the typed serial profile from the ingress operation shape.

    Full AXI4 ingress needs AW/W assembly and burst fan-out.  AXI4-Lite,
    AHB, and APB ingress already decode to one address access and use the
    single-access path.  Egress selection remains delegated to the common
    AMBA requester factory, so this function does not enumerate protocol
    pairs.
    """

    if not isinstance(ingress_protocol, InterfaceProtocol) or not isinstance(
        egress_protocol, InterfaceProtocol
    ):
        raise TypeError("AMBA serial bridge requires two InterfaceProtocol values")
    common = {
        "ingress_port": ingress_port,
        "egress_port": egress_port,
        "parent_capacity": parent_capacity,
        "axi_wire_id": axi_wire_id,
        "byte_order": byte_order,
        "capabilities": capabilities,
    }
    if ingress_protocol.interface_family == AXI4_FAMILY:
        return build_amba_serial_burst_bridge_vdut(
            name,
            ingress_protocol,
            egress_protocol,
            routes,
            assembly_profile=assembly_profile,
            **common,
        )
    if assembly_profile is not None:
        raise ValueError(
            "AXI4 burst assembly profile is only meaningful for full AXI4 "
            "ingress"
        )
    return build_amba_serial_address_bridge_vdut(
        name,
        ingress_protocol,
        egress_protocol,
        routes,
        **common,
    )


__all__ = ["build_amba_serial_bridge_vdut"]
