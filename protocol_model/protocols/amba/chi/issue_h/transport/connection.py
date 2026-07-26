"""Executable endpoint runtime for one directed, multi-channel CHI link.

The CHI activation handshake belongs to a Link, while protocol traffic and
L-Credits belong to individual REQ, RSP, SNP, and DAT channels.
Consequently, a directed topology connection must not be implemented as
several independent point-to-point sessions: doing so would create several
activation authorities for one physical/logical Link.

This module keeps one :class:`ChiTransportLinkSession` as the atomic authority
and composes bounded transmitter queues and receiver captures around every
enabled channel.  Channel queues remain independent, so one frame can move a
flit on more than one enabled channel while activation advances exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

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
    ChiReqLCrdReturn,
    ChiRspLCrdReturn,
    ChiSnpLCrdReturn,
)
from .link import (
    ChiDatChannelSignals,
    ChiLinkActivationPhase,
    ChiLinkActivationSignals,
    ChiReqChannelSignals,
    ChiRspChannelSignals,
    ChiSnpChannelSignals,
    ChiTransportLink,
    ChiTransportTransfer,
)
from .session import ChiTransportLinkState


_CHANNEL_ORDER = (
    ChiChannelKind.REQ,
    ChiChannelKind.RSP,
    ChiChannelKind.SNP,
    ChiChannelKind.DAT,
)


def _require_positive(value: int, subject: str) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value <= 0
    ):
        raise ValueError(f"{subject} must be positive")
    return value


@dataclass(frozen=True)
class ChiConnectionEnqueue:
    """Offer one routable protocol packet to an enabled channel FIFO."""

    packet: ChiNetworkPacket
    resource_plane: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError("CHI connection enqueue requires ChiNetworkPacket")
        if (
            not isinstance(self.resource_plane, int)
            or isinstance(self.resource_plane, bool)
            or self.resource_plane < 0
        ):
            raise ValueError("CHI connection Resource Plane must be non-negative")
        if (
            self.packet.channel is not ChiChannelKind.REQ
            and self.resource_plane != 0
        ):
            raise ValueError("only REQ traffic uses a Resource Plane")


@dataclass(frozen=True)
class ChiConnectionDrain:
    """Commit consumption of captured packets on one channel."""

    channel: ChiChannelKind
    count: int = 1

    def __post_init__(self) -> None:
        try:
            channel = ChiChannelKind(self.channel)
        except (TypeError, ValueError) as error:
            raise ValueError("CHI connection drain requires a known channel") from error
        _require_positive(self.count, "CHI connection drain count")
        object.__setattr__(self, "channel", channel)


@dataclass(frozen=True)
class ChiConnectionTick:
    """Advance one shared activation/link frame."""

    active: bool = True

    def __post_init__(self) -> None:
        if type(self.active) is not bool:
            raise TypeError("CHI connection tick active must be bool")


ChiTransportConnectionAction = (
    ChiConnectionEnqueue | ChiConnectionDrain | ChiConnectionTick
)


@dataclass(frozen=True)
class ChiConnectionQueuedPacket:
    """One packet waiting in a channel-local transmitter FIFO."""

    serial: int
    packet: ChiNetworkPacket
    resource_plane: int = 0


@dataclass(frozen=True)
class ChiConnectionTxState:
    pending: tuple[ChiConnectionQueuedPacket, ...] = ()
    next_serial: int = 0
    sent_count: int = 0

    @property
    def depth(self) -> int:
        return len(self.pending)


@dataclass(frozen=True)
class ChiConnectionCapturedPacket:
    """One protocol packet owned by the receiving endpoint."""

    packet: ChiNetworkPacket
    transfer: ChiTransportTransfer
    resource_plane: int = 0


@dataclass(frozen=True)
class ChiConnectionRxState:
    captured: tuple[ChiConnectionCapturedPacket, ...]
    reserved_by_plane: tuple[int, ...]
    received_count: int = 0
    returned_credit_count: int = 0

    @property
    def depth(self) -> int:
        return len(self.captured)

    def depth_by_plane(self, plane: int) -> int:
        return sum(
            item.resource_plane == plane for item in self.captured
        )


@dataclass(frozen=True)
class ChiTransportConnectionState:
    """Atomic state of all enabled channels on one directed Link."""

    next_tick: int
    link: ChiTransportLinkState
    transmitters: Mapping[ChiChannelKind, ChiConnectionTxState]
    receivers: Mapping[ChiChannelKind, ChiConnectionRxState]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "transmitters",
            MappingProxyType(dict(self.transmitters)),
        )
        object.__setattr__(
            self,
            "receivers",
            MappingProxyType(dict(self.receivers)),
        )

    def _single_channel(self) -> ChiChannelKind:
        if len(self.transmitters) != 1:
            raise ValueError(
                "multi-channel CHI state requires an explicit channel"
            )
        return next(iter(self.transmitters))

    @property
    def transmitter(self) -> ChiConnectionTxState:
        """Convenient scalar view for a one-channel connection."""

        return self.transmitters[self._single_channel()]

    @property
    def receiver(self) -> ChiConnectionRxState:
        """Convenient scalar view for a one-channel connection."""

        return self.receivers[self._single_channel()]


@dataclass(frozen=True)
class ChiTransportConnectionObservation:
    """One shared frame and its per-channel accepted transfers."""

    frame: AtomicFrame
    phase: ChiLinkActivationPhase
    transfers: Mapping[ChiChannelKind, ChiTransportTransfer]
    grants_by_channel: Mapping[ChiChannelKind, tuple[bool, ...]]
    tx_depth_before: Mapping[ChiChannelKind, int]
    tx_depth_after: Mapping[ChiChannelKind, int]
    rx_depth_before: Mapping[ChiChannelKind, int]
    rx_depth_after: Mapping[ChiChannelKind, int]

    def __post_init__(self) -> None:
        for name in (
            "transfers",
            "grants_by_channel",
            "tx_depth_before",
            "tx_depth_after",
            "rx_depth_before",
            "rx_depth_after",
        ):
            object.__setattr__(
                self,
                name,
                MappingProxyType(dict(getattr(self, name))),
            )

    @property
    def tick(self) -> int:
        return self.frame.tick


class ChiTransportConnectionSession(
    SemanticComponent[
        ChiTransportConnectionAction,
        ChiTransportConnectionState,
        ChiTransportConnectionObservation,
    ]
):
    """Compose all enabled channel endpoints around one atomic Link session."""

    def __init__(
        self,
        link: ChiTransportLink,
        *,
        transmitter_capacity: int = 8,
        transmitter_capacity_by_channel: Mapping[
            ChiChannelKind, int
        ] | None = None,
    ) -> None:
        if not isinstance(link, ChiTransportLink):
            raise TypeError("CHI connection runtime requires ChiTransportLink")
        default_capacity = _require_positive(
            transmitter_capacity,
            "CHI transmitter capacity",
        )
        overrides = {
            ChiChannelKind(channel): _require_positive(
                capacity,
                "CHI channel transmitter capacity",
            )
            for channel, capacity in dict(
                transmitter_capacity_by_channel or {}
            ).items()
        }
        enabled = self._profile_channels(link)
        unknown = set(overrides) - enabled
        if unknown:
            raise ValueError(
                "CHI transmitter capacities reference disabled channels: "
                f"{sorted(item.value for item in unknown)!r}"
            )
        self.link = link
        self.name = f"{link.name}.chi_connection"
        self.link_session = link.open_session()
        self.channels = enabled
        self.transmitter_capacities = MappingProxyType(
            {
                channel: overrides.get(channel, default_capacity)
                for channel in enabled
            }
        )
        self.receiver_capacities = MappingProxyType(
            {
                channel: self._credit_limits(channel)
                for channel in enabled
            }
        )

    @staticmethod
    def _profile_channels(
        link: ChiTransportLink,
    ) -> frozenset[ChiChannelKind]:
        profile = link.profile
        return frozenset(
            channel
            for channel, configured in (
                (ChiChannelKind.REQ, profile.request),
                (ChiChannelKind.RSP, profile.response),
                (ChiChannelKind.SNP, profile.snoop),
                (ChiChannelKind.DAT, profile.data),
            )
            if configured is not None
        )

    @property
    def transmitter_capacity(self) -> int:
        """Return the common capacity, or fail when per-channel values differ."""

        values = frozenset(self.transmitter_capacities.values())
        if len(values) != 1:
            raise ValueError(
                "CHI connection has channel-specific transmitter capacities"
            )
        return next(iter(values))

    def initial_state(self) -> ChiTransportConnectionState:
        return ChiTransportConnectionState(
            0,
            self.link_session.initial_state(),
            {
                channel: ChiConnectionTxState()
                for channel in self.channels
            },
            {
                channel: ChiConnectionRxState(
                    (),
                    tuple(0 for _ in self._credit_limits(channel)),
                )
                for channel in self.channels
            },
        )

    def is_quiescent(self, state: ChiTransportConnectionState) -> bool:
        return (
            isinstance(state, ChiTransportConnectionState)
            and all(item.depth == 0 for item in state.transmitters.values())
            and all(item.depth == 0 for item in state.receivers.values())
            and self.link_session.is_quiescent(state.link)
        )

    def step(
        self,
        state: ChiTransportConnectionState,
        action: ChiTransportConnectionAction,
    ) -> SemanticStep[
        ChiTransportConnectionState,
        ChiTransportConnectionObservation,
    ]:
        fault = self._invariant_fault(state)
        if fault is not None:
            return SemanticStep(state, fault=fault)
        if isinstance(action, ChiConnectionEnqueue):
            return self._enqueue(state, action)
        if isinstance(action, ChiConnectionDrain):
            return self._drain(state, action)
        if isinstance(action, ChiConnectionTick):
            return self._tick(state, action)
        raise TypeError("unknown CHI transport connection action")

    def peek_capture(
        self,
        state: ChiTransportConnectionState,
        channel: ChiChannelKind,
    ) -> ChiConnectionCapturedPacket | None:
        self._require_state(state)
        channel = ChiChannelKind(channel)
        receiver = state.receivers.get(channel)
        if receiver is None:
            raise ValueError(
                f"CHI connection does not implement {channel.value.upper()}"
            )
        return None if not receiver.captured else receiver.captured[0]

    def live_packet_count(
        self,
        state: ChiTransportConnectionState,
        channel: ChiChannelKind,
    ) -> int:
        self._require_state(state)
        channel = ChiChannelKind(channel)
        if channel not in self.channels:
            return 0
        return (
            state.transmitters[channel].depth
            + state.receivers[channel].depth
        )

    def _enqueue(
        self,
        state: ChiTransportConnectionState,
        action: ChiConnectionEnqueue,
    ) -> SemanticStep[
        ChiTransportConnectionState,
        ChiTransportConnectionObservation,
    ]:
        channel = action.packet.channel
        if channel not in self.channels:
            return self._fault(
                state,
                "channel",
                f"connection does not implement {channel.value.upper()}",
                ConstraintScope.TRANSPORT,
            )
        limits = self._credit_limits(channel)
        if not 0 <= action.resource_plane < len(limits):
            return self._fault(
                state,
                "resource_plane",
                f"{channel.value.upper()} Resource Plane "
                f"{action.resource_plane} is out of range",
                ConstraintScope.EVENT,
            )
        profile = self._representation_profile(channel)
        reasons = action.packet.explain_profile(profile)
        if reasons:
            return self._fault(
                state,
                "representation",
                "; ".join(reasons),
                ConstraintScope.EVENT,
            )
        tx = state.transmitters[channel]
        capacity = self.transmitter_capacities[channel]
        if tx.depth >= capacity:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"chi.{channel.value}_tx_queue.slot",
                    ConstraintScope.VIRTUAL_DUT,
                    available=0,
                    capacity=capacity,
                    reason=(
                        f"{channel.value.upper()} transmitter queue is full"
                    ),
                    location=self.link.transmitter.qualified_name,
                ),
            )
        entry = ChiConnectionQueuedPacket(
            tx.next_serial,
            action.packet,
            action.resource_plane,
        )
        transmitters = dict(state.transmitters)
        transmitters[channel] = ChiConnectionTxState(
            tx.pending + (entry,),
            tx.next_serial + 1,
            tx.sent_count,
        )
        return SemanticStep(
            ChiTransportConnectionState(
                state.next_tick,
                state.link,
                transmitters,
                state.receivers,
            )
        )

    def _drain(
        self,
        state: ChiTransportConnectionState,
        action: ChiConnectionDrain,
    ) -> SemanticStep[
        ChiTransportConnectionState,
        ChiTransportConnectionObservation,
    ]:
        receiver = state.receivers.get(action.channel)
        if receiver is None:
            return self._fault(
                state,
                "channel",
                f"connection does not implement "
                f"{action.channel.value.upper()}",
                ConstraintScope.TRANSPORT,
            )
        if action.count > receiver.depth:
            return SemanticStep(
                state,
                blocked=ResourceDemand(
                    f"chi.{action.channel.value}_capture.packet",
                    ConstraintScope.VIRTUAL_DUT,
                    required=action.count,
                    available=receiver.depth,
                    capacity=sum(
                        self.receiver_capacities[action.channel]
                    ),
                    reason=(
                        f"{action.channel.value.upper()} receiver has fewer "
                        "captured packets than requested"
                    ),
                    location=self.link.receiver.qualified_name,
                ),
            )
        receivers = dict(state.receivers)
        receivers[action.channel] = ChiConnectionRxState(
            receiver.captured[action.count :],
            receiver.reserved_by_plane,
            receiver.received_count,
            receiver.returned_credit_count,
        )
        return SemanticStep(
            ChiTransportConnectionState(
                state.next_tick,
                state.link,
                state.transmitters,
                receivers,
            )
        )

    def _tick(
        self,
        state: ChiTransportConnectionState,
        action: ChiConnectionTick,
    ) -> SemanticStep[
        ChiTransportConnectionState,
        ChiTransportConnectionObservation,
    ]:
        previous = state.link.activation.phase
        has_pending = any(
            item.depth > 0 for item in state.transmitters.values()
        )
        has_credits = any(
            any(self._link_credits(state.link, channel))
            for channel in self.channels
        )
        phase = self._next_phase(
            previous,
            wants_run=action.active or has_pending,
            has_pending=has_pending,
            has_credits=has_credits,
        )

        selected: dict[
            ChiChannelKind,
            tuple[object | None, int],
        ] = {}
        grants: dict[ChiChannelKind, tuple[bool, ...]] = {}
        for channel in self._ordered_channels():
            credits = self._link_credits(state.link, channel)
            tx = state.transmitters[channel]
            head = None if not tx.pending else tx.pending[0]
            flit: object | None = None
            plane = 0
            if phase in (
                ChiLinkActivationPhase.RUN,
                ChiLinkActivationPhase.DEACTIVATE,
            ):
                if head is not None and credits[head.resource_plane] > 0:
                    flit = ChiProtocolFlit(head.packet)
                    plane = head.resource_plane
                elif phase is ChiLinkActivationPhase.DEACTIVATE:
                    for candidate_plane, count in enumerate(credits):
                        if count:
                            flit = self._credit_return(channel)
                            plane = candidate_plane
                            break
            selected[channel] = (flit, plane)
            receiving_plane = None
            if flit is not None:
                classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(flit)
                if classification.is_protocol_flit:
                    receiving_plane = plane
            grants[channel] = (
                self._grant_vector(
                    channel,
                    state.receivers[channel],
                    receiving_plane=receiving_plane,
                )
                if phase is ChiLinkActivationPhase.RUN
                else tuple(False for _ in credits)
            )

        request, acknowledge = {
            ChiLinkActivationPhase.STOP: (False, False),
            ChiLinkActivationPhase.ACTIVATE: (True, False),
            ChiLinkActivationPhase.RUN: (True, True),
            ChiLinkActivationPhase.DEACTIVATE: (False, True),
        }[phase]
        observations: dict[str, object] = {
            self.link.profile.activation_observation:
                ChiLinkActivationSignals(request, acknowledge)
        }
        if ChiChannelKind.REQ in self.channels:
            req_profile = self.link.profile.request
            assert req_profile is not None
            flit, plane = selected[ChiChannelKind.REQ]
            observations[req_profile.observation] = ChiReqChannelSignals(
                flit_valid=flit is not None,
                flit=flit,
                resource_plane=plane,
                lcrdv_by_plane=grants[ChiChannelKind.REQ],
            )
        if ChiChannelKind.RSP in self.channels:
            rsp_profile = self.link.profile.response
            assert rsp_profile is not None
            flit, _ = selected[ChiChannelKind.RSP]
            observations[rsp_profile.observation] = ChiRspChannelSignals(
                flit_valid=flit is not None,
                flit=flit,
                lcrdv=grants[ChiChannelKind.RSP][0],
            )
        if ChiChannelKind.DAT in self.channels:
            dat_profile = self.link.profile.data
            assert dat_profile is not None
            flit, _ = selected[ChiChannelKind.DAT]
            observations[dat_profile.observation] = ChiDatChannelSignals(
                flit_valid=flit is not None,
                flit=flit,
                lcrdv=grants[ChiChannelKind.DAT][0],
            )
        if ChiChannelKind.SNP in self.channels:
            snp_profile = self.link.profile.snoop
            assert snp_profile is not None
            flit, _ = selected[ChiChannelKind.SNP]
            observations[snp_profile.observation] = ChiSnpChannelSignals(
                flit_valid=flit is not None,
                flit=flit,
                lcrdv=grants[ChiChannelKind.SNP][0],
            )

        frame = AtomicFrame(
            state.next_tick,
            self.link.profile.clock,
            observations,
            source=self.name,
        )
        link_transition = self.link_session.step(state.link, frame)
        if link_transition.fault is not None:
            return SemanticStep(state, fault=link_transition.fault)

        transfers: dict[ChiChannelKind, ChiTransportTransfer] = {}
        for transfer in link_transition.emissions:
            classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(
                transfer.flit
            )
            channel = classification.channel
            if channel in transfers:
                return self._fault(
                    state,
                    "link_emission",
                    f"link emitted two {channel.value.upper()} flits in one "
                    "frame",
                    ConstraintScope.TRANSPORT,
                )
            transfers[channel] = transfer

        transmitters = dict(state.transmitters)
        receivers = dict(state.receivers)
        for channel in self._ordered_channels():
            transfer = transfers.get(channel)
            tx_step = self._apply_tx_transfer(
                channel,
                transmitters[channel],
                transfer,
            )
            if tx_step.fault is not None:
                return SemanticStep(state, fault=tx_step.fault)
            transmitters[channel] = tx_step.state
            rx_step = self._apply_rx_frame(
                channel,
                receivers[channel],
                grants[channel],
                transfer,
            )
            if rx_step.fault is not None:
                return SemanticStep(state, fault=rx_step.fault)
            receivers[channel] = rx_step.state

        candidate = ChiTransportConnectionState(
            state.next_tick + 1,
            link_transition.state,
            transmitters,
            receivers,
        )
        invariant_fault = self._invariant_fault(candidate)
        if invariant_fault is not None:
            return SemanticStep(state, fault=invariant_fault)
        observation = ChiTransportConnectionObservation(
            frame,
            phase,
            transfers,
            grants,
            {
                channel: state.transmitters[channel].depth
                for channel in self.channels
            },
            {
                channel: candidate.transmitters[channel].depth
                for channel in self.channels
            },
            {
                channel: state.receivers[channel].depth
                for channel in self.channels
            },
            {
                channel: candidate.receivers[channel].depth
                for channel in self.channels
            },
        )
        return SemanticStep(candidate, (observation,))

    def _apply_tx_transfer(
        self,
        channel: ChiChannelKind,
        state: ChiConnectionTxState,
        transfer: ChiTransportTransfer | None,
    ) -> SemanticStep[ChiConnectionTxState, ChiConnectionQueuedPacket]:
        if transfer is None:
            return SemanticStep(state)
        classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(transfer.flit)
        if classification.is_link_maintenance:
            return SemanticStep(state)
        if not state.pending:
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.{channel.value}.tx.empty_commit",
                    "link accepted a protocol flit from an empty channel FIFO",
                    ConstraintScope.VIRTUAL_DUT,
                    self.link.transmitter.qualified_name,
                ),
            )
        head = state.pending[0]
        plane = getattr(transfer, "resource_plane", 0)
        if (
            not isinstance(transfer.flit, ChiProtocolFlit)
            or transfer.flit.packet != head.packet
            or plane != head.resource_plane
        ):
            return SemanticStep(
                state,
                fault=SemanticFault(
                    f"{self.name}.{channel.value}.tx.head_mismatch",
                    "accepted transfer does not match the channel FIFO head",
                    ConstraintScope.VIRTUAL_DUT,
                    self.link.transmitter.qualified_name,
                ),
            )
        return SemanticStep(
            ChiConnectionTxState(
                state.pending[1:],
                state.next_serial,
                state.sent_count + 1,
            ),
            (head,),
        )

    def _apply_rx_frame(
        self,
        channel: ChiChannelKind,
        state: ChiConnectionRxState,
        grants: tuple[bool, ...],
        transfer: ChiTransportTransfer | None,
    ) -> SemanticStep[ChiConnectionRxState, ChiConnectionCapturedPacket]:
        reserved = list(state.reserved_by_plane)
        captured = list(state.captured)
        received = 0
        returned = 0
        if transfer is not None:
            plane = getattr(transfer, "resource_plane", 0)
            if not 0 <= plane < len(reserved):
                return self._rx_fault(
                    channel,
                    state,
                    "transfer_plane",
                    f"accepted transfer uses unknown plane {plane}",
                )
            if reserved[plane] == 0:
                return self._rx_fault(
                    channel,
                    state,
                    "unreserved_transfer",
                    "receiver observed a transfer without an old reservation",
                )
            reserved[plane] -= 1
            classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(
                transfer.flit
            )
            if classification.is_protocol_flit:
                if not isinstance(transfer.flit, ChiProtocolFlit):
                    return self._rx_fault(
                        channel,
                        state,
                        "protocol_carrier",
                        "protocol transfer does not carry a network packet",
                    )
                packet = transfer.flit.packet
                captured.append(
                    ChiConnectionCapturedPacket(packet, transfer, plane)
                )
                received += 1
            else:
                returned += 1
        for plane, grant in enumerate(grants):
            if grant:
                reserved[plane] += 1
        candidate = ChiConnectionRxState(
            tuple(captured),
            tuple(reserved),
            state.received_count + received,
            state.returned_credit_count + returned,
        )
        capacities = self.receiver_capacities[channel]
        limits = self._credit_limits(channel)
        for plane, (capacity, limit) in enumerate(
            zip(capacities, limits)
        ):
            if candidate.reserved_by_plane[plane] > limit:
                return self._rx_fault(
                    channel,
                    state,
                    "credit_limit",
                    "receiver reservations exceed the L-Credit limit",
                )
            if (
                candidate.depth_by_plane(plane)
                + candidate.reserved_by_plane[plane]
                > capacity
            ):
                return self._rx_fault(
                    channel,
                    state,
                    "capacity",
                    "receiver captures and reservations exceed capacity",
                )
        emissions = (
            ()
            if transfer is None
            or CHI_ISSUE_H_CHANNEL_DOMAIN.classify(
                transfer.flit
            ).is_link_maintenance
            else (candidate.captured[-1],)
        )
        return SemanticStep(candidate, emissions)

    def _grant_vector(
        self,
        channel: ChiChannelKind,
        state: ChiConnectionRxState,
        *,
        receiving_plane: int | None,
    ) -> tuple[bool, ...]:
        capacities = self.receiver_capacities[channel]
        limits = self._credit_limits(channel)
        if receiving_plane is not None and not (
            0 <= receiving_plane < len(capacities)
        ):
            raise ValueError("receiving Resource Plane is out of range")
        return tuple(
            state.reserved_by_plane[plane]
            - int(receiving_plane == plane)
            < limit
            and state.depth_by_plane(plane)
            + state.reserved_by_plane[plane]
            < capacity
            for plane, (capacity, limit) in enumerate(
                zip(capacities, limits)
            )
        )

    def _invariant_fault(
        self,
        state: ChiTransportConnectionState,
    ) -> SemanticFault | None:
        self._require_state(state)
        if (
            set(state.transmitters) != self.channels
            or set(state.receivers) != self.channels
        ):
            return SemanticFault(
                f"{self.name}.channel_state",
                "connection state does not cover exactly the enabled channels",
                ConstraintScope.TRANSPORT,
                self.link.name,
            )
        for channel in self.channels:
            tx = state.transmitters[channel]
            rx = state.receivers[channel]
            if tx.depth > self.transmitter_capacities[channel]:
                return SemanticFault(
                    f"{self.name}.{channel.value}.tx_capacity",
                    "channel transmitter FIFO exceeds its capacity",
                    ConstraintScope.VIRTUAL_DUT,
                    self.link.transmitter.qualified_name,
                )
            credits = self._link_credits(state.link, channel)
            if rx.reserved_by_plane != credits:
                return SemanticFault(
                    f"{self.name}.{channel.value}.credit_mirror",
                    "receiver reservations disagree with transmitter-held "
                    "L-Credits",
                    ConstraintScope.TRANSPORT,
                    self.link.name,
                )
            capacities = self.receiver_capacities[channel]
            if any(
                rx.depth_by_plane(plane) + rx.reserved_by_plane[plane]
                > capacity
                for plane, capacity in enumerate(capacities)
            ):
                return SemanticFault(
                    f"{self.name}.{channel.value}.rx_capacity",
                    "receiver captures and reservations exceed capacity",
                    ConstraintScope.VIRTUAL_DUT,
                    self.link.receiver.qualified_name,
                )
        return None

    def _require_state(self, state: ChiTransportConnectionState) -> None:
        if not isinstance(state, ChiTransportConnectionState):
            raise TypeError(
                "CHI connection requires ChiTransportConnectionState"
            )

    def _ordered_channels(self) -> tuple[ChiChannelKind, ...]:
        return tuple(
            channel for channel in _CHANNEL_ORDER if channel in self.channels
        )

    def _credit_limits(
        self,
        channel: ChiChannelKind,
    ) -> tuple[int, ...]:
        profile = self.link.profile
        if channel is ChiChannelKind.REQ:
            assert profile.request is not None
            return profile.request.credit_capacities
        if channel is ChiChannelKind.RSP:
            assert profile.response is not None
            return (profile.response.credit_capacity,)
        if channel is ChiChannelKind.DAT:
            assert profile.data is not None
            return (profile.data.credit_capacity,)
        if channel is ChiChannelKind.SNP:
            assert profile.snoop is not None
            return (profile.snoop.credit_capacity,)
        raise ValueError(
            f"{channel.value.upper()} endpoint runtime is not implemented"
        )

    def _representation_profile(self, channel: ChiChannelKind):
        profile = self.link.profile
        if channel is ChiChannelKind.REQ:
            assert profile.request is not None
            return profile.request.representation
        if channel is ChiChannelKind.RSP:
            assert profile.response is not None
            return profile.response.representation
        if channel is ChiChannelKind.DAT:
            assert profile.data is not None
            return profile.data.representation
        if channel is ChiChannelKind.SNP:
            assert profile.snoop is not None
            return profile.snoop.representation
        raise ValueError(
            f"{channel.value.upper()} representation is not implemented"
        )

    @staticmethod
    def _link_credits(
        state: ChiTransportLinkState,
        channel: ChiChannelKind,
    ) -> tuple[int, ...]:
        if channel is ChiChannelKind.REQ:
            assert state.request is not None
            return state.request.usable_credits_by_plane
        if channel is ChiChannelKind.RSP:
            assert state.response is not None
            return (state.response.usable_credits,)
        if channel is ChiChannelKind.DAT:
            assert state.data is not None
            return (state.data.usable_credits,)
        if channel is ChiChannelKind.SNP:
            assert state.snoop is not None
            return (state.snoop.usable_credits,)
        raise ValueError(
            f"{channel.value.upper()} link state is not implemented"
        )

    @staticmethod
    def _credit_return(channel: ChiChannelKind):
        if channel is ChiChannelKind.REQ:
            return ChiReqLCrdReturn()
        if channel is ChiChannelKind.RSP:
            return ChiRspLCrdReturn()
        if channel is ChiChannelKind.DAT:
            return ChiDatLCrdReturn()
        if channel is ChiChannelKind.SNP:
            return ChiSnpLCrdReturn()
        raise ValueError(
            f"{channel.value.upper()} L-Credit return is not implemented"
        )

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

    def _rx_fault(
        self,
        channel: ChiChannelKind,
        state: ChiConnectionRxState,
        suffix: str,
        reason: str,
    ) -> SemanticStep[ChiConnectionRxState, ChiConnectionCapturedPacket]:
        return SemanticStep(
            state,
            fault=SemanticFault(
                f"{self.name}.{channel.value}.rx.{suffix}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                self.link.receiver.qualified_name,
            ),
        )

    def _fault(
        self,
        state: ChiTransportConnectionState,
        suffix: str,
        reason: str,
        scope: ConstraintScope,
    ) -> SemanticStep[
        ChiTransportConnectionState,
        ChiTransportConnectionObservation,
    ]:
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
    "ChiConnectionCapturedPacket",
    "ChiConnectionDrain",
    "ChiConnectionEnqueue",
    "ChiConnectionQueuedPacket",
    "ChiConnectionRxState",
    "ChiConnectionTick",
    "ChiConnectionTxState",
    "ChiTransportConnectionAction",
    "ChiTransportConnectionObservation",
    "ChiTransportConnectionSession",
    "ChiTransportConnectionState",
]
