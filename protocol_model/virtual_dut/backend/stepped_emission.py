"""Bounded, caller-stepped release of backend port emissions.

This module refines an immediate event-level backend without assigning clock
or pin semantics to the refinement.  A scenario can map one explicit
``advance()`` opportunity to one cycle, but the backend itself only records
ordered service opportunities.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from types import MappingProxyType
from typing import Callable, Hashable, Mapping, TYPE_CHECKING

from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticFault,
)

from ..arbitration import round_robin_select
from .advance import ExplicitlyAdvanceableBackend
from .base import VirtualDutBackend
from .transition import DutTransition, PortEmission, PortInput

if TYPE_CHECKING:
    from ..binding.port import InterfaceAttachmentBinding


@dataclass(frozen=True)
class EmissionWaitContext:
    """Admission-time facts supplied to an emission wait policy."""

    batch_serial: int
    event_index: int
    event_count: int
    queued_event_count: int
    advance_index: int

    def __post_init__(self) -> None:
        for name in (
            "batch_serial",
            "event_index",
            "queued_event_count",
            "advance_index",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"emission wait {name} must be non-negative")
        if (
            not isinstance(self.event_count, int)
            or isinstance(self.event_count, bool)
            or self.event_count <= 0
        ):
            raise ValueError("emission wait event_count must be positive")
        if self.event_index >= self.event_count:
            raise ValueError("emission wait event_index exceeds its batch")


EmissionWaitPolicy = Callable[[PortEmission, EmissionWaitContext], int]
EmissionBatchOrderingKeyPolicy = Callable[
    [tuple[PortEmission, ...]], Hashable
]


class EmissionBatchScheduling(str, Enum):
    """How ready heads from accepted output batches share one emitter."""

    FIFO = "fifo"
    ROUND_ROBIN = "round_robin"


def _no_emission_wait(
    _emission: PortEmission, _context: EmissionWaitContext
) -> int:
    return 0


@dataclass(frozen=True)
class SteppedEmissionProfile:
    """Finite response storage and per-event wait selection.

    Capacity is counted in canonical output events.  For example, an AXI read
    burst with eight R beats reserves eight entries, while one B completion
    reserves one.  This makes the resource represented by the profile explicit
    instead of treating a large burst as an unbounded single token.

    FIFO scheduling drains each accepted output batch before the next one.
    Round-robin scheduling considers one head per live batch.  The wrapper's
    ordering-key policy suppresses later batches with the same key until the
    earlier batch completes, so a protocol adapter can permit only its legal
    interleavings.
    """

    capacity_events: int = 256
    wait_policy: EmissionWaitPolicy = _no_emission_wait
    scheduling: EmissionBatchScheduling | str = EmissionBatchScheduling.FIFO

    def __post_init__(self) -> None:
        if (
            not isinstance(self.capacity_events, int)
            or isinstance(self.capacity_events, bool)
            or self.capacity_events <= 0
        ):
            raise ValueError("stepped emission capacity must be positive")
        if not callable(self.wait_policy):
            raise TypeError("stepped emission wait policy must be callable")
        try:
            scheduling = EmissionBatchScheduling(self.scheduling)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "stepped emission requires a valid batch scheduling policy"
            ) from error
        object.__setattr__(self, "scheduling", scheduling)


@dataclass(frozen=True)
class DeferredPortEmission:
    """One queued output and the remaining empty service opportunities."""

    emission: PortEmission
    remaining_wait_steps: int
    batch_serial: int
    event_index: int
    event_count: int
    ordering_key: Hashable

    def __post_init__(self) -> None:
        if not isinstance(self.emission, PortEmission):
            raise TypeError("deferred emission requires PortEmission")
        for name in (
            "remaining_wait_steps",
            "batch_serial",
            "event_index",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"deferred emission {name} must be non-negative")
        if (
            not isinstance(self.event_count, int)
            or isinstance(self.event_count, bool)
            or self.event_count <= 0
        ):
            raise ValueError("deferred emission event_count must be positive")
        if self.event_index >= self.event_count:
            raise ValueError("deferred emission event_index exceeds its batch")
        try:
            hash(self.ordering_key)
        except TypeError as error:
            raise TypeError(
                "deferred emission ordering key must be hashable"
            ) from error


@dataclass(frozen=True)
class EmissionOffer:
    """Stable reference to one selected output that is not yet accepted."""

    batch_serial: int
    event_index: int
    emission: PortEmission

    def __post_init__(self) -> None:
        for value, subject in (
            (self.batch_serial, "batch serial"),
            (self.event_index, "event index"),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"emission offer {subject} must be non-negative")
        if not isinstance(self.emission, PortEmission):
            raise TypeError("emission offer requires PortEmission")

    @property
    def token(self) -> tuple[int, int]:
        return self.batch_serial, self.event_index


@dataclass(frozen=True)
class SteppedEmissionState:
    inner_state: object
    pending: tuple[DeferredPortEmission, ...] = ()
    next_batch_serial: int = 0
    advance_index: int = 0
    last_selected_batch_serial: int | None = None
    offered_id: tuple[int, int] | None = None

    def __post_init__(self) -> None:
        pending = tuple(self.pending)
        if any(not isinstance(item, DeferredPortEmission) for item in pending):
            raise TypeError("stepped emission state has an invalid pending item")
        for value, subject in (
            (self.next_batch_serial, "next batch serial"),
            (self.advance_index, "advance index"),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"stepped emission {subject} must be non-negative")
        if self.last_selected_batch_serial is not None and (
            not isinstance(self.last_selected_batch_serial, int)
            or isinstance(self.last_selected_batch_serial, bool)
            or self.last_selected_batch_serial < 0
        ):
            raise ValueError(
                "stepped emission last selected batch must be non-negative"
            )
        if self.offered_id is not None:
            if (
                not isinstance(self.offered_id, tuple)
                or len(self.offered_id) != 2
                or any(
                    not isinstance(value, int)
                    or isinstance(value, bool)
                    or value < 0
                    for value in self.offered_id
                )
            ):
                raise ValueError(
                    "stepped emission offered id requires two non-negative integers"
                )
            offered = next(
                (
                    item
                    for item in pending
                    if (item.batch_serial, item.event_index) == self.offered_id
                ),
                None,
            )
            if offered is None:
                raise ValueError(
                    "stepped emission offered id is not present in pending state"
                )
            if offered.remaining_wait_steps != 0:
                raise ValueError("stepped emission cannot offer a waiting event")
        if pending and self.next_batch_serial <= max(
            item.batch_serial for item in pending
        ):
            raise ValueError(
                "stepped emission next serial must exceed every pending batch"
            )
        object.__setattr__(self, "pending", pending)


class SteppedEmissionBackend(VirtualDutBackend):
    """Buffer an immediate backend's outputs and release them on advances.

    ``accept()`` still lets the wrapped backend consume an input atomically,
    but its output events enter a finite FIFO.  If the complete output batch
    does not fit, the input is not accepted and a ``ResourceDemand`` is
    returned.  Each explicit advance releases at most one event; a wait policy
    can insert empty advances before any event, including between AXI R beats.
    Optional round-robin scheduling retains batch boundaries and never makes a
    later same-key batch eligible while an earlier one remains pending.

    Wrapping another explicitly advanceable backend is deliberately rejected:
    composing two independent progress schedulers needs an explicit arbiter,
    rather than an implicit choice inside this small refinement.

    Capacity rejection speculatively evaluates then discards the wrapped
    transition, so this wrapper is intended for pure model backends.  An
    external backend with irreversible I/O must reserve admission before
    performing that I/O instead.
    """

    def __init__(
        self,
        inner: VirtualDutBackend,
        profile: SteppedEmissionProfile | None = None,
        *,
        batch_ordering_key: EmissionBatchOrderingKeyPolicy | None = None,
    ) -> None:
        if not isinstance(inner, VirtualDutBackend):
            raise TypeError("stepped emission wrapper requires a VirtualDutBackend")
        if isinstance(inner, ExplicitlyAdvanceableBackend):
            raise ValueError(
                "stepped emission wrapper requires a non-advanceable backend"
            )
        if profile is not None and not isinstance(
            profile, SteppedEmissionProfile
        ):
            raise TypeError("stepped emission wrapper requires a valid profile")
        if batch_ordering_key is not None and not callable(batch_ordering_key):
            raise TypeError(
                "stepped emission batch ordering key policy must be callable"
            )
        self.inner = inner
        self.profile = profile or SteppedEmissionProfile()
        self.batch_ordering_key = batch_ordering_key

    def initial_state(self) -> SteppedEmissionState:
        return SteppedEmissionState(self.inner.initial_state())

    def local_attachment_bindings(
        self,
    ) -> Mapping[str, "InterfaceAttachmentBinding"] | None:
        return self.inner.local_attachment_bindings()

    def boundary_projections(self) -> Mapping[str, object]:
        projected = dict(self.inner.boundary_projections())
        if "stepped_emission" in projected:
            raise ValueError(
                "wrapped backend already owns stepped_emission projection"
            )
        projected["stepped_emission"] = MappingProxyType(
            {
                "capacity_events": self.profile.capacity_events,
                "maximum_events_per_advance": 1,
                "batch_scheduling": self.profile.scheduling.value,
                "offer_accept_seam": True,
            }
        )
        return MappingProxyType(projected)

    def accept(self, state: object, action: PortInput) -> DutTransition:
        self._require_state(state)
        assert isinstance(state, SteppedEmissionState)
        inner_step = self.inner.accept(state.inner_state, action)
        if inner_step.fault is not None:
            return DutTransition(state, fault=inner_step.fault)
        if inner_step.blocked is not None:
            return DutTransition(state, blocked=inner_step.blocked)
        if not inner_step.emissions:
            return DutTransition(replace(state, inner_state=inner_step.state))

        event_count = len(inner_step.emissions)
        available = self.profile.capacity_events - len(state.pending)
        if event_count > available:
            return DutTransition(
                state,
                blocked=ResourceDemand(
                    "deferred_emission_buffer",
                    ConstraintScope.VIRTUAL_DUT,
                    required=event_count,
                    available=available,
                    capacity=self.profile.capacity_events,
                    reason=(
                        "complete output batch does not fit in the stepped "
                        f"emission buffer ({event_count} required, "
                        f"{available} available)"
                    ),
                    location=action.port,
                ),
            )

        try:
            ordering_key = (
                state.next_batch_serial
                if self.batch_ordering_key is None
                else self.batch_ordering_key(inner_step.emissions)
            )
            hash(ordering_key)
        except Exception as error:
            return DutTransition(
                state,
                fault=self._fault(
                    "ordering_key_policy",
                    "emission batch ordering-key policy raised "
                    f"{type(error).__name__}: {error}",
                ),
            )

        deferred: list[DeferredPortEmission] = []
        for index, emission in enumerate(inner_step.emissions):
            context = EmissionWaitContext(
                state.next_batch_serial,
                index,
                event_count,
                len(state.pending),
                state.advance_index,
            )
            try:
                wait_steps = self.profile.wait_policy(emission, context)
            except Exception as error:
                return DutTransition(
                    state,
                    fault=self._fault(
                        "wait_policy",
                        "emission wait policy raised "
                        f"{type(error).__name__}: {error}",
                    ),
                )
            if (
                not isinstance(wait_steps, int)
                or isinstance(wait_steps, bool)
                or wait_steps < 0
            ):
                return DutTransition(
                    state,
                    fault=self._fault(
                        "wait_policy",
                        "emission wait policy must return a non-negative integer",
                    ),
                )
            deferred.append(
                DeferredPortEmission(
                    emission,
                    wait_steps,
                    state.next_batch_serial,
                    index,
                    event_count,
                    ordering_key,
                )
            )

        return DutTransition(
            SteppedEmissionState(
                inner_step.state,
                (*state.pending, *deferred),
                state.next_batch_serial + 1,
                state.advance_index,
                state.last_selected_batch_serial,
                state.offered_id,
            )
        )

    def prepare_offer(self, state: object) -> DutTransition:
        """Spend one service opportunity selecting, but not consuming, output.

        Repeated calls while an offer is active return the same state.  A
        pin/cycle driver can therefore present the same payload while READY is
        low and call :meth:`accept_offer` only on the handshake edge.
        """

        self._require_state(state)
        assert isinstance(state, SteppedEmissionState)
        if state.offered_id is not None:
            return DutTransition(state)

        candidate = replace(state, advance_index=state.advance_index + 1)
        if not candidate.pending:
            return DutTransition(candidate)

        eligible = self._eligible_heads(candidate)
        ready = tuple(
            item for item in eligible if item.remaining_wait_steps == 0
        )

        eligible_ids = {
            (item.batch_serial, item.event_index) for item in eligible
        }
        aged = tuple(
            replace(
                item,
                remaining_wait_steps=item.remaining_wait_steps - 1,
            )
            if (
                (item.batch_serial, item.event_index) in eligible_ids
                and item.remaining_wait_steps > 0
            )
            else item
            for item in candidate.pending
        )
        candidate = replace(candidate, pending=aged)
        if not ready:
            return DutTransition(candidate)

        selected = self._select_ready_head(candidate, ready)
        return DutTransition(
            replace(
                candidate,
                offered_id=(selected.batch_serial, selected.event_index),
            )
        )

    def current_offer(self, state: object) -> EmissionOffer | None:
        """Return the stable selected output without changing ownership."""

        self._require_state(state)
        assert isinstance(state, SteppedEmissionState)
        if state.offered_id is None:
            return None
        item = next(
            item
            for item in state.pending
            if (item.batch_serial, item.event_index) == state.offered_id
        )
        return EmissionOffer(item.batch_serial, item.event_index, item.emission)

    def accept_offer(self, state: object) -> DutTransition:
        """Consume and emit the currently offered output exactly once."""

        self._require_state(state)
        assert isinstance(state, SteppedEmissionState)
        offer = self.current_offer(state)
        if offer is None:
            raise ValueError("stepped emission backend has no current offer")
        pending = list(state.pending)
        selected_position = next(
            index
            for index, item in enumerate(pending)
            if (item.batch_serial, item.event_index) == offer.token
        )
        selected = pending.pop(selected_position)
        return DutTransition(
            replace(
                state,
                pending=tuple(pending),
                offered_id=None,
                last_selected_batch_serial=(
                    selected.batch_serial
                    if self.profile.scheduling
                    is EmissionBatchScheduling.ROUND_ROBIN
                    else state.last_selected_batch_serial
                ),
            ),
            (selected.emission,),
        )

    def advance(
        self, state: object, *, steps: int = 1
    ) -> DutTransition:
        """Prepare and immediately accept output as an always-ready shortcut."""

        self._require_state(state)
        assert isinstance(state, SteppedEmissionState)
        if (
            not isinstance(steps, int)
            or isinstance(steps, bool)
            or steps <= 0
        ):
            raise ValueError("stepped emission advance steps must be positive")

        candidate = state
        emissions: list[PortEmission] = []
        for _ in range(steps):
            prepared = self.prepare_offer(candidate)
            candidate = prepared.state
            if self.current_offer(candidate) is None:
                continue
            accepted = self.accept_offer(candidate)
            candidate = accepted.state
            emissions.extend(accepted.emissions)
        return DutTransition(candidate, tuple(emissions))

    def _eligible_heads(
        self, state: SteppedEmissionState
    ) -> tuple[DeferredPortEmission, ...]:
        if self.profile.scheduling is EmissionBatchScheduling.FIFO:
            return (state.pending[0],)

        batch_heads: list[DeferredPortEmission] = []
        seen_batches: set[int] = set()
        for item in state.pending:
            if item.batch_serial in seen_batches:
                continue
            seen_batches.add(item.batch_serial)
            batch_heads.append(item)

        eligible: list[DeferredPortEmission] = []
        seen_ordering_keys: set[Hashable] = set()
        for item in batch_heads:
            if item.ordering_key in seen_ordering_keys:
                continue
            seen_ordering_keys.add(item.ordering_key)
            eligible.append(item)
        return tuple(eligible)

    def _select_ready_head(
        self,
        state: SteppedEmissionState,
        ready: tuple[DeferredPortEmission, ...],
    ) -> DeferredPortEmission:
        if self.profile.scheduling is EmissionBatchScheduling.FIFO:
            return ready[0]
        ordered_serials = tuple(
            item.batch_serial for item in self._eligible_heads(state)
        )
        ready_serials = tuple(item.batch_serial for item in ready)
        selected = round_robin_select(
            ordered_serials,
            ready_serials,
            after=state.last_selected_batch_serial,
        )
        assert selected is not None
        return next(item for item in ready if item.batch_serial == selected)

    def is_quiescent(self, state: object) -> bool:
        return (
            isinstance(state, SteppedEmissionState)
            and not state.pending
            and self.inner.is_quiescent(state.inner_state)
        )

    def pending_usage(
        self, state: SteppedEmissionState
    ) -> tuple[int, int]:
        self._require_state(state)
        return len(state.pending), self.profile.capacity_events

    def _require_state(self, state: object) -> None:
        if not isinstance(state, SteppedEmissionState):
            raise TypeError(
                "SteppedEmissionBackend requires SteppedEmissionState"
            )
        if len(state.pending) > self.profile.capacity_events:
            raise ValueError("stepped emission state exceeds configured capacity")

    @staticmethod
    def _fault(suffix: str, reason: str) -> SemanticFault:
        return SemanticFault(
            f"stepped_emission_backend.{suffix}",
            reason,
            ConstraintScope.VIRTUAL_DUT,
        )


def constant_emission_wait(
    *, initial_wait_steps: int = 0, inter_event_wait_steps: int = 0
) -> EmissionWaitPolicy:
    """Return a policy with one initial wait and a fixed inter-event gap."""

    for value, subject in (
        (initial_wait_steps, "initial wait"),
        (inter_event_wait_steps, "inter-event wait"),
    ):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ValueError(f"constant emission {subject} must be non-negative")

    def policy(
        _emission: PortEmission, context: EmissionWaitContext
    ) -> int:
        return (
            initial_wait_steps
            if context.event_index == 0
            else inter_event_wait_steps
        )

    return policy


__all__ = [
    "DeferredPortEmission",
    "EmissionBatchOrderingKeyPolicy",
    "EmissionBatchScheduling",
    "EmissionOffer",
    "EmissionWaitContext",
    "EmissionWaitPolicy",
    "SteppedEmissionBackend",
    "SteppedEmissionProfile",
    "SteppedEmissionState",
    "constant_emission_wait",
]
