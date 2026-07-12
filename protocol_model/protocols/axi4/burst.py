"""Pure AXI4 burst-address and byte-lane semantics."""

from __future__ import annotations

from protocol_model.core import CanonicalEvent


def transfer_bytes(address: CanonicalEvent) -> int:
    return 1 << int(address.payload["size"])


def transfer_count(address: CanonicalEvent) -> int:
    return int(address.payload["len"]) + 1


def beat_address(address: CanonicalEvent, beat_index: int) -> int:
    """Return the protocol address of one zero-based burst beat."""

    beats = transfer_count(address)
    if beat_index < 0 or beat_index >= beats:
        raise IndexError(f"beat index {beat_index} outside burst length {beats}")
    start = int(address.payload["addr"])
    size = transfer_bytes(address)
    burst = address.payload["burst"]
    if burst == "FIXED":
        return start
    aligned = (start // size) * size
    if burst == "INCR":
        return start if beat_index == 0 else aligned + beat_index * size
    if burst == "WRAP":
        span = beats * size
        lower = (start // span) * span
        return lower + ((start - lower + beat_index * size) % span)
    raise ValueError(f"unknown AXI burst type {burst!r}")


def byte_lane_mask(
    address: CanonicalEvent, beat_index: int, *, bus_bytes: int
) -> int:
    """Return lanes that WSTRB may assert for this transfer beat."""

    if bus_bytes <= 0:
        raise ValueError("bus_bytes must be positive")
    width = transfer_bytes(address)
    current = beat_address(address, beat_index)
    aligned = (current // width) * width
    lower_lane = current % bus_bytes
    upper_lane = (aligned + width - 1) % bus_bytes
    if upper_lane < lower_lane:
        raise ValueError("one AXI transfer cannot wrap across the data bus boundary")
    return ((1 << (upper_lane - lower_lane + 1)) - 1) << lower_lane


def write_strobe_violation(
    address: CanonicalEvent,
    beat_index: int,
    data: CanonicalEvent,
    *,
    bus_bytes: int,
) -> str | None:
    allowed = byte_lane_mask(address, beat_index, bus_bytes=bus_bytes)
    observed = int(data.payload["strb"])
    outside = observed & ~allowed
    if outside:
        return (
            f"WSTRB 0x{observed:x} asserts lanes outside allowed mask "
            f"0x{allowed:x} at beat {beat_index + 1}"
        )
    return None
