"""Five-channel AXI4 AtomicFrame observation and shared reset lowering."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from protocol_model.link import LinkProtocol, LinkSessionState
from protocol_model.observation import (
    AtomicFrame,
    ReadyValidObserver,
    ReadyValidSignals,
    ResetEpochObserver,
    ResetEpochState,
)
from protocol_model.patterns import QuietConstraint, QuietMode, QuietState
from protocol_model.semantics import (
    CanonicalEvent,
    ConstraintKind,
    ConstraintScope,
    SemanticComponent,
    SemanticConstraint,
    SemanticFragment,
    SemanticStep,
    compose_fragments,
)

from .definition import build_axi4_link


@dataclass(frozen=True)
class Axi4ObservationState:
    channel_states: Mapping[str, ResetEpochState]
    quiet_states: Mapping[str, QuietState[bool]]
    link_state: LinkSessionState

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "channel_states", MappingProxyType(dict(self.channel_states))
        )
        object.__setattr__(
            self, "quiet_states", MappingProxyType(dict(self.quiet_states))
        )


@dataclass(frozen=True)
class Axi4ObservationPolicy:
    """Pin-observation restrictions kept separate from LinkProtocol profiles."""

    tied_inactive_channels: frozenset[str] = frozenset()


class Axi4ObservationSession(
    SemanticComponent[AtomicFrame, Axi4ObservationState, CanonicalEvent]
):
    """Lower five ready/valid lanes into one atomic LinkSession batch."""

    # Responses consume obligations that existed before this sampling edge.
    # W is lowered before AW so a same-frame address/data pair is correlated
    # without making a newly completed write visible to same-frame B.
    LOWERING_ORDER = ("B", "R", "W", "AW", "AR")

    def __init__(
        self,
        protocol: LinkProtocol | None = None,
        *,
        clock: str = "aclk",
        reset_lane: str = "reset",
        policy: Axi4ObservationPolicy | None = None,
    ) -> None:
        self.protocol = protocol or build_axi4_link()
        expected = {"AW", "W", "B", "AR", "R"}
        if set(self.protocol.channels) != expected:
            raise ValueError("AXI4 observation requires the five-channel link")
        self.name = f"{self.protocol.name}.observation"
        self.clock = clock
        self.reset_lane = reset_lane
        self.policy = policy or Axi4ObservationPolicy()
        unknown_quiet = self.policy.tied_inactive_channels - expected
        if unknown_quiet:
            raise ValueError(
                f"unknown AXI4 quiet channels: {sorted(unknown_quiet)!r}"
            )
        self.link_session = self.protocol.open_session()
        self.channel_observers = {}
        for name, channel in self.protocol.channels.items():
            ready_valid = ReadyValidObserver(
                f"{self.name}.{name}.ready_valid",
                name,
                channel.event,
                clock,
            )
            self.channel_observers[name] = ResetEpochObserver(
                f"{self.name}.{name}.reset_epoch",
                ready_valid,
                reset_lane,
                inactive=lambda frame, lane=name: self._lane_inactive(frame, lane),
                inactive_reason=f"{name} VALID must be low while reset is asserted",
            )
        self.quiet_constraints = {
            name: QuietConstraint(
                f"{self.name}.{name}.inactive",
                QuietMode.TIED,
                value_of=lambda frame, lane=name: frame.get(lane).valid,
                expected=False,
                location=f"{name}.valid",
            )
            for name in self.policy.tied_inactive_channels
        }

    @staticmethod
    def _lane_inactive(frame: AtomicFrame, lane: str) -> bool:
        try:
            signals = frame.get(lane)
        except KeyError:
            return False
        return isinstance(signals, ReadyValidSignals) and not signals.valid

    def initial_state(self) -> Axi4ObservationState:
        return Axi4ObservationState(
            {
                name: observer.initial_state()
                for name, observer in self.channel_observers.items()
            },
            {
                name: constraint.initial_state()
                for name, constraint in self.quiet_constraints.items()
            },
            self.link_session.initial_state(),
        )

    @property
    def semantics(self) -> SemanticFragment:
        lane_fragments = []
        for observer in self.channel_observers.values():
            lane_fragments.extend((observer.inner.semantics, observer.semantics))
        frame_policy = SemanticFragment(
            f"{self.name}.frame_policy",
            constraints=(
                SemanticConstraint(
                    f"{self.name}.atomic_commit",
                    "all transfers accepted at one AXI sampling edge commit or roll back together",
                    ConstraintScope.LINK,
                    kind=ConstraintKind.RELATION,
                    targets=self.LOWERING_ORDER,
                ),
                SemanticConstraint(
                    f"{self.name}.response_visibility",
                    "R and B consume obligations that existed before the current sampling edge",
                    ConstraintScope.LINK,
                    kind=ConstraintKind.RELATION,
                    targets=("AR", "R", "AW", "W", "B"),
                ),
                *(
                    SemanticConstraint(
                        f"{self.name}.{name}.tied_inactive",
                        f"{name} VALID remains low in this observation profile",
                        ConstraintScope.LINK,
                        targets=(f"{name}.valid",),
                    )
                    for name in sorted(self.quiet_constraints)
                ),
            ),
        )
        return compose_fragments(
            f"{self.name}.semantics", *lane_fragments, frame_policy
        )

    def is_quiescent(self, state: Axi4ObservationState) -> bool:
        return self.link_session.is_quiescent(state.link_state) and all(
            observer.is_quiescent(state.channel_states[name])
            for name, observer in self.channel_observers.items()
        )

    def step(
        self, state: Axi4ObservationState, frame: AtomicFrame
    ) -> SemanticStep[Axi4ObservationState, CanonicalEvent]:
        channel_states = {}
        events = []
        for name in self.LOWERING_ORDER:
            observer = self.channel_observers[name]
            transition = observer.step(state.channel_states[name], frame)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            channel_states[name] = transition.state
            events.extend(transition.emissions)

        quiet_states = {}
        for name, constraint in self.quiet_constraints.items():
            transition = constraint.step(state.quiet_states[name], frame)
            if transition.fault is not None:
                return SemanticStep(state, fault=transition.fault)
            quiet_states[name] = transition.state

        asserted = frame.get(self.reset_lane)
        if asserted:
            return SemanticStep(
                Axi4ObservationState(
                    channel_states,
                    quiet_states,
                    self.link_session.initial_state(),
                )
            )

        link_transition = self.link_session.step_batch(state.link_state, events)
        if link_transition.fault is not None:
            return SemanticStep(state, fault=link_transition.fault)
        return SemanticStep(
            Axi4ObservationState(
                channel_states, quiet_states, link_transition.state
            ),
            link_transition.emissions,
        )
