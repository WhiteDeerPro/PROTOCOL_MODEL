"""Network-facing runtime for one resolved CHI transport connection.

The network executor asks only for enqueue, tick, capture, drain, and live
packet counts.  Queue shapes and credit accounting stay in the family-owned
multi-channel connection session.
"""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.semantics import SemanticStep

from ..representation import ChiChannelKind, ChiNetworkPacket
from .connection import (
    ChiConnectionDrain,
    ChiConnectionEnqueue,
    ChiConnectionTick,
    ChiTransportConnectionSession,
    ChiTransportConnectionState,
)
from .link import ChiTransportLink, ChiTransportTransfer


@dataclass(frozen=True)
class ChiPathCapture:
    """The oldest protocol packet captured on one connection channel."""

    packet: ChiNetworkPacket
    transfer: ChiTransportTransfer
    resource_plane: int = 0


@dataclass(frozen=True)
class ChiTransportConnectionRuntime:
    """Uniform operations consumed by topology-independent CHI execution."""

    session: ChiTransportConnectionSession

    @property
    def channels(self) -> frozenset[ChiChannelKind]:
        return self.session.channels

    @property
    def channel(self) -> ChiChannelKind:
        """Return the only channel on a single-channel connection."""

        if len(self.channels) != 1:
            raise ValueError(
                "multi-channel CHI connection requires an explicit channel"
            )
        return next(iter(self.channels))

    @property
    def link(self) -> ChiTransportLink:
        return self.session.link

    @property
    def state_type(self) -> type[ChiTransportConnectionState]:
        return ChiTransportConnectionState

    @property
    def transmitter_capacity(self) -> int:
        return self.session.transmitter_capacity

    def transmitter_capacity_for(
        self, channel: ChiChannelKind
    ) -> int:
        selected = ChiChannelKind(channel)
        try:
            return self.session.transmitter_capacities[selected]
        except KeyError as error:
            raise ValueError(
                f"CHI connection does not carry "
                f"{selected.value.upper()}"
            ) from error

    def initial_state(self) -> ChiTransportConnectionState:
        return self.session.initial_state()

    def is_quiescent(self, state: ChiTransportConnectionState) -> bool:
        return self.session.is_quiescent(state)

    def accepts(self, packet: ChiNetworkPacket) -> bool:
        return (
            isinstance(packet, ChiNetworkPacket)
            and packet.channel in self.channels
        )

    def enqueue(
        self,
        state: ChiTransportConnectionState,
        packet: ChiNetworkPacket,
        *,
        resource_plane: int = 0,
    ) -> SemanticStep:
        if not self.accepts(packet):
            raise ValueError(
                f"CHI connection cannot enqueue "
                f"{packet.channel.value.upper()} traffic"
            )
        return self.session.step(
            state,
            ChiConnectionEnqueue(packet, resource_plane),
        )

    def tick(
        self,
        state: ChiTransportConnectionState,
        *,
        active: bool,
    ) -> SemanticStep:
        return self.session.step(state, ChiConnectionTick(active))

    def drain(
        self,
        state: ChiTransportConnectionState,
        *,
        channel: ChiChannelKind | None = None,
        count: int = 1,
    ) -> SemanticStep:
        selected = self._select_channel(state, channel, captured=True)
        return self.session.step(
            state,
            ChiConnectionDrain(selected, count),
        )

    def peek_capture(
        self,
        state: ChiTransportConnectionState,
        channel: ChiChannelKind | None = None,
    ) -> ChiPathCapture | None:
        selected = self._select_channel(
            state,
            channel,
            captured=True,
            allow_empty=True,
        )
        if selected is None:
            return None
        captured = self.session.peek_capture(state, selected)
        if captured is None:
            return None
        return ChiPathCapture(
            captured.packet,
            captured.transfer,
            captured.resource_plane,
        )

    def live_packet_count(
        self,
        state: ChiTransportConnectionState,
        channel: ChiChannelKind | None = None,
    ) -> int:
        if channel is not None:
            return self.session.live_packet_count(
                state, ChiChannelKind(channel)
            )
        return sum(
            self.session.live_packet_count(state, item)
            for item in self.channels
        )

    def live_packet_counts(
        self,
        state: ChiTransportConnectionState,
    ) -> dict[ChiChannelKind, int]:
        return {
            channel: self.session.live_packet_count(state, channel)
            for channel in self.channels
        }

    def _select_channel(
        self,
        state: ChiTransportConnectionState,
        channel: ChiChannelKind | None,
        *,
        captured: bool,
        allow_empty: bool = False,
    ) -> ChiChannelKind | None:
        if channel is not None:
            selected = ChiChannelKind(channel)
            if selected not in self.channels:
                raise ValueError(
                    f"CHI connection does not carry "
                    f"{selected.value.upper()}"
                )
            return selected
        if len(self.channels) == 1:
            return next(iter(self.channels))
        if captured:
            non_empty = tuple(
                item
                for item in sorted(
                    self.channels, key=lambda value: value.value
                )
                if state.receivers[item].depth
            )
            if len(non_empty) == 1:
                return non_empty[0]
            if not non_empty and allow_empty:
                return None
            if not non_empty:
                raise ValueError(
                    "multi-channel CHI connection has no captured packet"
                )
            raise ValueError(
                "multi-channel CHI connection has several captured channels; "
                "select one explicitly"
            )
        raise ValueError(
            "multi-channel CHI connection requires an explicit channel"
        )


def open_transport_connection_runtime(
    link: ChiTransportLink,
    *,
    transmitter_capacity: int = 1,
) -> ChiTransportConnectionRuntime:
    """Open all enabled channels behind one activation authority."""

    if not isinstance(link, ChiTransportLink):
        raise TypeError("CHI connection runtime requires ChiTransportLink")
    return ChiTransportConnectionRuntime(
        ChiTransportConnectionSession(
            link,
            transmitter_capacity=transmitter_capacity,
        )
    )


ChiPathState = ChiTransportConnectionState


__all__ = [
    "ChiPathCapture",
    "ChiPathState",
    "ChiTransportConnectionRuntime",
    "open_transport_connection_runtime",
]
