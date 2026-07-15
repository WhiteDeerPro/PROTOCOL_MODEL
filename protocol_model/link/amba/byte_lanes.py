"""Byte-lane geometry shared by memory-mapped AMBA link families."""

from __future__ import annotations


def transfer_container_lane_bounds(
    start_address: int, *, transfer_width: int, bus_bytes: int
) -> tuple[int, int]:
    """Return byte lanes occupied by one possibly unaligned transfer.

    The calculation is independent of AXI/AHB event field names.  A concrete
    LinkProtocol remains responsible for deciding whether this geometry is
    legal for its transfer type.
    """

    if bus_bytes <= 0 or bus_bytes & (bus_bytes - 1):
        raise ValueError("bus_bytes must be a positive power of two")
    if transfer_width <= 0 or transfer_width & (transfer_width - 1):
        raise ValueError("transfer_width must be a positive power of two")
    if transfer_width > bus_bytes:
        raise ValueError(
            f"transfer width {transfer_width} bytes exceeds "
            f"{bus_bytes}-byte data bus"
        )
    lower_lane = start_address % bus_bytes
    aligned = (start_address // transfer_width) * transfer_width
    bus_word = (start_address // bus_bytes) * bus_bytes
    upper_lane = aligned + transfer_width - 1 - bus_word
    if upper_lane < lower_lane or upper_lane >= bus_bytes:
        raise ValueError("one transfer cannot cross the data bus boundary")
    return lower_lane, upper_lane


def transfer_container_lane_mask(
    start_address: int, *, transfer_width: int, bus_bytes: int
) -> int:
    lower, upper = transfer_container_lane_bounds(
        start_address,
        transfer_width=transfer_width,
        bus_bytes=bus_bytes,
    )
    return ((1 << (upper - lower + 1)) - 1) << lower
