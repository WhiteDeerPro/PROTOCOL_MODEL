"""A finite DAT-only endpoint-to-endpoint CHI transport path.

The path composes a bounded protocol-flit FIFO, the existing atomic transport
link session, and a bounded receiver capture.  It is a deterministic reference
fixture for one directed DAT channel, not a complete CHI node or transaction
engine.
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
    ChiDatLCrdReturn,
    ChiNetworkPacket,
    ChiProtocolFlit,
)
from .link import (
    ChiDatChannelSignals,
    ChiDatTransfer,
    ChiDatTransferKind,
    ChiLinkActivationPhase,
    ChiLinkActivationSignals,
    ChiTransportLink,
)
from .session import ChiTransportLinkState


@dataclass(frozen=True)
class ChiDatEnqueue:
    """Place one routable DAT packet in the finite Transmitter FIFO.

    Packet-to-flit lowering happens once at this helper boundary.
    """

    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError("ChiDatEnqueue requires a ChiNetworkPacket")
        if self.packet.channel is not ChiChannelKind.DAT:
            raise TypeError("ChiDatEnqueue requires a DAT Network packet")


@dataclass(frozen=True)
class ChiDatDrain:
    """Let the receiving endpoint consume captured protocol flits."""

    count: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.count, int)
            or isinstance(self.count, bool)
            or self.count <= 0
        ):
            raise ValueError("ChiDatDrain count must be positive")


@dataclass(frozen=True)
class ChiDatPathTick:
    """Advance the common-clock path by one atomic sampling frame.

    ``active`` asks the generated path to remain in RUN.  Pending Transmitter
    work also keeps RUN requested until the finite FIFO drains.
    """

    active: bool = True

    def __post_init__(self) -> None:
        if type(self.active) is not bool:
            raise TypeError("ChiDatPathTick active must be bool")


ChiDatPathAction = ChiDatEnqueue | ChiDatDrain | ChiDatPathTick


@dataclass(frozen=True)
class ChiDatQueuedFlit:
    """One protocol flit waiting in the bounded DAT Transmitter FIFO."""

    serial: int
    flit: ChiProtocolFlit


@dataclass(frozen=True)
class ChiDatTxQueueState:
    pending: tuple[ChiDatQueuedFlit, ...] = ()
    next_serial: int = 0
    sent_count: int = 0

    @property
    def depth(self) -> int:
        return len(self.pending)


@dataclass(frozen=True)
class ChiDatCaptureState:
    """Accepted data plus receiver slots reserved by outstanding credits."""

    captured: tuple[ChiDatTransfer, ...] = ()
    reserved_credits: int = 0
    received_count: int = 0
    returned_credit_count: int = 0

    @property
    def depth(self) -> int:
        return len(self.captured)


@dataclass(frozen=True)
class ChiDatPointToPointState:
    next_tick: int
    link: ChiTransportLinkState
    transmitter: ChiDatTxQueueState
    receiver: ChiDatCaptureState


@dataclass(frozen=True)
class ChiDatPathObservation:
    """One generated link frame and its endpoint-visible state change."""

    frame: AtomicFrame
    phase: ChiLinkActivationPhase
    grant: bool
    transfer: ChiDatTransfer | None
    tx_depth_before: int
    tx_depth_after: int
    rx_depth_before: int
    rx_depth_after: int

    @property
    def tick(self) -> int:
        return self.frame.tick


class ChiDatPointToPointSession(
    SemanticComponent[
        ChiDatPathAction,
        ChiDatPointToPointState,
        ChiDatPathObservation,
    ]
):
    """Compose a finite DAT TX queue, atomic link, and RX capture.

    Receiver reservations mirror credits held at the Transmitter.  A transfer
    therefore consumes a reservation and an old credit in the same atomic
    step.  A simultaneous grant can replace that credit, but it cannot
    authorize the transfer because flit selection observes frame-start state.
    """

    def __init__(
        self,
        link: ChiTransportLink,
        *,
        transmitter_capacity: int = 8,
        receiver_capacity: int | None = None,
    ) -> None:
        if not isinstance(link, ChiTransportLink):
            raise TypeError("DAT point-to-point path requires ChiTransportLink")
        data_profile = link.profile.data
        if (
            link.profile.request is not None
            or link.profile.response is not None
            or link.profile.snoop is not None
            or data_profile is None
        ):
            raise ValueError(
                "ChiDatPointToPointSession requires a DAT-only link profile"
            )
        if (
            not isinstance(transmitter_capacity, int)
            or isinstance(transmitter_capacity, bool)
            or transmitter_capacity <= 0
        ):
            raise ValueError("DAT Transmitter capacity must be positive")
        capture_capacity = (
            data_profile.credit_capacity
            if receiver_capacity is None
            else receiver_capacity
        )
        if (
            not isinstance(capture_capacity, int)
            or isinstance(capture_capacity, bool)
            or capture_capacity <= 0
        ):
            raise ValueError("DAT receiver capacity must be positive")
        if capture_capacity < data_profile.credit_capacity:
            raise ValueError(
                "DAT receiver capacity cannot be smaller than its credit limit"
            )
        self.link = link
        self.name = f"{link.name}.dat_point_to_point"
        self.link_session = link.open_session()
        self.transmitter_capacity = transmitter_capacity
        self.receiver_capacity = capture_capacity
        self.credit_limit = data_profile.credit_capacity

    def initial_state(self) -> ChiDatPointToPointState:
        return ChiDatPointToPointState(
            0,
            self.link_session.initial_state(),
            ChiDatTxQueueState(),
            ChiDatCaptureState(),
        )

    def is_quiescent(self, state: ChiDatPointToPointState) -> bool:
        return (
            isinstance(state, ChiDatPointToPointState)
            and state.transmitter.depth == 0
            and state.receiver.depth == 0
            and self.link_session.is_quiescent(state.link)
        )

    def step(
        self,
        state: ChiDatPointToPointState,
        action: ChiDatPathAction,
    ) -> SemanticStep[ChiDatPointToPointState, ChiDatPathObservation]:
        if not isinstance(state, ChiDatPointToPointState):
            raise TypeError("DAT path requires ChiDatPointToPointState")
        invariant_fault = self._invariant_fault(state)
        if invariant_fault is not None:
            return SemanticStep(state, fault=invariant_fault)
        if isinstance(action, ChiDatEnqueue):
            return self._enqueue(state, action)
        if isinstance(action, ChiDatDrain):
            return self._drain(state, action)
        if isinstance(action, ChiDatPathTick):
            return self._tick(state, action)
        raise TypeError("unknown CHI DAT point-to-point action")

    def _enqueue(
        self,
        state: ChiDatPointToPointState,
        action: ChiDatEnqueue,
    ) -> SemanticStep[ChiDatPointToPointState, ChiDatPathObservation]:
        data_profile = self.link.profile.data
        assert data_profile is not None
        reasons = action.packet.explain_profile(
            data_profile.representation,
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
                    "chi.dat_tx_queue.slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=self.transmitter_capacity,
                    reason="DAT transmitter queue is full",
                    location=self.link.transmitter.qualified_name,
                ),
            )
        entry = ChiDatQueuedFlit(
            tx.next_serial,
            ChiProtocolFlit(action.packet),
        )
        candidate_tx = ChiDatTxQueueState(
            tx.pending + (entry,),
            tx.next_serial + 1,
            tx.sent_count,
        )
        return SemanticStep(
            ChiDatPointToPointState(
                state.next_tick,
                state.link,
                candidate_tx,
                state.receiver,
            )
        )

    def _drain(
        self,
        state: ChiDatPointToPointState,
        action: ChiDatDrain,
    ) -> SemanticStep[ChiDatPointToPointState, ChiDatPathObservation]:
        rx = state.receiver
        if action.count > rx.depth:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    "chi.dat_capture.flit",
                    ConstraintScope.VIRTUAL_DUT,
                    required=action.count,
                    available=rx.depth,
                    capacity=self.receiver_capacity,
                    reason=(
                        "DAT receiver has fewer captured flits than requested"
                    ),
                    location=self.link.receiver.qualified_name,
                ),
            )
        candidate_rx = ChiDatCaptureState(
            rx.captured[action.count :],
            rx.reserved_credits,
            rx.received_count,
            rx.returned_credit_count,
        )
        return SemanticStep(
            ChiDatPointToPointState(
                state.next_tick,
                state.link,
                state.transmitter,
                candidate_rx,
            )
        )

    def _tick(
        self,
        state: ChiDatPointToPointState,
        action: ChiDatPathTick,
    ) -> SemanticStep[ChiDatPointToPointState, ChiDatPathObservation]:
        assert state.link.data is not None
        previous_phase = state.link.activation.phase
        pending = state.transmitter.depth > 0
        wants_run = action.active or pending
        old_credit = state.link.data.usable_credits
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
        flit: ChiProtocolFlit | ChiDatLCrdReturn | None = None
        if phase in (
            ChiLinkActivationPhase.RUN,
            ChiLinkActivationPhase.DEACTIVATE,
        ):
            if queued is not None and old_credit > 0:
                flit = queued.flit
            elif phase is ChiLinkActivationPhase.DEACTIVATE and old_credit > 0:
                flit = ChiDatLCrdReturn()

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
        data_profile = self.link.profile.data
        assert data_profile is not None
        frame = AtomicFrame(
            state.next_tick,
            self.link.profile.clock,
            {
                self.link.profile.activation_observation:
                    ChiLinkActivationSignals(request, acknowledge),
                data_profile.observation: ChiDatChannelSignals(
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
            not isinstance(item, ChiDatTransfer)
            for item in link_transition.emissions
        ):
            return self._fault(
                state,
                "link_emission",
                "DAT-only link emitted an unexpected transfer set",
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

        candidate = ChiDatPointToPointState(
            state.next_tick + 1,
            link_transition.state,
            tx_transition.state,
            rx_transition.state,
        )
        invariant_fault = self._invariant_fault(candidate)
        if invariant_fault is not None:
            return SemanticStep(state, fault=invariant_fault)
        observation = ChiDatPathObservation(
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
        state: ChiDatCaptureState,
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
        state: ChiDatTxQueueState,
        transfer: ChiDatTransfer | None,
    ) -> SemanticStep[ChiDatTxQueueState, ChiDatQueuedFlit]:
        if transfer is None or (
            transfer.kind is ChiDatTransferKind.LINK_CREDIT_RETURN
        ):
            return SemanticStep(state)
        if not state.pending:
            return self._tx_fault(
                state,
                "empty_commit",
                "the link accepted a protocol flit from an empty DAT FIFO",
            )
        head = state.pending[0]
        if transfer.flit != head.flit:
            return self._tx_fault(
                state,
                "head_mismatch",
                "accepted transfer does not match the DAT FIFO head",
            )
        return SemanticStep(
            ChiDatTxQueueState(
                state.pending[1:],
                state.next_serial,
                state.sent_count + 1,
            ),
            (head,),
        )

    def _apply_rx_frame(
        self,
        state: ChiDatCaptureState,
        *,
        grant: bool,
        transfer: ChiDatTransfer | None,
    ) -> SemanticStep[ChiDatCaptureState, ChiDatTransfer]:
        captured = state.captured
        reserved = state.reserved_credits
        received = 0
        returned = 0
        if transfer is not None:
            if reserved == 0:
                return self._rx_fault(
                    state,
                    "unreserved_transfer",
                    "receiver observed a DAT transfer without an old reservation",
                )
            reserved -= 1
            if transfer.kind is ChiDatTransferKind.PROTOCOL:
                captured += (transfer,)
                received = 1
            else:
                returned = 1
        reserved += int(grant)
        candidate = ChiDatCaptureState(
            captured,
            reserved,
            state.received_count + received,
            state.returned_credit_count + returned,
        )
        if candidate.reserved_credits > self.credit_limit:
            return self._rx_fault(
                state,
                "credit_limit",
                "DAT receiver credit reservations exceed their limit",
            )
        if candidate.depth + candidate.reserved_credits > self.receiver_capacity:
            return self._rx_fault(
                state,
                "capacity",
                "DAT receiver slots are overcommitted",
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
        self, state: ChiDatPointToPointState
    ) -> SemanticFault | None:
        if state.link.data is None:
            return SemanticFault(
                f"{self.name}.data_state",
                "DAT-only path has no DAT link state",
                ConstraintScope.TRANSPORT,
                self.link.name,
            )
        if state.receiver.reserved_credits != state.link.data.usable_credits:
            return SemanticFault(
                f"{self.name}.credit_mirror",
                "receiver reservation disagrees with Transmitter-held credit",
                ConstraintScope.TRANSPORT,
                self.link.name,
            )
        if state.transmitter.depth > self.transmitter_capacity:
            return SemanticFault(
                f"{self.name}.tx_capacity",
                "DAT Transmitter FIFO exceeds its configured capacity",
                ConstraintScope.VIRTUAL_DUT,
                self.link.transmitter.qualified_name,
            )
        if (
            state.receiver.depth + state.receiver.reserved_credits
            > self.receiver_capacity
        ):
            return SemanticFault(
                f"{self.name}.rx_capacity",
                "DAT receiver capture and reservations exceed capacity",
                ConstraintScope.VIRTUAL_DUT,
                self.link.receiver.qualified_name,
            )
        return None

    def _tx_fault(
        self,
        state: ChiDatTxQueueState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiDatTxQueueState, ChiDatQueuedFlit]:
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
        state: ChiDatCaptureState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiDatCaptureState, ChiDatTransfer]:
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
        state: ChiDatPointToPointState,
        suffix: str,
        reason: str,
        scope: ConstraintScope,
    ) -> SemanticStep[ChiDatPointToPointState, ChiDatPathObservation]:
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
    "ChiDatCaptureState",
    "ChiDatDrain",
    "ChiDatEnqueue",
    "ChiDatPathAction",
    "ChiDatPathObservation",
    "ChiDatPathTick",
    "ChiDatPointToPointSession",
    "ChiDatPointToPointState",
    "ChiDatQueuedFlit",
    "ChiDatTxQueueState",
]
