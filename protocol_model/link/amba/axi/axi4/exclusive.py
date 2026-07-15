"""AXI4 link-local exclusive access sequencing and response semantics."""

from __future__ import annotations

from dataclasses import dataclass, replace

from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintScope,
    EventOffer,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)


ERROR_RESPONSES = frozenset(("SLVERR", "DECERR"))
MATCH_FIELDS = ("addr", "region", "len", "size", "burst", "lock", "cache", "prot")


@dataclass(frozen=True)
class Axi4ReadContext:
    serial: int
    request: CanonicalEvent
    remaining: int
    response_class: str | None = None
    had_error: bool = False


@dataclass(frozen=True)
class Axi4Reservation:
    request: CanonicalEvent
    completion_index: int


@dataclass(frozen=True)
class Axi4WriteContext:
    serial: int
    request: CanonicalEvent
    exclusive_eligible: bool = False


@dataclass(frozen=True)
class Axi4ExclusiveState:
    reads: tuple[Axi4ReadContext, ...] = ()
    writes: tuple[Axi4WriteContext, ...] = ()
    reservations: tuple[Axi4Reservation, ...] = ()
    next_read_serial: int = 0
    next_write_serial: int = 0


@dataclass(frozen=True)
class Axi4ExclusiveMonitor(
    SemanticComponent[CanonicalEvent, Axi4ExclusiveState, object]
):
    """Check the exclusive relations decidable from one AXI4 link trace.

    A matching completed exclusive read makes EXOKAY possible for one later
    exclusive write. External writes can still make that write fail, so OKAY
    remains legal; invalidation by traffic on other links belongs to the
    composed system or memory endpoint.
    """

    name: str = "axi4.exclusive"

    @property
    def event_kinds(self) -> frozenset[str]:
        return frozenset(("AR", "R", "AW", "B"))

    def observes(self, event: CanonicalEvent) -> bool:
        return event.kind in self.event_kinds

    def initial_state(self) -> Axi4ExclusiveState:
        return Axi4ExclusiveState()

    def is_quiescent(self, state: Axi4ExclusiveState) -> bool:
        # A completed exclusive read does not oblige the manager to issue the
        # write half, so a latent reservation is a quiescent state.
        return not state.reads and not state.writes

    def resource_usage(self, state: Axi4ExclusiveState) -> dict[str, int]:
        return {f"{self.name}.reservations": len(state.reservations)}

    def _fault(
        self, state: Axi4ExclusiveState, rule: str, reason: str
    ) -> SemanticStep[Axi4ExclusiveState, object]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{rule}", reason, ConstraintScope.LINK
            ),
        )

    @staticmethod
    def _locked(event: CanonicalEvent) -> bool:
        return bool(int(event.payload["lock"]))

    @staticmethod
    def _matching_read(
        reservation: Axi4Reservation, write: CanonicalEvent
    ) -> bool:
        read = reservation.request
        return read.key == write.key and all(
            read.payload[field] == write.payload[field] for field in MATCH_FIELDS
        )

    @staticmethod
    def _first_for_key(contexts, key):
        return next(
            (
                (index, context)
                for index, context in enumerate(contexts)
                if context.request.key == key
            ),
            None,
        )

    @staticmethod
    def _response_offers(kind: str, key, responses) -> tuple[EventOffer, ...]:
        return tuple(
            EventOffer.constrained(kind, key=key, payload={"resp": response})
            for response in responses
        )

    def event_offers(self, state: Axi4ExclusiveState) -> tuple[EventOffer, ...]:
        offers = [EventOffer.unconstrained("AR"), EventOffer.unconstrained("AW")]
        seen = set()
        for context in state.reads:
            key = context.request.key
            if key in seen:
                continue
            seen.add(key)
            if not self._locked(context.request):
                responses = ("OKAY", "SLVERR", "DECERR")
            elif context.response_class is None:
                responses = ("OKAY", "EXOKAY", "SLVERR", "DECERR")
            else:
                responses = (
                    context.response_class,
                    "SLVERR",
                    "DECERR",
                )
            offers.extend(self._response_offers("R", key, responses))

        seen.clear()
        for context in state.writes:
            key = context.request.key
            if key in seen:
                continue
            seen.add(key)
            responses = ["OKAY", "SLVERR", "DECERR"]
            if context.exclusive_eligible:
                responses.insert(1, "EXOKAY")
            offers.extend(self._response_offers("B", key, responses))
        return tuple(offers)

    def _step_read_address(
        self, state: Axi4ExclusiveState, event: CanonicalEvent
    ) -> SemanticStep[Axi4ExclusiveState, object]:
        reservations = state.reservations
        if self._locked(event):
            # A later exclusive read with the same ID replaces the address
            # monitored for that ID.
            reservations = tuple(
                item for item in reservations if item.request.key != event.key
            )
        context = Axi4ReadContext(
            state.next_read_serial,
            event,
            int(event.payload["len"]) + 1,
        )
        return SemanticStep(
            replace(
                state,
                reads=state.reads + (context,),
                reservations=reservations,
                next_read_serial=state.next_read_serial + 1,
            )
        )

    def _step_read_data(
        self, state: Axi4ExclusiveState, event: CanonicalEvent
    ) -> SemanticStep[Axi4ExclusiveState, object]:
        selected = self._first_for_key(state.reads, event.key)
        if selected is None:
            return self._fault(
                state, "orphan_read_response", "R has no matching AR context"
            )
        index, context = selected
        response = str(event.payload["resp"])
        locked = self._locked(context.request)
        if not locked and response == "EXOKAY":
            return self._fault(
                state,
                "normal_read_exokay",
                "a normal read must not receive an EXOKAY response",
            )

        response_class = context.response_class
        if locked and response in {"OKAY", "EXOKAY"}:
            if response_class is not None and response != response_class:
                return self._fault(
                    state,
                    "mixed_read_response",
                    "one exclusive read transaction must not mix OKAY and EXOKAY",
                )
            response_class = response

        updated = replace(
            context,
            remaining=context.remaining - 1,
            response_class=response_class,
            had_error=context.had_error or response in ERROR_RESPONSES,
        )
        reads = list(state.reads)
        reservations = state.reservations
        if updated.remaining:
            reads[index] = updated
        else:
            del reads[index]
            superseded = any(
                item.request.key == context.request.key
                and self._locked(item.request)
                and item.serial > context.serial
                for item in reads
            )
            if (
                locked
                and updated.response_class == "EXOKAY"
                and not updated.had_error
                and not superseded
                and event.trace_index is not None
            ):
                reservations = tuple(
                    item
                    for item in reservations
                    if item.request.key != context.request.key
                ) + (Axi4Reservation(context.request, event.trace_index),)
        return SemanticStep(
            replace(state, reads=tuple(reads), reservations=reservations)
        )

    def _step_write_address(
        self, state: Axi4ExclusiveState, event: CanonicalEvent
    ) -> SemanticStep[Axi4ExclusiveState, object]:
        eligible = False
        reservations = state.reservations
        predecessors = ()
        if self._locked(event):
            pending = next(
                (
                    item
                    for item in state.reads
                    if item.request.key == event.key
                    and self._locked(item.request)
                ),
                None,
            )
            if pending is not None:
                return self._fault(
                    state,
                    "write_before_read_complete",
                    "exclusive write started before its same-ID exclusive read completed",
                )
            match = next(
                (
                    item
                    for item in reservations
                    if self._matching_read(item, event)
                ),
                None,
            )
            if match is not None:
                eligible = True
                predecessors = (match.completion_index,)
                reservations = tuple(
                    item for item in reservations if item is not match
                )
        context = Axi4WriteContext(
            state.next_write_serial, event, eligible
        )
        return SemanticStep(
            replace(
                state,
                writes=state.writes + (context,),
                reservations=reservations,
                next_write_serial=state.next_write_serial + 1,
            ),
            causal_predecessors=predecessors,
        )

    def _step_write_response(
        self, state: Axi4ExclusiveState, event: CanonicalEvent
    ) -> SemanticStep[Axi4ExclusiveState, object]:
        selected = self._first_for_key(state.writes, event.key)
        if selected is None:
            return self._fault(
                state, "orphan_write_response", "B has no matching AW context"
            )
        index, context = selected
        response = str(event.payload["resp"])
        if response == "EXOKAY" and not self._locked(context.request):
            return self._fault(
                state,
                "normal_write_exokay",
                "a normal write must not receive an EXOKAY response",
            )
        if response == "EXOKAY" and not context.exclusive_eligible:
            return self._fault(
                state,
                "unmatched_success",
                "EXOKAY requires a matching completed exclusive read sequence",
            )
        writes = list(state.writes)
        del writes[index]
        return SemanticStep(replace(state, writes=tuple(writes)))

    def step(
        self, state: Axi4ExclusiveState, event: CanonicalEvent
    ) -> SemanticStep[Axi4ExclusiveState, object]:
        if event.kind == "AR":
            return self._step_read_address(state, event)
        if event.kind == "R":
            return self._step_read_data(state, event)
        if event.kind == "AW":
            return self._step_write_address(state, event)
        if event.kind == "B":
            return self._step_write_response(state, event)
        return self._fault(
            state, "alphabet", f"unexpected AXI exclusive event {event.kind!r}"
        )
