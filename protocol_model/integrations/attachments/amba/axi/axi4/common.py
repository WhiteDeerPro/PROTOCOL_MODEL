"""Validation, byte lanes, and response mapping shared by AXI4 attachments."""

from __future__ import annotations

from math import log2

from protocol_model.link import LinkProtocol
from protocol_model.link.amba.axi.axi4 import (
    AXI4_FAMILY,
    beat_byte_addresses,
    byte_lane_bounds,
)
from protocol_model.patterns import ForbiddenEventMonitor
from protocol_model.semantics import CanonicalEvent
from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AccessStatus,
    AddressAccess,
    ByteOrder,
)


AXI4_CHANNELS = frozenset(("AW", "W", "B", "AR", "R"))
AXI4_ADDRESS_ATTRIBUTES = frozenset(("cache", "prot", "qos", "region"))


def require_axi4_address_protocol(
    protocol: LinkProtocol,
    role: str,
    byte_order: ByteOrder | str,
) -> ByteOrder:
    """Validate the transport shape used by the current AXI4 integration."""

    if protocol.family != AXI4_FAMILY:
        raise ValueError("AXI4 attachment requires the AXI4 LinkProtocol family")
    if role not in protocol.roles:
        raise ValueError(f"AXI4 protocol has no {role} role")
    if set(protocol.channels) != AXI4_CHANNELS:
        raise ValueError("AXI4 address integration requires the five-channel shape")
    for name in ("address_width", "data_width", "id_width"):
        if name not in protocol.parameters:
            raise ValueError(f"AXI4 protocol is missing parameter {name!r}")
    normalized = (
        byte_order
        if isinstance(byte_order, ByteOrder)
        else ByteOrder(byte_order)
    )
    if normalized is not ByteOrder.LITTLE:
        raise ValueError("current AXI4 AddressSpace mapping supports little-endian data")
    return normalized


def event_is_forbidden(protocol: LinkProtocol, kind: str) -> bool:
    """Whether a monotonic link profile explicitly disables an event kind."""

    return any(
        isinstance(monitor, ForbiddenEventMonitor)
        and kind in monitor.event_kinds
        for monitor in protocol.monitors.values()
    )


def address_attributes(event: CanonicalEvent) -> dict[str, object]:
    return {
        name: event.payload[name]
        for name in AXI4_ADDRESS_ATTRIBUTES
        if name in event.payload
    }


def beat_access_geometry(
    address: CanonicalEvent,
    beat_index: int,
    *,
    bus_bytes: int,
) -> tuple[int, int, int]:
    """Return address, actual byte count, and lower bus lane for one beat."""

    byte_addresses = beat_byte_addresses(
        address, beat_index, bus_bytes=bus_bytes
    )
    if not byte_addresses:
        raise ValueError("AXI4 beat exposes no addressable byte lanes")
    if byte_addresses != tuple(
        range(byte_addresses[0], byte_addresses[0] + len(byte_addresses))
    ):
        raise ValueError("one AXI4 beat is not a contiguous byte access")
    lower_lane, _ = byte_lane_bounds(
        address, beat_index, bus_bytes=bus_bytes
    )
    return byte_addresses[0], len(byte_addresses), lower_lane


def extract_beat_value(
    bus_value: int,
    address: CanonicalEvent,
    beat_index: int,
    *,
    bus_bytes: int,
) -> int:
    _, size, lower_lane = beat_access_geometry(
        address, beat_index, bus_bytes=bus_bytes
    )
    return (int(bus_value) >> (8 * lower_lane)) & ((1 << (8 * size)) - 1)


def place_beat_value(
    value: int,
    address: CanonicalEvent,
    beat_index: int,
    *,
    bus_bytes: int,
) -> int:
    _, size, lower_lane = beat_access_geometry(
        address, beat_index, bus_bytes=bus_bytes
    )
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("AXI4 read data must be an integer")
    if not 0 <= value < 1 << (8 * size):
        raise ValueError("AXI4 read data does not fit the addressed beat lanes")
    return value << (8 * lower_lane)


def extract_beat_strobes(
    bus_strobes: int,
    address: CanonicalEvent,
    beat_index: int,
    *,
    bus_bytes: int,
) -> int:
    _, size, lower_lane = beat_access_geometry(
        address, beat_index, bus_bytes=bus_bytes
    )
    return (int(bus_strobes) >> lower_lane) & ((1 << size) - 1)


def place_single_value(
    value: int,
    *,
    address: int,
    size: int,
    bus_bytes: int,
) -> int:
    lower_lane = address % bus_bytes
    if not 0 <= value < 1 << (8 * size):
        raise ValueError("AXI4 value does not fit the single access size")
    return value << (8 * lower_lane)


def extract_single_value(
    bus_value: int,
    *,
    address: int,
    size: int,
    bus_bytes: int,
) -> int:
    lower_lane = address % bus_bytes
    return (int(bus_value) >> (8 * lower_lane)) & ((1 << (8 * size)) - 1)


def place_single_strobes(
    byte_enable: int,
    *,
    address: int,
    size: int,
    bus_bytes: int,
) -> int:
    if not 0 <= byte_enable < 1 << size:
        raise ValueError("AXI4 byte enable does not fit the single access size")
    return byte_enable << (address % bus_bytes)


def validate_single_access(
    access: AddressAccess,
    *,
    bus_bytes: int,
    address_width: int,
) -> str | None:
    """Validate the deliberately serialized, one-beat requester profile."""

    size = access.size
    if size > bus_bytes or size & (size - 1):
        return "AXI4 single access size must be a power of two within the data bus"
    if access.address % size:
        return "AXI4 single access must align to its transfer size"
    if access.address + size > 1 << address_width:
        return "AXI4 single access exceeds the address width"
    return None


def single_address_payload(access: AddressAccess) -> tuple[dict[str, object], set[str]]:
    payload: dict[str, object] = {
        "addr": access.address,
        "len": 0,
        "size": int(log2(access.size)),
        "burst": "INCR",
        "lock": 0,
    }
    for name in sorted(AXI4_ADDRESS_ATTRIBUTES):
        payload[name] = access.attributes.get(name, 0)
    return payload, set(AXI4_ADDRESS_ATTRIBUTES)


def result_response(result: AccessResult) -> str:
    if result.status is AccessStatus.OK:
        return "OKAY"
    if result.status is AccessStatus.DECODE_ERROR:
        return "DECERR"
    return "SLVERR"


def aggregate_write_response(results: tuple[AccessResult, ...]) -> str:
    responses = tuple(result_response(item) for item in results)
    if "DECERR" in responses:
        return "DECERR"
    if "SLVERR" in responses:
        return "SLVERR"
    return "OKAY"


def response_status(response: object) -> AccessStatus:
    if response == "OKAY":
        return AccessStatus.OK
    if response == "DECERR":
        return AccessStatus.DECODE_ERROR
    return AccessStatus.ACCESS_ERROR
