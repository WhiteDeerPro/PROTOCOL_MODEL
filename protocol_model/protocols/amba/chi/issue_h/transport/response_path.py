"""A finite RSP-only endpoint-to-endpoint CHI transport path.

This deterministic reference fixture mirrors the existing DAT path: a finite
protocol-flit FIFO, one atomic transport link, and a receiver capture share a
single scalar L-Credit account.  It transports RetryAck and PCrdGrant but does
not interpret their transaction-level Retry lifecycle.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.observation import AtomicFrame
from protocol_model.semantics import (
    ConstraintScope,
    ResourceDemand,
    SemanticComponent,
    SemanticFault,
    SemanticStep,
)

from ..representation import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiChannelKind,
    ChiNetworkPacket,
    ChiProtocolFlit,
    ChiRspLCrdReturn,
)
from .link import (
    ChiLinkActivationPhase,
    ChiLinkActivationSignals,
    ChiRspChannelSignals,
    ChiRspTransfer,
    ChiRspTransferKind,
    ChiTransportLink,
)
from .session import ChiTransportLinkState


@dataclass(frozen=True)
class ChiRspEnqueue:
    """Place one routable RSP packet in the finite Transmitter FIFO.

    Packet-to-flit lowering happens once at this helper boundary.
    """

    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError("ChiRspEnqueue requires a ChiNetworkPacket")
        if self.packet.channel is not ChiChannelKind.RSP:
            raise TypeError("ChiRspEnqueue requires an RSP Network packet")


@dataclass(frozen=True)
class ChiRspDrain:
    """Let the receiving endpoint consume captured protocol flits."""

    count: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.count, int)
            or isinstance(self.count, bool)
            or self.count <= 0
        ):
            raise ValueError("ChiRspDrain count must be positive")


@dataclass(frozen=True)
class ChiRspPathTick:
    """Advance the common-clock path by one atomic sampling frame."""

    active: bool = True

    def __post_init__(self) -> None:
        if type(self.active) is not bool:
            raise TypeError("ChiRspPathTick active must be bool")


ChiRspPathAction = ChiRspEnqueue | ChiRspDrain | ChiRspPathTick


@dataclass(frozen=True)
class ChiRspQueuedFlit:
    """One protocol flit waiting in the bounded RSP Transmitter FIFO."""

    serial: int
    flit: ChiProtocolFlit


@dataclass(frozen=True)
class ChiRspTxQueueState:
    pending: tuple[ChiRspQueuedFlit, ...] = ()
    next_serial: int = 0
    sent_count: int = 0

    @property
    def depth(self) -> int:
        return len(self.pending)


@dataclass(frozen=True)
class ChiRspCaptureState:
    """Accepted responses plus receiver slots reserved by L-Credits."""

    captured: tuple[ChiRspTransfer, ...] = ()
    reserved_credits: int = 0
    received_count: int = 0
    returned_credit_count: int = 0

    @property
    def depth(self) -> int:
        return len(self.captured)


@dataclass(frozen=True)
class ChiRspPointToPointState:
    next_tick: int
    link: ChiTransportLinkState
    transmitter: ChiRspTxQueueState
    receiver: ChiRspCaptureState


@dataclass(frozen=True)
class ChiRspPathObservation:
    """One generated link frame and its endpoint-visible state change."""

    frame: AtomicFrame
    phase: ChiLinkActivationPhase
    grant: bool
    transfer: ChiRspTransfer | None
    tx_depth_before: int
    tx_depth_after: int
    rx_depth_before: int
    rx_depth_after: int

    @property
    def tick(self) -> int:
        return self.frame.tick


class ChiRspPointToPointSession(
    SemanticComponent[
        ChiRspPathAction,
        ChiRspPointToPointState,
        ChiRspPathObservation,
    ]
):
    """Compose a finite RSP TX queue, atomic link, and RX capture.

    The receiver reservation mirrors credits currently held by the
    Transmitter.  Flit selection observes frame-start credits, so a grant in
    the same frame cannot authorize a protocol transfer in that frame.
    """

    def __init__(
        self,
        link: ChiTransportLink,
        *,
        transmitter_capacity: int = 8,
        receiver_capacity: int | None = None,
    ) -> None:
        if not isinstance(link, ChiTransportLink):
            raise TypeError("RSP point-to-point path requires ChiTransportLink")
        response_profile = link.profile.response
        if (
            link.profile.request is not None
            or link.profile.data is not None
            or link.profile.snoop is not None
            or response_profile is None
        ):
            raise ValueError(
                "ChiRspPointToPointSession requires an RSP-only link profile"
            )
        if (
            not isinstance(transmitter_capacity, int)
            or isinstance(transmitter_capacity, bool)
            or transmitter_capacity <= 0
        ):
            raise ValueError("RSP Transmitter capacity must be positive")
        capture_capacity = (
            response_profile.credit_capacity
            if receiver_capacity is None
            else receiver_capacity
        )
        if (
            not isinstance(capture_capacity, int)
            or isinstance(capture_capacity, bool)
            or capture_capacity <= 0
        ):
            raise ValueError("RSP receiver capacity must be positive")
        if capture_capacity < response_profile.credit_capacity:
            raise ValueError(
                "RSP receiver capacity cannot be smaller than its credit limit"
            )
        self.link = link
        self.name = f"{link.name}.rsp_point_to_point"
        self.link_session = link.open_session()
        self.transmitter_capacity = transmitter_capacity
        self.receiver_capacity = capture_capacity
        self.credit_limit = response_profile.credit_capacity

    def initial_state(self) -> ChiRspPointToPointState:
        return ChiRspPointToPointState(
            0,
            self.link_session.initial_state(),
            ChiRspTxQueueState(),
            ChiRspCaptureState(),
        )

    def is_quiescent(self, state: ChiRspPointToPointState) -> bool:
        return (
            isinstance(state, ChiRspPointToPointState)
            and state.transmitter.depth == 0
            and state.receiver.depth == 0
            and self.link_session.is_quiescent(state.link)
        )

    def step(
        self,
        state: ChiRspPointToPointState,
        action: ChiRspPathAction,
    ) -> SemanticStep[ChiRspPointToPointState, ChiRspPathObservation]:
        if not isinstance(state, ChiRspPointToPointState):
            raise TypeError("RSP path requires ChiRspPointToPointState")
        invariant_fault = self._invariant_fault(state)
        if invariant_fault is not None:
            return SemanticStep(state, fault=invariant_fault)
        if isinstance(action, ChiRspEnqueue):
            return self._enqueue(state, action)
        if isinstance(action, ChiRspDrain):
            return self._drain(state, action)
        if isinstance(action, ChiRspPathTick):
            return self._tick(state, action)
        raise TypeError("unknown CHI RSP point-to-point action")

    def _enqueue(
        self,
        state: ChiRspPointToPointState,
        action: ChiRspEnqueue,
    ) -> SemanticStep[ChiRspPointToPointState, ChiRspPathObservation]:
        response_profile = self.link.profile.response
        assert response_profile is not None
        reasons = action.packet.explain_profile(
            response_profile.representation,
        )
        if reasons:
            return self._fault(
                state,
                "representation",
                "; ".join(reasons),
                ConstraintScope.EVENT,
            )
        tx = state.transmitter
        if tx.depth >= self.transmitter_capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    "chi.rsp_tx_queue.slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.transmitter_capacity,
                    reason="RSP transmitter queue is full",
                    location=self.link.transmitter.qualified_name,
                ),
            )
        entry = ChiRspQueuedFlit(
            tx.next_serial,
            ChiProtocolFlit(action.packet),
        )
        candidate_tx = ChiRspTxQueueState(
            tx.pending + (entry,),
            tx.next_serial + 1,
            tx.sent_count,
        )
        return SemanticStep(
            ChiRspPointToPointState(
                state.next_tick,
                state.link,
                candidate_tx,
                state.receiver,
            )
        )

    def _drain(
        self,
        state: ChiRspPointToPointState,
        action: ChiRspDrain,
    ) -> SemanticStep[ChiRspPointToPointState, ChiRspPathObservation]:
        rx = state.receiver
        if action.count > rx.depth:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    "chi.rsp_capture.flit",
                    ConstraintScope.VIRTUAL_DUT,
                    required=action.count,
                    available=rx.depth,
                    capacity=self.receiver_capacity,
                    reason=(
                        "RSP receiver has fewer captured flits than requested"
                    ),
                    location=self.link.receiver.qualified_name,
                ),
            )
        candidate_rx = ChiRspCaptureState(
            rx.captured[action.count :],
            rx.reserved_credits,
            rx.received_count,
            rx.returned_credit_count,
        )
        return SemanticStep(
            ChiRspPointToPointState(
                state.next_tick,
                state.link,
                state.transmitter,
                candidate_rx,
            )
        )

    def _tick(
        self,
        state: ChiRspPointToPointState,
        action: ChiRspPathTick,
    ) -> SemanticStep[ChiRspPointToPointState, ChiRspPathObservation]:
        assert state.link.response is not None
        previous_phase = state.link.activation.phase
        pending = state.transmitter.depth > 0
        wants_run = action.active or pending
        old_credit = state.link.response.usable_credits
        phase = self._next_phase(
            previous_phase,
            wants_run=wants_run,
            has_pending=pending,
            has_credits=old_credit > 0,
        )

        queued = (
            None
            if not state.transmitter.pending
            else state.transmitter.pending[0]
        )
        flit: ChiProtocolFlit | ChiRspLCrdReturn | None = None
        if phase in (
            ChiLinkActivationPhase.RUN,
            ChiLinkActivationPhase.DEACTIVATE,
        ):
            if queued is not None and old_credit > 0:
                flit = queued.flit
            elif phase is ChiLinkActivationPhase.DEACTIVATE and old_credit > 0:
                flit = ChiRspLCrdReturn()

        receiving_protocol = (
            flit is not None
            and CHI_ISSUE_H_CHANNEL_DOMAIN.classify(flit).is_protocol_flit
        )
        grant = False
        if phase is ChiLinkActivationPhase.RUN:
            grant = self._can_grant(
                state.receiver,
                receiving_protocol=receiving_protocol,
            )

        request, acknowledge = {
            ChiLinkActivationPhase.STOP: (False, False),
            ChiLinkActivationPhase.ACTIVATE: (True, False),
            ChiLinkActivationPhase.RUN: (True, True),
            ChiLinkActivationPhase.DEACTIVATE: (False, True),
        }[phase]
        response_profile = self.link.profile.response
        assert response_profile is not None
        frame = AtomicFrame(
            state.next_tick,
            self.link.profile.clock,
            {
                self.link.profile.activation_observation:
                    ChiLinkActivationSignals(request, acknowledge),
                response_profile.observation: ChiRspChannelSignals(
                    flit_valid=flit is not None,
                    flit=flit,
                    lcrdv=grant,
                ),
            },
            source=self.name,
        )
        link_transition = self.link_session.step(state.link, frame)
        if link_transition.fault is not None:
            return SemanticStep(state, fault=link_transition.fault)
        if len(link_transition.emissions) > 1 or any(
            not isinstance(item, ChiRspTransfer)
            for item in link_transition.emissions
        ):
            return self._fault(
                state,
                "link_emission",
                "RSP-only link emitted an unexpected transfer set",
                ConstraintScope.TRANSPORT,
            )
        transfer = (
            None
            if not link_transition.emissions
            else link_transition.emissions[0]
        )
        tx_transition = self._apply_tx_transfer(state.transmitter, transfer)
        if tx_transition.fault is not None:
            return SemanticStep(state, fault=tx_transition.fault)
        rx_transition = self._apply_rx_frame(
            state.receiver,
            grant=grant,
            transfer=transfer,
        )
        if rx_transition.fault is not None:
            return SemanticStep(state, fault=rx_transition.fault)

        candidate = ChiRspPointToPointState(
            state.next_tick + 1,
            link_transition.state,
            tx_transition.state,
            rx_transition.state,
        )
        invariant_fault = self._invariant_fault(candidate)
        if invariant_fault is not None:
            return SemanticStep(state, fault=invariant_fault)
        observation = ChiRspPathObservation(
            frame,
            phase,
            grant,
            transfer,
            state.transmitter.depth,
            candidate.transmitter.depth,
            state.receiver.depth,
            candidate.receiver.depth,
        )
        return SemanticStep(candidate, (observation,))

    def _can_grant(
        self,
        state: ChiRspCaptureState,
        *,
        receiving_protocol: bool,
    ) -> bool:
        receiving = int(receiving_protocol)
        remaining_reservations = state.reserved_credits - receiving
        captured_after = state.depth + receiving
        return (
            remaining_reservations < self.credit_limit
            and captured_after + remaining_reservations
            < self.receiver_capacity
        )

    def _apply_tx_transfer(
        self,
        state: ChiRspTxQueueState,
        transfer: ChiRspTransfer | None,
    ) -> SemanticStep[ChiRspTxQueueState, ChiRspQueuedFlit]:
        if transfer is None or (
            transfer.kind is ChiRspTransferKind.LINK_CREDIT_RETURN
        ):
            return SemanticStep(state)
        if not state.pending:
            return self._tx_fault(
                state,
                "empty_commit",
                "the link accepted a protocol flit from an empty RSP FIFO",
            )
        head = state.pending[0]
        if transfer.flit != head.flit:
            return self._tx_fault(
                state,
                "head_mismatch",
                "accepted transfer does not match the RSP FIFO head",
            )
        return SemanticStep(
            ChiRspTxQueueState(
                state.pending[1:],
                state.next_serial,
                state.sent_count + 1,
            ),
            (head,),
        )

    def _apply_rx_frame(
        self,
        state: ChiRspCaptureState,
        *,
        grant: bool,
        transfer: ChiRspTransfer | None,
    ) -> SemanticStep[ChiRspCaptureState, ChiRspTransfer]:
        captured = state.captured
        reserved = state.reserved_credits
        received = 0
        returned = 0
        if transfer is not None:
            if reserved == 0:
                return self._rx_fault(
                    state,
                    "unreserved_transfer",
                    "receiver observed an RSP transfer without an old reservation",
                )
            reserved -= 1
            if transfer.kind is ChiRspTransferKind.PROTOCOL:
                captured += (transfer,)
                received = 1
            else:
                returned = 1
        reserved += int(grant)
        candidate = ChiRspCaptureState(
            captured,
            reserved,
            state.received_count + received,
            state.returned_credit_count + returned,
        )
        if candidate.reserved_credits > self.credit_limit:
            return self._rx_fault(
                state,
                "credit_limit",
                "RSP receiver credit reservations exceed their limit",
            )
        if candidate.depth + candidate.reserved_credits > self.receiver_capacity:
            return self._rx_fault(
                state,
                "capacity",
                "RSP receiver slots are overcommitted",
            )
        emissions = () if transfer is None else (transfer,)
        return SemanticStep(candidate, emissions)

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
        self, state: ChiRspPointToPointState
    ) -> SemanticFault | None:
        if state.link.response is None:
            return SemanticFault(
                f"{self.name}.response_state",
                "RSP-only path has no RSP link state",
                ConstraintScope.TRANSPORT,
                self.link.name,
            )
        if (
            state.receiver.reserved_credits
            != state.link.response.usable_credits
        ):
            return SemanticFault(
                f"{self.name}.credit_mirror",
                "receiver reservation disagrees with Transmitter-held credit",
                ConstraintScope.TRANSPORT,
                self.link.name,
            )
        if state.transmitter.depth > self.transmitter_capacity:
            return SemanticFault(
                f"{self.name}.tx_capacity",
                "RSP Transmitter FIFO exceeds its configured capacity",
                ConstraintScope.VIRTUAL_DUT,
                self.link.transmitter.qualified_name,
            )
        if (
            state.receiver.depth + state.receiver.reserved_credits
            > self.receiver_capacity
        ):
            return SemanticFault(
                f"{self.name}.rx_capacity",
                "RSP receiver capture and reservations exceed capacity",
                ConstraintScope.VIRTUAL_DUT,
                self.link.receiver.qualified_name,
            )
        return None

    def _tx_fault(
        self,
        state: ChiRspTxQueueState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiRspTxQueueState, ChiRspQueuedFlit]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.tx.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.link.transmitter.qualified_name,
            ),
        )

    def _rx_fault(
        self,
        state: ChiRspCaptureState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiRspCaptureState, ChiRspTransfer]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.rx.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.link.receiver.qualified_name,
            ),
        )

    def _fault(
        self,
        state: ChiRspPointToPointState,
        suffix: str,
        reason: str,
        scope: ConstraintScope,
    ) -> SemanticStep[ChiRspPointToPointState, ChiRspPathObservation]:
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
    "ChiRspCaptureState",
    "ChiRspDrain",
    "ChiRspEnqueue",
    "ChiRspPathAction",
    "ChiRspPathObservation",
    "ChiRspPathTick",
    "ChiRspPointToPointSession",
    "ChiRspPointToPointState",
    "ChiRspQueuedFlit",
    "ChiRspTxQueueState",
]
