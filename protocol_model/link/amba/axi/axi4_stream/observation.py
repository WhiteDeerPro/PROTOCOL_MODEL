"""Single-lane AXI4-Stream AtomicFrame observation."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.link import LinkProtocol, LinkSessionState
from protocol_model.observation import (
    AtomicFrame,
    ReadyValidObserver,
    ReadyValidSignals,
    ResetEpochObserver,
    ResetEpochState,
)
from protocol_model.semantics import CanonicalEvent, SemanticComponent, SemanticStep

from .definition import Axi4StreamConfig, build_axi4_stream_link


@dataclass(frozen=True)
class Axi4StreamObservationState:
    lane_state: ResetEpochState
    link_state: LinkSessionState


class Axi4StreamObservationSession(
    SemanticComponent[AtomicFrame, Axi4StreamObservationState, CanonicalEvent]
):
    def __init__(
        self,
        protocol: LinkProtocol | None = None,
        *,
        config: Axi4StreamConfig | None = None,
        clock: str = "aclk",
        lane: str = "T",
        reset_lane: str = "reset",
    ) -> None:
        if protocol is not None and config is not None:
            raise ValueError("select either an AXI4-Stream protocol or config")
        self.protocol = protocol or build_axi4_stream_link(config)
        if set(self.protocol.channels) != {"T"}:
            raise ValueError("AXI4-Stream observation requires one T channel")
        self.name = f"{self.protocol.name}.observation"
        self.reset_lane = reset_lane
        ready_valid = ReadyValidObserver(
            f"{self.name}.ready_valid",
            lane,
            self.protocol.channels["T"].event,
            clock,
        )
        self.observer = ResetEpochObserver(
            f"{self.name}.reset_epoch",
            ready_valid,
            reset_lane,
            inactive=lambda frame: self._lane_inactive(frame, lane),
            inactive_reason="TVALID must be low while reset is asserted",
        )
        self.link_session = self.protocol.open_session()

    @staticmethod
    def _lane_inactive(frame: AtomicFrame, lane: str) -> bool:
        try:
            signals = frame.get(lane)
        except KeyError:
            return False
        return isinstance(signals, ReadyValidSignals) and not signals.valid

    @property
    def semantics(self):
        from protocol_model.semantics import compose_fragments

        return compose_fragments(
            f"{self.name}.semantics",
            self.observer.inner.semantics,
            self.observer.semantics,
        )

    def initial_state(self) -> Axi4StreamObservationState:
        return Axi4StreamObservationState(
            self.observer.initial_state(), self.link_session.initial_state()
        )

    def is_quiescent(self, state: Axi4StreamObservationState) -> bool:
        return self.observer.is_quiescent(
            state.lane_state
        ) and self.link_session.is_quiescent(state.link_state)

    def step(
        self, state: Axi4StreamObservationState, frame: AtomicFrame
    ) -> SemanticStep[Axi4StreamObservationState, CanonicalEvent]:
        observed = self.observer.step(state.lane_state, frame)
        if observed.fault is not None:
            return SemanticStep(state, fault=observed.fault)
        if frame.get(self.reset_lane):
            return SemanticStep(
                Axi4StreamObservationState(
                    observed.state, self.link_session.initial_state()
                )
            )
        linked = self.link_session.step_batch(state.link_state, observed.emissions)
        if linked.fault is not None:
            return SemanticStep(state, fault=linked.fault)
        return SemanticStep(
            Axi4StreamObservationState(observed.state, linked.state),
            linked.emissions,
        )
