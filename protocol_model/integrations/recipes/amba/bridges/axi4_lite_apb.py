"""AXI4-Lite-to-APB preset over the generic single-access builder."""

from __future__ import annotations

from typing import Mapping

from protocol_model.interface import InterfaceProtocol
from protocol_model.protocols.amba.apb import APB_FAMILY
from protocol_model.protocols.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.fabric.route import AddressRoute

from .serial_address import build_amba_serial_address_bridge_vdut


def build_axi4_lite_to_apb_bridge_vdut(
    name: str,
    axi_protocol: InterfaceProtocol,
    apb_protocol: InterfaceProtocol,
    routes: tuple[AddressRoute, ...],
    *,
    axi_port: str = "s_axi",
    apb_port: str = "m_apb",
    parent_capacity: int = 8,
    capabilities: Mapping[str, object] | None = None,
    byte_order: ByteOrder | str = ByteOrder.LITTLE,
) -> VirtualDut:
    """Select AXI4-Lite/APB codecs and reuse the canonical address runtime."""

    if axi_protocol.interface_family != AXI4_LITE_FAMILY:
        raise ValueError("bridge ingress requires an AXI4-Lite InterfaceProtocol")
    if apb_protocol.interface_family != APB_FAMILY:
        raise ValueError("bridge egress requires an APB InterfaceProtocol")
    if int(axi_protocol.parameters["data_width"]) != int(
        apb_protocol.parameters["data_width"]
    ):
        raise ValueError(
            "AXI4-Lite to APB preset requires equal data widths"
        )
    if "prot" not in apb_protocol.event_kinds["READ"].schema.fields:
        raise ValueError(
            "AXI4-Lite to APB preset requires PPROT preservation"
        )
    if "strb" not in apb_protocol.event_kinds["WRITE"].schema.fields:
        raise ValueError(
            "AXI4-Lite to APB preset requires PSTRB preservation"
        )
    return build_amba_serial_address_bridge_vdut(
        name,
        axi_protocol,
        apb_protocol,
        routes,
        ingress_port=axi_port,
        egress_port=apb_port,
        parent_capacity=parent_capacity,
        byte_order=byte_order,
        capabilities=capabilities,
    )


__all__ = ["build_axi4_lite_to_apb_bridge_vdut"]
