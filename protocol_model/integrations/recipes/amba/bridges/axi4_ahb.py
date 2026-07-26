"""Audited AXI4-to-AHB-Lite preset over the generic burst builder."""

from __future__ import annotations

from typing import Mapping

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.ahb import AHB_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.fabric.route import AddressRoute

from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4BurstAssemblyProfile,
)

from .serial_burst import build_amba_serial_burst_bridge_vdut


def build_axi4_to_ahb_lite_bridge_vdut(
    name: str,
    axi_protocol: InterfaceProtocol,
    ahb_protocol: InterfaceProtocol,
    routes: tuple[AddressRoute, ...],
    *,
    axi_port: str = "s_axi",
    ahb_port: str = "m_ahb",
    parent_capacity: int = 8,
    assembly_profile: Axi4BurstAssemblyProfile | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
    capabilities: Mapping[str, object] | None = None,
) -> VirtualDut:
    """Select the AHB-Lite target profile and delegate all runtime logic."""

    if ahb_protocol.interface_family != AHB_FAMILY or (
        ahb_protocol.parameters.get("revision") != "AHB-Lite"
    ):
        raise ValueError("bridge egress requires an AHB-Lite InterfaceProtocol")
    return build_amba_serial_burst_bridge_vdut(
        name,
        axi_protocol,
        ahb_protocol,
        routes,
        ingress_port=axi_port,
        egress_port=ahb_port,
        parent_capacity=parent_capacity,
        assembly_profile=assembly_profile,
        byte_order=byte_order,
        capabilities=capabilities,
    )


__all__ = ["build_axi4_to_ahb_lite_bridge_vdut"]
