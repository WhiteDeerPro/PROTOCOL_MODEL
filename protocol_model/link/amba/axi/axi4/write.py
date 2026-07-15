"""AXI4 AW/W FIFO correlation and B completion semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from protocol_model.patterns import (
    BurstAssembler,
    BurstAssemblerState,
    CompletionLedger,
    CompletionLedgerState,
    FifoJoin,
    FifoJoinState,
)
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    EventOffer,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)


@dataclass(frozen=True)
class Axi4WriteState:
    assembler: BurstAssemblerState
    join: FifoJoinState
    completions: CompletionLedgerState


@dataclass(frozen=True)
class Axi4WriteMonitor(
    SemanticComponent[CanonicalEvent, Axi4WriteState, object]
):
    name: str
    count_of: Callable[[CanonicalEvent], int]
    data_rule: Callable[[CanonicalEvent, int, CanonicalEvent], str | None]
    data_offer: Callable[[CanonicalEvent, int], Mapping[str, object]]
    final_field: str | None = "last"
    data_rule_name: str = "data_relation"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_assembler",
            BurstAssembler(f"{self.name}.burst", "W", self.final_field),
        )
        object.__setattr__(
            self,
            "_join",
            FifoJoin(
                f"{self.name}.join",
                self.count_of,
                self.data_rule,
                self.data_rule_name,
            ),
        )
        object.__setattr__(
            self,
            "_ledger",
            CompletionLedger(f"{self.name}.completion", "B"),
        )

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset(("AW", "W", "B"))

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.event_kinds

    def initial_state(self) -> Axi4WriteState:
        return Axi4WriteState(
            self._assembler.initial_state(),
            self._join.initial_state(),
            self._ledger.initial_state(),
        )

    def is_quiescent(self, state: Axi4WriteState) -> bool:
        return (
            self._assembler.is_quiescent(state.assembler)
            and self._join.is_quiescent(state.join)
            and self._ledger.is_quiescent(state.completions)
        )

    def resource_usage(self, state: Axi4WriteState) -> dict[str, int]:
        usage = {
            f"{self.name}.pending_descriptors": len(state.join.descriptors),
            f"{self.name}.pending_data_bursts": len(state.join.bursts),
            f"{self.name}.pending_completions": len(state.completions.pending),
        }
        if self.final_field is not None:
            usage[f"{self.name}.assembling_data"] = int(
                bool(state.assembler.current)
            )
        return usage

    def _fault(
        self, state: Axi4WriteState, rule: str, reason: str
    ) -> SemanticStep[Axi4WriteState, object]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, ConstraintScope.LINK
            ),
        )

    def event_offers(self, state: Axi4WriteState) -> tuple[EventOffer, ...]:
        offers = [EventOffer.unconstrained("AW")]
        if state.join.descriptors:
            descriptor = state.join.descriptors[0]
            position = len(state.assembler.current)
            if position < descriptor.expected_beats:
                payload = dict(self.data_offer(descriptor.event, position))
                if self.final_field is not None:
                    payload[self.final_field] = (
                        position + 1 == descriptor.expected_beats
                    )
                offers.append(EventOffer.constrained("W", payload=payload))
        else:
            # W is allowed before AW. A protocol-specific generator can choose
            # whether to exercise this unconstrained direction.
            offers.append(EventOffer.unconstrained("W"))
        offers.extend(self._ledger.event_offers(state.completions))
        return tuple(offers)

    def _add_joined(
        self,
        state: Axi4WriteState,
        transition,
    ) -> SemanticStep[Axi4WriteState, object]:
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        completions = self._ledger.add(
            state.completions, transition.emissions
        )
        return SemanticStep(
            Axi4WriteState(state.assembler, transition.state, completions)
        )

    def step(
        self, state: Axi4WriteState, event: CanonicalEvent
    ) -> SemanticStep[Axi4WriteState, object]:
        if event.kind == "AW":
            expected = self.count_of(event)
            current = state.assembler.current
            if self.final_field is not None and current and len(current) >= expected:
                return self._fault(
                    state,
                    "missing_final",
                    f"W burst reached {len(current)} beats before AW declared "
                    f"{expected} beats, without {self.final_field}",
                )
            if current:
                for index, data in enumerate(current):
                    reason = self.data_rule(event, index, data)
                    if reason is not None:
                        return self._fault(state, self.data_rule_name, reason)
            joined = self._join.add_descriptor(state.join, event)
            return self._add_joined(state, joined)

        if event.kind == "W":
            if state.join.descriptors:
                descriptor = state.join.descriptors[0]
                position = len(state.assembler.current)
                if position >= descriptor.expected_beats:
                    return self._fault(
                        state,
                        "beat_count",
                        "W burst exceeded the oldest AW length",
                    )
                expected_final = position + 1 == descriptor.expected_beats
                if (
                    self.final_field is not None
                    and event.payload.get(self.final_field) is not expected_final
                ):
                    return self._fault(
                        state,
                        "final_marker",
                        f"W beat {position + 1}/{descriptor.expected_beats} requires "
                        f"{self.final_field}={expected_final}",
                    )
                reason = self.data_rule(descriptor.event, position, event)
                if reason is not None:
                    return self._fault(state, self.data_rule_name, reason)

            assembled = self._assembler.step(state.assembler, event)
            if assembled.fault is not None:
                return SemanticStep(state, fault=assembled.fault)
            next_state = Axi4WriteState(
                assembled.state, state.join, state.completions
            )
            if assembled.emissions:
                joined = self._join.add_burst(
                    state.join, assembled.emissions[0]
                )
                added = self._add_joined(next_state, joined)
                if added.fault is not None:
                    return added
                next_state = added.state
            return SemanticStep(
                next_state,
                causal_predecessors=assembled.causal_predecessors,
            )

        if event.kind == "B":
            consumed = self._ledger.consume(state.completions, event)
            if consumed.fault is not None:
                return SemanticStep(state, fault=consumed.fault)
            return SemanticStep(
                Axi4WriteState(state.assembler, state.join, consumed.state),
                causal_predecessors=consumed.causal_predecessors,
            )

        return self._fault(
            state, "alphabet", f"unexpected AXI write event {event.kind!r}"
        )
