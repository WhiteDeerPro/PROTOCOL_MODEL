"""Explicit semantic embedding of native AXI4-Lite events into AXI4."""

from __future__ import annotations

from dataclasses import dataclass, replace

from protocol_model.link import LinkTrace
from protocol_model.link.amba.axi.axi4 import Axi4Config
from protocol_model.semantics import CanonicalEvent

from .definition import Axi4LiteConfig


@dataclass(frozen=True)
class Axi4LiteToAxi4:
    lite: Axi4LiteConfig = Axi4LiteConfig()
    axi: Axi4Config | None = None
    fixed_id: int = 0

    def __post_init__(self) -> None:
        target = self.axi or Axi4Config(
            address_width=self.lite.address_width,
            data_width=self.lite.data_width,
            id_width=1,
        )
        if target.address_width != self.lite.address_width:
            raise ValueError("AXI4 embedding requires the same address width")
        if target.data_width != self.lite.data_width:
            raise ValueError("AXI4 embedding requires the same data width")
        if not 0 <= self.fixed_id < (1 << target.id_width):
            raise ValueError("fixed AXI ID is outside the target ID width")
        object.__setattr__(self, "axi", target)

    def event(self, event: CanonicalEvent) -> CanonicalEvent:
        if event.key is not None:
            raise ValueError("native AXI4-Lite events have no transaction ID")
        payload = dict(event.payload)
        if event.kind in {"AW", "AR"}:
            payload = {
                "addr": payload["addr"],
                "len": 0,
                "size": self.axi.maximum_size_encoding,  # type: ignore[union-attr]
                "burst": "INCR",
                "lock": 0,
                "cache": 0,
                "prot": payload["prot"],
                "qos": 0,
                "region": 0,
            }
            key = self.fixed_id
        elif event.kind == "W":
            payload["last"] = True
            key = None
        elif event.kind == "R":
            payload["last"] = True
            key = self.fixed_id
        elif event.kind == "B":
            key = self.fixed_id
        else:
            raise ValueError(f"event {event.kind!r} is not AXI4-Lite")
        return replace(event, key=key, payload=payload)

    def trace(self, trace: LinkTrace) -> LinkTrace:
        return LinkTrace(tuple(self.event(event) for event in trace.events), trace.causal_edges)
