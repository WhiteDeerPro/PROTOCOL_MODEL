"""Small construction vocabulary shared by the AXI4 example themes.

The helpers only make complete AXI4 inputs less noisy.  Legality remains the
responsibility of ``LinkSession`` and ``Axi4ObservationSession``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from protocol_model import AtomicFrame, CanonicalEvent, ReadyValidSignals, Verdict
from protocol_model.link import LinkProtocol


AXI4_CHANNELS = ("AW", "W", "B", "AR", "R")


class ExecutionMode(str, Enum):
    LINK = "link-events"
    OBSERVATION = "atomic-frames"


@dataclass(frozen=True)
class ExampleCase:
    """One readable input trace and its expected model outcome."""

    name: str
    theme: str
    title_en: str
    title_zh: str
    claim_en: str
    claim_zh: str
    protocol: LinkProtocol
    mode: ExecutionMode
    actions: tuple[CanonicalEvent | AtomicFrame, ...]
    expected_verdict: Verdict
    expected_rule: str | None = None
    expected_reason_contains: str | None = None
    deep_dive: bool = False


def address(
    kind: str,
    *,
    key: int,
    addr: int,
    length: int = 0,
    size: int = 2,
    burst: str = "INCR",
    lock: int = 0,
) -> CanonicalEvent:
    """Create a complete AR or AW event with neutral optional attributes."""

    return CanonicalEvent(
        kind,
        key=key,
        payload={
            "addr": addr,
            "len": length,
            "size": size,
            "burst": burst,
            "lock": lock,
            "cache": 0,
            "prot": 0,
            "qos": 0,
            "region": 0,
        },
    )


def read_data(
    *,
    key: int,
    last: bool,
    response: str = "OKAY",
    data: int = 0,
) -> CanonicalEvent:
    return CanonicalEvent(
        "R",
        key=key,
        payload={"data": data, "resp": response, "last": last},
    )


def write_data(
    *,
    last: bool,
    strobe: int,
    data: int = 0,
) -> CanonicalEvent:
    return CanonicalEvent(
        "W",
        payload={"data": data, "strb": strobe, "last": last},
    )


def write_response(*, key: int, response: str = "OKAY") -> CanonicalEvent:
    return CanonicalEvent("B", key=key, payload={"resp": response})


def frame(
    tick: int,
    active: dict[str, CanonicalEvent] | None = None,
    *,
    reset: bool = False,
    ready: bool = True,
) -> AtomicFrame:
    """Create one complete five-channel sampling edge."""

    active = active or {}
    observations: dict[str, object] = {
        name: ReadyValidSignals(
            valid=name in active,
            ready=ready,
            event=active.get(name),
        )
        for name in AXI4_CHANNELS
    }
    observations["reset"] = reset
    return AtomicFrame(
        tick,
        "aclk",
        observations,
        source="showcase.axi4",
    )


__all__ = [
    "AXI4_CHANNELS",
    "ExecutionMode",
    "ExampleCase",
    "address",
    "frame",
    "read_data",
    "write_data",
    "write_response",
]
