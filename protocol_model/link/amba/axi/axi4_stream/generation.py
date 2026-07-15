"""Small state-driven packet generator for AXI4-Stream."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

from protocol_model.link import LinkProtocol, LinkTrace
from protocol_model.semantics import EventOffer

from .definition import Axi4StreamConfig, build_axi4_stream_link


@dataclass(frozen=True)
class Axi4StreamGenerationPolicy:
    packet_lengths: tuple[int, ...] = (1,)
    stream_ids: tuple[int, ...] = ()
    destinations: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.packet_lengths or any(length <= 0 for length in self.packet_lengths):
            raise ValueError("stream generation requires positive packet lengths")


class Axi4StreamGenerator:
    def __init__(self, protocol: LinkProtocol):
        if set(protocol.channels) != {"T"}:
            raise ValueError("AXI4-Stream generator requires one T channel")
        if not bool(protocol.parameters["use_last"]):
            raise ValueError("packet generation requires explicit TLAST")
        self.protocol = protocol

    @classmethod
    def from_config(
        cls, config: Axi4StreamConfig | None = None
    ) -> "Axi4StreamGenerator":
        return cls(build_axi4_stream_link(config))

    def generate(
        self, rng: Random, policy: Axi4StreamGenerationPolicy
    ) -> LinkTrace:
        session = self.protocol.open_session()
        state = session.initial_state()
        events = []
        use_keep = bool(self.protocol.parameters["use_keep"])
        byte_count = int(self.protocol.parameters["data_width"]) // 8
        id_width = int(self.protocol.parameters["id_width"])
        dest_width = int(self.protocol.parameters["dest_width"])
        for packet_index, length in enumerate(policy.packet_lengths):
            key = (
                policy.stream_ids[packet_index % len(policy.stream_ids)]
                if policy.stream_ids
                else rng.randrange(1 << id_width) if id_width else None
            )
            destination = (
                policy.destinations[packet_index % len(policy.destinations)]
                if policy.destinations
                else rng.randrange(1 << dest_width) if dest_width else None
            )
            for beat in range(length):
                payload = {"last": beat + 1 == length}
                if use_keep:
                    payload["keep"] = (1 << byte_count) - 1
                if destination is not None:
                    payload["dest"] = destination
                offer = EventOffer.constrained("T", key=key, payload=payload)
                event = session.generate_event(state, rng, offer=offer)
                transition = session.step(state, event)
                if transition.fault is not None:
                    raise RuntimeError(transition.fault.reason)
                state = transition.state
                events.extend(transition.emissions)
        return LinkTrace(tuple(events), state.causal_edges)
