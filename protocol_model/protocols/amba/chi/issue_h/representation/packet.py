"""Network-layer carrier for CHI protocol messages.

A protocol message describes the operation being performed.  A network packet
adds the identity needed to route one copy of that message through a CHI
interconnect.  Keeping those facts separate matters for SNP traffic: one snoop
message can be replicated into packets with different destination NodeIDs.

Packetization is explicit even though the current executable slice does not
fragment message contents.  ``packet_index`` and ``packet_count`` reserve the
boundary needed by a later data splitter without pretending that the splitter
or a packed CHI codec already exists.  Snoop fanout is a different operation:
it creates independently routed target copies whose fragment index/count each
remain ``0/1``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiChannelKind,
    ChiChannelProfile,
    ChiProtocolMessage,
)


def _require_non_negative(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


@dataclass(frozen=True)
class ChiNetworkPacket:
    """One routable copy of a typed CHI protocol message.

    ``source_id`` and ``target_id`` are network routing identities.  They do
    not come from the message, so a router never needs to inspect an opcode or
    assume that every channel has the same protocol-field shape.
    """

    channel: ChiChannelKind
    message: ChiProtocolMessage
    source_id: int
    target_id: int
    packet_index: int = 0
    packet_count: int = 1

    def __post_init__(self) -> None:
        try:
            channel = ChiChannelKind(self.channel)
        except (TypeError, ValueError) as error:
            raise ValueError("CHI packet requires a known channel") from error

        classification = CHI_ISSUE_H_CHANNEL_DOMAIN.classify(self.message)
        if not classification.is_message:
            subject = (
                "hop-local link-maintenance flit"
                if classification.is_link_maintenance
                else "already packet-bearing protocol flit"
            )
            raise TypeError(
                f"CHI network packet cannot carry {subject}"
            )
        if classification.channel is not channel:
            raise ValueError(
                f"{classification.channel.name} protocol message cannot be "
                f"carried by a {channel.name} packet"
            )
        for route_field in ("source_id", "target_id"):
            if hasattr(self.message, route_field):
                raise TypeError(
                    f"CHI protocol message must not own Network route field "
                    f"{route_field}"
                )

        _require_non_negative("source_id", self.source_id)
        _require_non_negative("target_id", self.target_id)
        _require_non_negative("packet_index", self.packet_index)
        if (
            not isinstance(self.packet_count, int)
            or isinstance(self.packet_count, bool)
            or self.packet_count <= 0
        ):
            raise ValueError("packet_count must be a positive integer")
        if self.packet_index >= self.packet_count:
            raise ValueError("packet_index must be smaller than packet_count")

        object.__setattr__(self, "channel", channel)

    @classmethod
    def request(
        cls,
        message: ChiProtocolMessage,
        *,
        source_id: int,
        target_id: int,
        packet_index: int = 0,
        packet_count: int = 1,
    ) -> "ChiNetworkPacket":
        return cls(
            ChiChannelKind.REQ,
            message,
            source_id,
            target_id,
            packet_index,
            packet_count,
        )

    @classmethod
    def response(
        cls,
        message: ChiProtocolMessage,
        *,
        source_id: int,
        target_id: int,
        packet_index: int = 0,
        packet_count: int = 1,
    ) -> "ChiNetworkPacket":
        return cls(
            ChiChannelKind.RSP,
            message,
            source_id,
            target_id,
            packet_index,
            packet_count,
        )

    @classmethod
    def snoop(
        cls,
        message: ChiProtocolMessage,
        *,
        source_id: int,
        target_id: int,
        packet_index: int = 0,
        packet_count: int = 1,
    ) -> "ChiNetworkPacket":
        return cls(
            ChiChannelKind.SNP,
            message,
            source_id,
            target_id,
            packet_index,
            packet_count,
        )

    @classmethod
    def data(
        cls,
        message: ChiProtocolMessage,
        *,
        source_id: int,
        target_id: int,
        packet_index: int = 0,
        packet_count: int = 1,
    ) -> "ChiNetworkPacket":
        return cls(
            ChiChannelKind.DAT,
            message,
            source_id,
            target_id,
            packet_index,
            packet_count,
        )

    def explain_profile(
        self,
        profile: ChiChannelProfile | None = None,
    ) -> tuple[str, ...]:
        """Return message and packet-identity representation errors."""

        selected = profile or CHI_ISSUE_H_CHANNEL_DOMAIN.default_profile(
            self.channel
        )
        reasons = list(
            CHI_ISSUE_H_CHANNEL_DOMAIN.explain_profile(
                self.message,
                selected,
            )
        )
        node_id_width = getattr(selected, "node_id_width", None)
        if isinstance(node_id_width, int) and not isinstance(
            node_id_width, bool
        ):
            node_limit = 1 << node_id_width
            if self.target_id >= node_limit:
                reasons.append(
                    f"TgtID {self.target_id} exceeds "
                    f"{node_id_width}-bit NodeID"
                )
            if self.source_id >= node_limit:
                reasons.append(
                    f"SrcID {self.source_id} exceeds "
                    f"{node_id_width}-bit NodeID"
                )
        return tuple(reasons)


__all__ = [
    "ChiNetworkPacket",
]
