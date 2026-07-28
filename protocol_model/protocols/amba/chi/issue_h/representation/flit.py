"""Transport-layer envelopes for CHI channel traffic.

Protocol traffic crosses one hop as a flit that contains a network packet.
Link-maintenance flits, such as L-Credit return, remain direct hop-local forms
and therefore never acquire a :class:`ChiNetworkPacket`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from .domain import ChiChannelKind, ChiChannelItemKind
from .packet import ChiNetworkPacket


@dataclass(frozen=True)
class ChiProtocolFlit:
    """One single-hop transport envelope carrying a network packet."""

    packet: ChiNetworkPacket

    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_FLIT
    )

    def __post_init__(self) -> None:
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError("CHI protocol flit requires a ChiNetworkPacket")

    @property
    def chi_channel(self) -> ChiChannelKind:
        return self.packet.channel

    @property
    def opcode(self) -> object:
        """Expose the opcode only for channel-domain/profile dispatch."""

        return self.packet.message.opcode


__all__ = [
    "ChiProtocolFlit",
]
