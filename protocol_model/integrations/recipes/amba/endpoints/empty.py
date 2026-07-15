"""AMBA role selections for protocol-independent empty endpoint recipes."""

from __future__ import annotations

from protocol_model.link import LinkProtocol
from protocol_model.link.amba.ahb import AHB_FAMILY
from protocol_model.link.amba.apb import APB_FAMILY
from protocol_model.link.amba.axi.axi4 import AXI4_FAMILY
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.recipes import (
    build_blackhole_sink_vdut,
    build_idle_source_vdut,
)


def _require_family(protocol: LinkProtocol, family: str, label: str) -> None:
    if protocol.family != family:
        raise ValueError(
            f"{label} empty endpoint requires protocol family {family!r}, "
            f"got {protocol.family!r}"
        )


def build_apb_idle_source_vdut(
    name: str, protocol: LinkProtocol, *, port_name: str = "apb"
) -> VirtualDut:
    _require_family(protocol, APB_FAMILY, "APB")
    return build_idle_source_vdut(
        name, protocol, "requester", port_name=port_name
    )


def build_apb_blackhole_sink_vdut(
    name: str, protocol: LinkProtocol, *, port_name: str = "apb"
) -> VirtualDut:
    _require_family(protocol, APB_FAMILY, "APB")
    return build_blackhole_sink_vdut(
        name, protocol, "completer", port_name=port_name
    )


def build_ahb_idle_source_vdut(
    name: str, protocol: LinkProtocol, *, port_name: str = "ahb"
) -> VirtualDut:
    _require_family(protocol, AHB_FAMILY, "AHB")
    return build_idle_source_vdut(
        name, protocol, "manager", port_name=port_name
    )


def build_ahb_blackhole_sink_vdut(
    name: str, protocol: LinkProtocol, *, port_name: str = "ahb"
) -> VirtualDut:
    _require_family(protocol, AHB_FAMILY, "AHB")
    return build_blackhole_sink_vdut(
        name, protocol, "subordinate", port_name=port_name
    )


def build_axi4_idle_source_vdut(
    name: str, protocol: LinkProtocol, *, port_name: str = "axi"
) -> VirtualDut:
    _require_family(protocol, AXI4_FAMILY, "AXI4")
    return build_idle_source_vdut(
        name, protocol, "manager", port_name=port_name
    )


def build_axi4_blackhole_sink_vdut(
    name: str, protocol: LinkProtocol, *, port_name: str = "axi"
) -> VirtualDut:
    _require_family(protocol, AXI4_FAMILY, "AXI4")
    return build_blackhole_sink_vdut(
        name, protocol, "subordinate", port_name=port_name
    )


__all__ = [
    "build_ahb_blackhole_sink_vdut",
    "build_ahb_idle_source_vdut",
    "build_apb_blackhole_sink_vdut",
    "build_apb_idle_source_vdut",
    "build_axi4_blackhole_sink_vdut",
    "build_axi4_idle_source_vdut",
]
