"""A small executable REQ endpoint-to-endpoint transport path."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.observation import AtomicFrame
from protocol_model.semantics import (
    ConstraintScope,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)

from ..representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiChannelKind,
    ChiNetworkPacket,
    ChiProtocolFlit,
    ChiReqLCrdReturn,
)
from .endpoint import (
    ChiReqCaptureEndpoint,
    ChiReqCaptureState,
    ChiReqTxQueue,
    ChiReqTxQueueState,
)
from .link import (
    ChiLinkActivationPhase,
    ChiLinkActivationSignals,
    ChiReqChannelSignals,
    ChiReqTransfer,
    ChiReqTransferKind,
    ChiTransportLink,
)
from .session import ChiTransportLinkState


@dataclass(frozen=True)
class ChiReqEnqueue:
    """Place one routable REQ packet in the Transmitter's finite FIFO.

    The path owns the Network-packet-to-Link-flit boundary: callers provide a
    packet with explicit route identity and the helper wraps it in exactly one
    :class:`ChiProtocolFlit` before it reaches transport state or signals.
    """

    packet: ChiNetworkPacket
    resource_plane: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError("ChiReqEnqueue requires a ChiNetworkPacket")
        if self.packet.channel is not ChiChannelKind.REQ:
            raise TypeError("ChiReqEnqueue requires a REQ Network packet")


@dataclass(frozen=True)
class ChiReqDrain:
    """Let the receiving node consume captured protocol flits."""

    count: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.count, int)
            or isinstance(self.count, bool)
            or self.count <= 0
        ):
            raise ValueError("ChiReqDrain count must be positive")


@dataclass(frozen=True)
class ChiReqPathTick:
    """Advance the common-clock reference path by one sampling frame.

    ``active`` requests that the generated path remain in RUN.  Pending TX
    work also keeps it active until the queue drains.
    """

    active: bool = True

    def __post_init__(self) -> None:
        if type(self.active) is not bool:
            raise TypeError("ChiReqPathTick active must be bool")


ChiReqPathAction = ChiReqEnqueue | ChiReqDrain | ChiReqPathTick


@dataclass(frozen=True)
class ChiReqPointToPointState:
    next_tick: int
    link: ChiTransportLinkState
    transmitter: ChiReqTxQueueState
    receiver: ChiReqCaptureState


@dataclass(frozen=True)
class ChiReqPathObservation:
    """One generated frame plus its endpoint-visible state change."""

    frame: AtomicFrame
    phase: ChiLinkActivationPhase
    grants_by_plane: tuple[bool, ...]
    transfer: ChiReqTransfer | None
    tx_depth_before: int
    tx_depth_after: int
    rx_depth_before: int
    rx_depth_after: int

    @property
    def tick(self) -> int:
        return self.frame.tick


class ChiReqPointToPointSession(
    SemanticComponent[
        ChiReqPathAction,
        ChiReqPointToPointState,
        ChiReqPathObservation,
    ]
):
    """Compose a finite TX queue, one transport link, and an RX capture.

    This is a deterministic reference-path fixture, not a complete RN-I or
    Home Node.  It makes receiver slots, granted credits, the sender queue and
    accepted flits visible in one atomic state transition.
    """

    def __init__(
        self,
        link: ChiTransportLink,
        *,
        transmitter_capacity: int = 8,
        receiver_capacities_by_plane: tuple[int, ...] | None = None,
    ) -> None:
        if not isinstance(link, ChiTransportLink):
            raise TypeError("point-to-point path requires ChiTransportLink")
        req_profile = link.profile.request
        if (
            req_profile is None
            or link.profile.data is not None
            or link.profile.response is not None
            or link.profile.snoop is not None
        ):
            raise ValueError(
                "ChiReqPointToPointSession requires a REQ-only link profile"
            )
        receiver_capacities = (
            tuple(receiver_capacities_by_plane)
            if receiver_capacities_by_plane is not None
            else req_profile.credit_capacities
        )
        if len(receiver_capacities) != req_profile.resource_planes:
            raise ValueError(
                "receiver capacity planes must match the REQ link profile"
            )
        self.link = link
        self.name = f"{link.name}.req_point_to_point"
        self.link_session = link.open_session()
        self.transmitter = ChiReqTxQueue(
            link.transmitter,
            capacity=transmitter_capacity,
            resource_planes=req_profile.resource_planes,
        )
        self.receiver = ChiReqCaptureEndpoint(
            link.receiver,
            capacities_by_plane=receiver_capacities,
            credit_limits_by_plane=req_profile.credit_capacities,
        )

    def initial_state(self) -> ChiReqPointToPointState:
        return ChiReqPointToPointState(
            0,
            self.link_session.initial_state(),
            self.transmitter.initial_state(),
            self.receiver.initial_state(),
        )

    def is_quiescent(self, state: ChiReqPointToPointState) -> bool:
        return (
            isinstance(state, ChiReqPointToPointState)
            and state.transmitter.depth == 0
            and state.receiver.depth == 0
            and self.link_session.is_quiescent(state.link)
        )

    def step(
        self,
        state: ChiReqPointToPointState,
        action: ChiReqPathAction,
    ) -> SemanticStep[ChiReqPointToPointState, ChiReqPathObservation]:
        if not isinstance(state, ChiReqPointToPointState):
            raise TypeError(
                "point-to-point path requires ChiReqPointToPointState"
            )
        if isinstance(action, ChiReqEnqueue):
            return self._enqueue(state, action)
        if isinstance(action, ChiReqDrain):
            return self._drain(state, action)
        if isinstance(action, ChiReqPathTick):
            return self._tick(state, action)
        raise TypeError("unknown CHI REQ point-to-point action")

    def _enqueue(
        self,
        state: ChiReqPointToPointState,
        action: ChiReqEnqueue,
    ) -> SemanticStep[ChiReqPointToPointState, ChiReqPathObservation]:
        reasons = action.packet.explain_profile(
            self.link.profile.request.representation,
        )
        if reasons:
            return self._fault(
                state, "representation", "; ".join(reasons), ConstraintScope.EVENT
            )
        transition = self.transmitter.enqueue(
            state.transmitter,
            ChiProtocolFlit(action.packet),
            action.resource_plane,
        )
        if transition.blocked is not None:
            return SemanticStep(state, blocked=transition.blocked)
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        return SemanticStep(
            ChiReqPointToPointState(
                state.next_tick,
                state.link,
                transition.state,
                state.receiver,
            )
        )

    def _drain(
        self,
        state: ChiReqPointToPointState,
        action: ChiReqDrain,
    ) -> SemanticStep[ChiReqPointToPointState, ChiReqPathObservation]:
        transition = self.receiver.drain(state.receiver, action.count)
        if transition.blocked is not None:
            return SemanticStep(state, blocked=transition.blocked)
        if transition.fault is not None:
            return SemanticStep(state, fault=transition.fault)
        return SemanticStep(
            ChiReqPointToPointState(
                state.next_tick,
                state.link,
                state.transmitter,
                transition.state,
            )
        )

    def _tick(
        self,
        state: ChiReqPointToPointState,
        action: ChiReqPathTick,
    ) -> SemanticStep[ChiReqPointToPointState, ChiReqPathObservation]:
        previous_phase = state.link.activation.phase
        wants_run = action.active or state.transmitter.depth > 0
        phase = self._next_phase(
            previous_phase,
            wants_run=wants_run,
            has_pending=state.transmitter.depth > 0,
            has_credits=any(state.link.request.usable_credits_by_plane),
        )
        old_credits = state.link.request.usable_credits_by_plane
        queued = self.transmitter.head(state.transmitter)
        flit = None
        plane = 0
        if phase in (
            ChiLinkActivationPhase.RUN,
            ChiLinkActivationPhase.DEACTIVATE,
        ):
            if (
                queued is not None
                and old_credits[queued.resource_plane] > 0
            ):
                flit = queued.flit
                plane = queued.resource_plane
            elif phase is ChiLinkActivationPhase.DEACTIVATE:
                for candidate_plane, count in enumerate(old_credits):
                    if count:
                        flit = ChiReqLCrdReturn()
                        plane = candidate_plane
                        break

        grants = tuple(
            False for _ in self.link.profile.request.credit_capacities
        )
        if phase is ChiLinkActivationPhase.RUN:
            classification = (
                None
                if flit is None
                else CHI_ISSUE_H_CHANNEL_DOMAIN.classify(flit)
            )
            receiving_plane = (
                plane
                if (
                    classification is not None
                    and classification.is_protocol_flit
                )
                else None
            )
            grants = self.receiver.grant_vector(
                state.receiver,
                receiving_plane=receiving_plane,
            )

        request, acknowledge = {
            ChiLinkActivationPhase.STOP: (False, False),
            ChiLinkActivationPhase.ACTIVATE: (True, False),
            ChiLinkActivationPhase.RUN: (True, True),
            ChiLinkActivationPhase.DEACTIVATE: (False, True),
        }[phase]
        frame = AtomicFrame(
            state.next_tick,
            self.link.profile.clock,
            {
                self.link.profile.activation_observation:
                    ChiLinkActivationSignals(request, acknowledge),
                self.link.profile.request.observation: ChiReqChannelSignals(
                    flit_valid=flit is not None,
                    flit=flit,
                    resource_plane=plane,
                    lcrdv_by_plane=grants,
                ),
            },
            source=self.name,
        )
        link_transition = self.link_session.step(state.link, frame)
        if link_transition.fault is not None:
            return SemanticStep(state, fault=link_transition.fault)

        transfers = link_transition.emissions
        tx_state = state.transmitter
        transfer = None if not transfers else transfers[0]
        if transfer is not None and transfer.kind is ChiReqTransferKind.PROTOCOL:
            tx_transition = self.transmitter.commit_transfer(
                tx_state, transfer
            )
            if tx_transition.fault is not None:
                return SemanticStep(state, fault=tx_transition.fault)
            tx_state = tx_transition.state

        rx_transition = self.receiver.apply_frame(
            state.receiver, grants, transfers
        )
        if rx_transition.fault is not None:
            return SemanticStep(state, fault=rx_transition.fault)

        candidate = ChiReqPointToPointState(
            state.next_tick + 1,
            link_transition.state,
            tx_state,
            rx_transition.state,
        )
        invariant_fault = self._invariant_fault(candidate)
        if invariant_fault is not None:
            return SemanticStep(state, fault=invariant_fault)
        observation = ChiReqPathObservation(
            frame,
            phase,
            grants,
            transfer,
            state.transmitter.depth,
            tx_state.depth,
            state.receiver.depth,
            rx_transition.state.depth,
        )
        return SemanticStep(candidate, (observation,))

    @staticmethod
    def _next_phase(
        previous: ChiLinkActivationPhase,
        *,
        wants_run: bool,
        has_pending: bool,
        has_credits: bool,
    ) -> ChiLinkActivationPhase:
        if previous is ChiLinkActivationPhase.STOP:
            return (
                ChiLinkActivationPhase.ACTIVATE
                if wants_run
                else ChiLinkActivationPhase.STOP
            )
        if previous is ChiLinkActivationPhase.ACTIVATE:
            return ChiLinkActivationPhase.RUN
        if previous is ChiLinkActivationPhase.RUN:
            return (
                ChiLinkActivationPhase.RUN
                if wants_run or has_pending
                else ChiLinkActivationPhase.DEACTIVATE
            )
        if has_credits:
            return ChiLinkActivationPhase.DEACTIVATE
        return ChiLinkActivationPhase.STOP

    def _invariant_fault(
        self, state: ChiReqPointToPointState
    ) -> SemanticFault | None:
        link_credits = state.link.request.usable_credits_by_plane
        if state.receiver.reserved_by_plane != link_credits:
            return SemanticFault(
                f"{self.name}.credit_mirror",
                "receiver reservations disagree with transmitter-held credits",
                ConstraintScope.TRANSPORT,
                self.link.name,
            )
        if state.transmitter.depth > self.transmitter.capacity:
            return SemanticFault(
                f"{self.name}.tx_capacity",
                "transmitter queue exceeds its configured capacity",
                ConstraintScope.VIRTUAL_DUT,
                self.link.transmitter.qualified_name,
            )
        return None

    def _fault(
        self,
        state: ChiReqPointToPointState,
        suffix: str,
        reason: str,
        scope: ConstraintScope,
    ) -> SemanticStep[ChiReqPointToPointState, ChiReqPathObservation]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{suffix}",
                reason,
                scope,
                self.link.name,
            ),
        )


__all__ = [
    "ChiReqDrain",
    "ChiReqEnqueue",
    "ChiReqPathAction",
    "ChiReqPathObservation",
    "ChiReqPathTick",
    "ChiReqPointToPointSession",
    "ChiReqPointToPointState",
]
