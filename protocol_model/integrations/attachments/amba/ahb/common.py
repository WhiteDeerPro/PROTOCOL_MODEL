"""Validation and byte-lane mapping shared by AHB address attachments."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.link import LinkProtocol
from protocol_model.link.amba import transfer_container_lane_bounds
from protocol_model.link.amba.ahb import AHB_FAMILY
from protocol_model.virtual_dut.address.access import ByteOrder


_AHB_CHANNELS = {
    "READ",
    "WRITE",
    "WRITE_DATA",
    "READ_RESPONSE",
    "WRITE_RESPONSE",
}


@dataclass(frozen=True)
class AhbAccessContext:
    request_kind: str
    address: int
    size: int
    attributes: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "attributes", MappingProxyType(dict(self.attributes))
        )


@dataclass(frozen=True)
class AhbCompleterState:
    pending_write: AhbAccessContext | None = None


def require_ahb_address_profile(
    protocol: LinkProtocol, role: str, byte_order: ByteOrder | str
) -> ByteOrder:
    """Validate the current AddressAccess-compatible AHB profile."""

    if protocol.family != AHB_FAMILY:
        raise ValueError("AHB attachment requires an AHB LinkProtocol family")
    if role not in protocol.roles:
        raise ValueError(f"AHB protocol has no {role} role")
    if set(protocol.channels) != _AHB_CHANNELS:
        raise ValueError("AHB address attachment requires native five-event channels")
    if bool(protocol.parameters.get("exclusive_transfers", False)):
        raise ValueError(
            "generic AHB AddressAccess attachment does not implement an "
            "Exclusive Access Monitor"
        )
    normalized = byte_order if isinstance(byte_order, ByteOrder) else ByteOrder(byte_order)
    if normalized is not ByteOrder.LITTLE:
        raise ValueError("current AHB AddressAccess mapping supports little-endian data")
    return normalized


def transfer_lane_lower(address: int, size: int, bus_bytes: int) -> int:
    lower, _ = transfer_container_lane_bounds(
        address, transfer_width=size, bus_bytes=bus_bytes
    )
    return lower


def extract_transfer_value(
    bus_value: int, *, address: int, size: int, bus_bytes: int
) -> int:
    lower = transfer_lane_lower(address, size, bus_bytes)
    return (bus_value >> (8 * lower)) & ((1 << (8 * size)) - 1)


def place_transfer_value(
    value: int, *, address: int, size: int, bus_bytes: int
) -> int:
    if not 0 <= value < 1 << (8 * size):
        raise ValueError("transfer value does not fit the addressed AHB size")
    lower = transfer_lane_lower(address, size, bus_bytes)
    return value << (8 * lower)


def extract_transfer_strobes(
    bus_strobes: int, *, address: int, size: int, bus_bytes: int
) -> int:
    lower = transfer_lane_lower(address, size, bus_bytes)
    return (bus_strobes >> lower) & ((1 << size) - 1)


def place_transfer_strobes(
    byte_enable: int, *, address: int, size: int, bus_bytes: int
) -> int:
    if not 0 <= byte_enable < 1 << size:
        raise ValueError("byte enable does not fit the addressed AHB size")
    lower = transfer_lane_lower(address, size, bus_bytes)
    return byte_enable << lower


def default_payload_value(field) -> object:
    """Choose the deterministic inactive/default value for optional fields."""

    if field.domain.contains(False):
        return False
    if field.domain.contains(0):
        return 0
    raise ValueError(f"AHB field {field.name!r} has no zero-like default")
