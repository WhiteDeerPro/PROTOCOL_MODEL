"""Audited AXI4-to-APB preset over the generic burst builder."""

from __future__ import annotations

from typing import Mapping

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.apb import APB_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.fabric.route import AddressRoute

from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4BurstAssemblyProfile,
)

from .serial_burst import build_amba_serial_burst_bridge_vdut


def build_axi4_to_apb_bridge_vdut(
    name: str,
    axi_protocol: InterfaceProtocol,
    apb_protocol: InterfaceProtocol,
    routes: tuple[AddressRoute, ...],
    *,
    axi_port: str = "s_axi",
    apb_port: str = "m_apb",
    parent_capacity: int = 8,
    assembly_profile: Axi4BurstAssemblyProfile | None = None,
    capabilities: Mapping[str, object] | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Select an APB target while reusing the canonical burst runtime."""

    if apb_protocol.interface_family != APB_FAMILY:
        raise ValueError("bridge egress requires an APB InterfaceProtocol")
    if int(axi_protocol.parameters["data_width"]) != int(
        apb_protocol.parameters["data_width"]
    ):
        raise ValueError("AXI4 to APB preset requires equal data widths")
    if "prot" not in apb_protocol.event_kinds["READ"].schema.fields:
        raise ValueError("AXI4 to APB preset requires PPROT preservation")
    if "strb" not in apb_protocol.event_kinds["WRITE"].schema.fields:
        raise ValueError("AXI4 to APB preset requires PSTRB preservation")
    return build_amba_serial_burst_bridge_vdut(
        name,
        axi_protocol,
        apb_protocol,
        routes,
        ingress_port=axi_port,
        egress_port=apb_port,
        parent_capacity=parent_capacity,
        assembly_profile=assembly_profile,
        byte_order=byte_order,
        capabilities=capabilities,
    )


__all__ = ["build_axi4_to_apb_bridge_vdut"]
