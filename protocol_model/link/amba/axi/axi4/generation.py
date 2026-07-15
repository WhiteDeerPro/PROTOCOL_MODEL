"""State-driven generation for the AXI4 read-channel LinkProtocol implementation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from random import Random

from protocol_model.link import LinkProtocol, LinkTrace
from protocol_model.semantics import EventOffer

from .definition import Axi4Config, build_axi4_link, build_axi4_read_link


class Axi4ReadSchedule(str, Enum):
    RANDOM = "random"
    INTERLEAVE = "interleave"


@dataclass(frozen=True)
class Axi4ReadGenerationPolicy:
    reads: int = 1
    maximum_beats: int = 16
    request_ids: tuple[int, ...] = ()
    request_beats: tuple[int, ...] = ()
    response_schedule: Axi4ReadSchedule = Axi4ReadSchedule.RANDOM

    def __post_init__(self) -> None:
        if self.reads < 0:
            raise ValueError("read count must be non-negative")
        if not 1 <= self.maximum_beats <= 256:
            raise ValueError("maximum AXI burst length must be in [1, 256]")
        for name, values in (
            ("request_ids", self.request_ids),
            ("request_beats", self.request_beats),
        ):
            if values and len(values) != self.reads:
                raise ValueError(f"{name} must be empty or contain one value per read")
        if any(not 1 <= beats <= self.maximum_beats for beats in self.request_beats):
            raise ValueError("requested read beats exceed the generation policy")


class Axi4ReadGenerator:
    def __init__(self, protocol: LinkProtocol | None = None) -> None:
        self.protocol = protocol or build_axi4_read_link()
        if not {"AR", "R"}.issubset(self.protocol.channels) or "axi4.read" not in self.protocol.monitors:
            raise ValueError("AXI4 read generator requires AR/R and axi4.read semantics")

    @classmethod
    def from_config(cls, config: Axi4Config | None = None) -> "Axi4ReadGenerator":
        return cls(build_axi4_read_link(config))

    @staticmethod
    def _request_offer(
        rng: Random, policy: Axi4ReadGenerationPolicy, index: int
    ) -> EventOffer:
        if policy.request_beats:
            payload = {
                "len": policy.request_beats[index] - 1,
                "burst": "INCR",
            }
            if policy.request_ids:
                return EventOffer.constrained(
                    "AR", key=policy.request_ids[index], payload=payload
                )
            return EventOffer.constrained("AR", payload=payload)
        bursts = ["FIXED", "INCR"]
        wrap_lengths = tuple(
            beats
            for beats in (2, 4, 8, 16)
            if beats <= policy.maximum_beats
        )
        if wrap_lengths:
            bursts.append("WRAP")
        burst = rng.choice(bursts)
        if burst == "WRAP":
            beats = rng.choice(wrap_lengths)
        elif burst == "FIXED":
            beats = rng.randint(1, min(policy.maximum_beats, 16))
        else:
            beats = rng.randint(1, policy.maximum_beats)
        payload = {"len": beats - 1, "burst": burst}
        if policy.request_ids:
            return EventOffer.constrained(
                "AR", key=policy.request_ids[index], payload=payload
            )
        return EventOffer.constrained("AR", payload=payload)

    def generate(
        self,
        rng: Random,
        policy: Axi4ReadGenerationPolicy | None = None,
    ) -> LinkTrace:
        policy = policy or Axi4ReadGenerationPolicy()
        session = self.protocol.open_session()
        state = session.initial_state()
        events = []

        for index in range(policy.reads):
            request = session.generate_event(
                state, rng, offer=self._request_offer(rng, policy, index)
            )
            transition = session.step(state, request)
            if transition.fault is not None:
                raise RuntimeError(
                    f"generated AXI request violated {transition.fault.rule}: "
                    f"{transition.fault.reason}"
                )
            state = transition.state
            events.extend(transition.emissions)

        previous_key = None
        while not session.is_quiescent(state):
            response_offer = None
            if policy.response_schedule is Axi4ReadSchedule.INTERLEAVE:
                offers = [
                    offer
                    for offer in session.event_offers(state)
                    if offer.kind == "R"
                ]
                selected = offers[0]
                if len(offers) > 1:
                    selected = next(
                        (
                            offer
                            for offer in offers
                            if offer.key != previous_key
                        ),
                        offers[0],
                    )
                response_offer = EventOffer.constrained("R", key=selected.key)
            response = session.generate_event(
                state, rng, kind="R", offer=response_offer
            )
            transition = session.step(state, response)
            if transition.fault is not None:
                raise RuntimeError(
                    f"generated AXI response violated {transition.fault.rule}: "
                    f"{transition.fault.reason}"
                )
            state = transition.state
            events.extend(transition.emissions)
            previous_key = response.key

        return LinkTrace(tuple(events), state.causal_edges)


@dataclass(frozen=True)
class Axi4WriteGenerationPolicy:
    writes: int = 1
    maximum_beats: int = 16
    request_ids: tuple[int, ...] = ()
    request_beats: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.writes < 0:
            raise ValueError("write count must be non-negative")
        if not 1 <= self.maximum_beats <= 256:
            raise ValueError("maximum AXI burst length must be in [1, 256]")
        for name, values in (
            ("request_ids", self.request_ids),
            ("request_beats", self.request_beats),
        ):
            if values and len(values) != self.writes:
                raise ValueError(f"{name} must be empty or contain one value per write")
        if any(not 1 <= beats <= self.maximum_beats for beats in self.request_beats):
            raise ValueError("requested write beats exceed the generation policy")


class Axi4WriteGenerator:
    def __init__(self, protocol: LinkProtocol | None = None) -> None:
        self.protocol = protocol or build_axi4_link()
        if set(self.protocol.channels) != {"AW", "W", "B", "AR", "R"}:
            raise ValueError("AXI4 write generator requires the five-channel link")

    @classmethod
    def from_config(cls, config: Axi4Config | None = None) -> "Axi4WriteGenerator":
        return cls(build_axi4_link(config))

    @staticmethod
    def _request_offer(
        rng: Random, policy: Axi4WriteGenerationPolicy, index: int
    ) -> EventOffer:
        if policy.request_beats:
            beats = policy.request_beats[index]
            burst = "INCR"
        else:
            burst = rng.choice(("FIXED", "INCR", "WRAP"))
            if burst == "WRAP":
                candidates = tuple(
                    beats
                    for beats in (2, 4, 8, 16)
                    if beats <= policy.maximum_beats
                )
                if candidates:
                    beats = rng.choice(candidates)
                else:
                    burst = "INCR"
                    beats = 1
            elif burst == "FIXED":
                beats = rng.randint(1, min(policy.maximum_beats, 16))
            else:
                beats = rng.randint(1, policy.maximum_beats)
        payload = {"len": beats - 1, "burst": burst}
        if policy.request_ids:
            return EventOffer.constrained(
                "AW", key=policy.request_ids[index], payload=payload
            )
        return EventOffer.constrained("AW", payload=payload)

    def generate(
        self,
        rng: Random,
        policy: Axi4WriteGenerationPolicy | None = None,
    ) -> LinkTrace:
        policy = policy or Axi4WriteGenerationPolicy()
        session = self.protocol.open_session()
        state = session.initial_state()
        events = []

        for index in range(policy.writes):
            address = session.generate_event(
                state, rng, offer=self._request_offer(rng, policy, index)
            )
            transition = session.step(state, address)
            if transition.fault is not None:
                raise RuntimeError(
                    f"generated AXI AW violated {transition.fault.rule}: "
                    f"{transition.fault.reason}"
                )
            state = transition.state
            events.extend(transition.emissions)

        write_state = state.state_of("axi4.write")
        while (
            write_state.join.descriptors
            or write_state.join.bursts
            or write_state.assembler.current
        ):
            data = session.generate_event(state, rng, kind="W")
            transition = session.step(state, data)
            if transition.fault is not None:
                raise RuntimeError(
                    f"generated AXI W violated {transition.fault.rule}: "
                    f"{transition.fault.reason}"
                )
            state = transition.state
            events.extend(transition.emissions)
            write_state = state.state_of("axi4.write")

        while write_state.completions.pending:
            response = session.generate_event(state, rng, kind="B")
            transition = session.step(state, response)
            if transition.fault is not None:
                raise RuntimeError(
                    f"generated AXI B violated {transition.fault.rule}: "
                    f"{transition.fault.reason}"
                )
            state = transition.state
            events.extend(transition.emissions)
            write_state = state.state_of("axi4.write")

        return LinkTrace(tuple(events), state.causal_edges)
