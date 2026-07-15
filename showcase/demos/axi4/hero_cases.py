"""Richer observations for the two narrated cases in the AXI4 example set.

These are not extra cases.  ``merge_deep_dive_cases`` replaces the two
conceptually equivalent event-level catalog entries with complete
``AtomicFrame`` observations.  The public set therefore remains 24 cases
while its two walkthroughs can show AXI-facing ready/valid lanes and reset.
"""

from __future__ import annotations

from protocol_model import AtomicFrame, CanonicalEvent, ReadyValidSignals
from protocol_model.link.amba.axi.axi4 import byte_lane_mask

from common import AXI4_CHANNELS, ExecutionMode, ExampleCase


DEEP_DIVE_CASES = frozenset(
    {"write-narrow-unaligned-incr", "write-early-wlast"}
)


def _address(*, transaction_id: int = 1) -> CanonicalEvent:
    return CanonicalEvent(
        "AW",
        key=transaction_id,
        payload={
            "addr": 0x0003,
            "len": 3,
            "size": 2,
            "burst": "INCR",
            "lock": 0,
            "cache": 0,
            "prot": 0,
            "qos": 0,
            "region": 0,
        },
    )


def _write_beat(
    address: CanonicalEvent,
    index: int,
    *,
    last: bool,
) -> CanonicalEvent:
    mask = byte_lane_mask(address, index, bus_bytes=8)
    byte_value = 0x11 * (index + 1)
    data = int.from_bytes(bytes([byte_value]) * 8, byteorder="little")
    return CanonicalEvent(
        "W",
        payload={"data": data, "strb": mask, "last": last},
    )


def _response(*, transaction_id: int = 1) -> CanonicalEvent:
    return CanonicalEvent("B", key=transaction_id, payload={"resp": "OKAY"})


def _frame(
    tick: int,
    active: dict[str, CanonicalEvent] | None = None,
    *,
    reset: bool = False,
) -> AtomicFrame:
    active = active or {}
    observations: dict[str, object] = {
        name: ReadyValidSignals(
            valid=name in active,
            ready=True,
            event=active.get(name),
        )
        for name in AXI4_CHANNELS
    }
    observations["reset"] = reset
    return AtomicFrame(
        tick=tick,
        clock="aclk",
        observations=observations,
        source="showcase.axi4",
    )


def _deep_dive_actions():
    address = _address()
    legal_beats = tuple(
        _write_beat(address, index, last=index == 3) for index in range(4)
    )
    legal = (
        _frame(0, reset=True),
        _frame(1, {"AW": address}),
        *(
            _frame(index + 2, {"W": beat})
            for index, beat in enumerate(legal_beats)
        ),
        _frame(6, {"B": _response()}),
    )
    early = (
        _frame(0, reset=True),
        _frame(1, {"AW": address}),
        _frame(2, {"W": _write_beat(address, 0, last=True)}),
    )
    return {
        "write-narrow-unaligned-incr": legal,
        "write-early-wlast": early,
    }


def merge_deep_dive_cases(
    cases: tuple[ExampleCase, ...],
) -> tuple[ExampleCase, ...]:
    """Replace two catalog traces without changing names or case count."""

    actions = _deep_dive_actions()
    merged = []
    for case in cases:
        replacement = actions.get(case.name)
        if replacement is None:
            merged.append(case)
            continue
        merged.append(
            ExampleCase(
                name=case.name,
                theme=case.theme,
                title_en=case.title_en,
                title_zh=case.title_zh,
                claim_en=case.claim_en,
                claim_zh=case.claim_zh,
                protocol=case.protocol,
                mode=ExecutionMode.OBSERVATION,
                actions=replacement,
                expected_verdict=case.expected_verdict,
                expected_rule=case.expected_rule,
                expected_reason_contains=case.expected_reason_contains,
                deep_dive=True,
            )
        )
    missing = DEEP_DIVE_CASES.difference(case.name for case in merged)
    if missing:
        raise ValueError("missing deep-dive catalog cases: " + ", ".join(missing))
    return tuple(merged)


__all__ = ["DEEP_DIVE_CASES", "merge_deep_dive_cases"]
