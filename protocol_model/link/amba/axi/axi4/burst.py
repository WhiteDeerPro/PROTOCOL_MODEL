"""Pure AXI4 burst geometry shared by validation and generation."""

from __future__ import annotations

from protocol_model.link.amba.byte_lanes import (
    transfer_container_lane_bounds,
    transfer_container_lane_mask,
)
from protocol_model.semantics import CanonicalEvent


def transfer_bytes(address: CanonicalEvent) -> int:
    return 1 << int(address.payload["size"])


def transfer_count(address: CanonicalEvent) -> int:
    return int(address.payload["len"]) + 1


def beat_address(address: CanonicalEvent, beat_index: int) -> int:
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


def _validate_bus_geometry(address: CanonicalEvent, bus_bytes: int) -> int:
    if bus_bytes <= 0 or bus_bytes & (bus_bytes - 1):
        raise ValueError("bus_bytes must be a positive power of two")
    width = transfer_bytes(address)
    if width > bus_bytes:
        raise ValueError(
            f"transfer width {width} bytes exceeds {bus_bytes}-byte data bus"
        )
    return width


def byte_lane_bounds(
    address: CanonicalEvent, beat_index: int, *, bus_bytes: int
) -> tuple[int, int]:
    """Return inclusive AXI data-bus byte lanes for one transfer.

    An unaligned first transfer begins at AxADDR but ends at the end of its
    naturally aligned transfer container. FIXED bursts retain those first-beat
    lanes; later INCR/WRAP beats use a complete naturally aligned container.
    """

    width = _validate_bus_geometry(address, bus_bytes)
    current = beat_address(address, beat_index)
    lower_lane = current % bus_bytes
    if beat_index == 0 or address.payload["burst"] == "FIXED":
        return transfer_container_lane_bounds(
            current, transfer_width=width, bus_bytes=bus_bytes
        )
    else:
        upper_lane = lower_lane + width - 1
    if upper_lane < lower_lane or upper_lane >= bus_bytes:
        raise ValueError("one AXI transfer cannot cross the data bus boundary")
    return lower_lane, upper_lane


def beat_byte_addresses(
    address: CanonicalEvent, beat_index: int, *, bus_bytes: int
) -> tuple[int, ...]:
    """Return memory byte addresses represented by the legal lanes of a beat."""

    lower, upper = byte_lane_bounds(
        address, beat_index, bus_bytes=bus_bytes
    )
    current = beat_address(address, beat_index)
    bus_word = (current // bus_bytes) * bus_bytes
    return tuple(bus_word + lane for lane in range(lower, upper + 1))


def byte_lane_mask(
    address: CanonicalEvent, beat_index: int, *, bus_bytes: int
) -> int:
    lower_lane, upper_lane = byte_lane_bounds(
        address, beat_index, bus_bytes=bus_bytes
    )
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


def wrap_length_is_legal(event: CanonicalEvent) -> bool:
    return event.payload["burst"] != "WRAP" or event.payload["len"] in {
        1,
        3,
        7,
        15,
    }


def fixed_length_is_legal(event: CanonicalEvent) -> bool:
    return event.payload["burst"] != "FIXED" or int(event.payload["len"]) <= 15


def exclusive_length_is_legal(event: CanonicalEvent) -> bool:
    return not int(event.payload["lock"]) or transfer_count(event) <= 16


def exclusive_size_is_legal(event: CanonicalEvent) -> bool:
    if not int(event.payload["lock"]):
        return True
    total = transfer_count(event) * transfer_bytes(event)
    return total in {1, 2, 4, 8, 16, 32, 64, 128}


def exclusive_start_is_aligned(event: CanonicalEvent) -> bool:
    if not int(event.payload["lock"]):
        return True
    total = transfer_count(event) * transfer_bytes(event)
    return int(event.payload["addr"]) % total == 0


def wrap_start_is_aligned(event: CanonicalEvent) -> bool:
    return event.payload["burst"] != "WRAP" or (
        int(event.payload["addr"]) % transfer_bytes(event) == 0
    )


def stays_in_4kb(event: CanonicalEvent) -> bool:
    address = int(event.payload["addr"])
    beats = transfer_count(event)
    bytes_per_beat = transfer_bytes(event)
    burst = event.payload["burst"]
    if burst == "FIXED":
        last = (
            (address // bytes_per_beat) * bytes_per_beat
            + bytes_per_beat
            - 1
        )
    elif burst == "WRAP":
        total = beats * bytes_per_beat
        boundary = (address // total) * total
        last = boundary + total - 1
    else:
        aligned = (address // bytes_per_beat) * bytes_per_beat
        last = aligned + beats * bytes_per_beat - 1
    return address // 4096 == last // 4096


def stays_in_address_space(event: CanonicalEvent, *, address_width: int) -> bool:
    """Return whether the complete transfer container fits AxADDR width."""

    if type(address_width) is not int or address_width <= 0:
        raise ValueError("address_width must be a positive integer")
    address = int(event.payload["addr"])
    beats = transfer_count(event)
    bytes_per_beat = transfer_bytes(event)
    burst = event.payload["burst"]
    if burst == "FIXED":
        last = (address // bytes_per_beat) * bytes_per_beat + bytes_per_beat - 1
    elif burst == "WRAP":
        total = beats * bytes_per_beat
        last = (address // total) * total + total - 1
    else:
        aligned = (address // bytes_per_beat) * bytes_per_beat
        last = aligned + beats * bytes_per_beat - 1
    return last < (1 << address_width)
