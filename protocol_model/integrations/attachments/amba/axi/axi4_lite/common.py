"""Validation and byte-lane mapping shared by AXI4-Lite attachments."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.link import LinkProtocol
from protocol_model.link.amba import transfer_container_lane_bounds
from protocol_model.link.amba.axi.axi4_lite import AXI4_LITE_FAMILY
from protocol_model.virtual_dut.address.access import (
    AccessStatus,
    ByteOrder,
)


_AXI4_LITE_CHANNELS = {"AW", "W", "B", "AR", "R"}


@dataclass(frozen=True)
class Axi4LiteAccessContext:
    request_kind: str
    address: int
    size: int
    attributes: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )


@dataclass(frozen=True)
class Axi4LiteWriteData:
    data: int
    strb: int


@dataclass(frozen=True)
class Axi4LiteCompleterState:
    pending_aw: tuple[Axi4LiteAccessContext, ...] = ()
    pending_w: tuple[Axi4LiteWriteData, ...] = ()


@dataclass(frozen=True)
class Axi4LitePendingRead:
    request_id: int
    address: int
    size: int


@dataclass(frozen=True)
class Axi4LiteRequesterState:
    pending_reads: tuple[Axi4LitePendingRead, ...] = ()
    pending_writes: tuple[int, ...] = ()


def require_axi4_lite_address_profile(
    protocol: LinkProtocol, role: str, byte_order: ByteOrder | str
) -> ByteOrder:
    """Validate the native AXI4-Lite profile used by AddressAccess."""

    if protocol.family != AXI4_LITE_FAMILY:
        raise ValueError(
            "AXI4-Lite attachment requires an AXI4-Lite LinkProtocol family"
        )
    if role not in protocol.roles:
        raise ValueError(f"AXI4-Lite protocol has no {role} role")
    if set(protocol.channels) != _AXI4_LITE_CHANNELS:
        raise ValueError(
            "AXI4-Lite address attachment requires native five-channel events"
        )
    normalized = (
        byte_order if isinstance(byte_order, ByteOrder) else ByteOrder(byte_order)
    )
    if normalized is not ByteOrder.LITTLE:
        raise ValueError(
            "current AXI4-Lite AddressAccess mapping supports little-endian data"
        )
    return normalized


def implicit_transfer_geometry(address: int, bus_bytes: int) -> tuple[int, int]:
    """Return the first active lane and byte span of a native Lite transfer."""

    lower, upper = transfer_container_lane_bounds(
        address,
        transfer_width=bus_bytes,
        bus_bytes=bus_bytes,
    )
    return lower, upper - lower + 1


def extract_transfer_value(
    bus_value: int, *, address: int, bus_bytes: int
) -> int:
    lower, size = implicit_transfer_geometry(address, bus_bytes)
    return (bus_value >> (8 * lower)) & ((1 << (8 * size)) - 1)


def extract_transfer_strobes(
    bus_strobes: int, *, address: int, bus_bytes: int
) -> int:
    lower, size = implicit_transfer_geometry(address, bus_bytes)
    return (bus_strobes >> lower) & ((1 << size) - 1)


def place_transfer_value(
    value: int, *, address: int, size: int, bus_bytes: int
) -> int:
    lower, implicit_size = implicit_transfer_geometry(address, bus_bytes)
    if size != implicit_size:
        raise ValueError(
            "AXI4-Lite AddressAccess size must match its implicit transfer span"
        )
    if not 0 <= value < 1 << (8 * size):
        raise ValueError("transfer value does not fit the AXI4-Lite access size")
    return value << (8 * lower)


def place_transfer_strobes(
    byte_enable: int, *, address: int, size: int, bus_bytes: int
) -> int:
    lower, implicit_size = implicit_transfer_geometry(address, bus_bytes)
    if size != implicit_size:
        raise ValueError(
            "AXI4-Lite AddressAccess size must match its implicit transfer span"
        )
    if not 0 <= byte_enable < 1 << size:
        raise ValueError("byte enable does not fit the AXI4-Lite access size")
    return byte_enable << lower


def access_status_to_response(status: AccessStatus) -> str:
    return {
        AccessStatus.OK: "OKAY",
        AccessStatus.ACCESS_ERROR: "SLVERR",
        AccessStatus.DECODE_ERROR: "DECERR",
    }[status]


def response_to_access_status(response: object) -> AccessStatus:
    return {
        "OKAY": AccessStatus.OK,
        "SLVERR": AccessStatus.ACCESS_ERROR,
        "DECERR": AccessStatus.DECODE_ERROR,
    }[response]
