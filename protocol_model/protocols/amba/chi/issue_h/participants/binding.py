"""Bind one CHI protocol participant to a concrete VirtualDut boundary.

The binding is deliberately wider than a normal ``InterfaceAttachment``.
A CHI participant can own several NodeIDs and use several unidirectional
transport ports, while a port can carry more than one protocol channel.  The
family-specific runtime interprets channel purpose; the generic VirtualDut
boundary only needs to expose compatible ``TransportPort`` objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from protocol_model.semantics import SemanticComponent
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)

from ..representation import ChiChannelKind
from ..transport import CHI_ISSUE_H_TRANSPORT_FAMILY


@dataclass(frozen=True)
class ChiParticipantPortBinding:
    """Channel purposes assigned to one concrete CHI transport port."""

    port: TransportPort
    channels: frozenset[ChiChannelKind]

    def __post_init__(self) -> None:
        if not isinstance(self.port, TransportPort):
            raise TypeError("CHI participant port binding requires TransportPort")
        if self.port.transport_family != CHI_ISSUE_H_TRANSPORT_FAMILY:
            raise ValueError(
                "CHI participant port belongs to another transport family"
            )
        try:
            channels = frozenset(ChiChannelKind(item) for item in self.channels)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "CHI participant port binding contains an unknown channel"
            ) from error
        if not channels:
            raise ValueError(
                "CHI participant port binding requires at least one channel"
            )
        object.__setattr__(self, "channels", channels)


@dataclass(frozen=True)
class ChiParticipantBinding:
    """Local association of participant behavior with one VirtualDut.

    ``node_ids`` is the identity offered by the participant, not a global
    allocation authority.  A later SystemProtocol identity contract can
    assign or validate those values without mutating this frozen local
    declaration.
    """

    name: str
    dut: VirtualDut
    component: SemanticComponent = field(repr=False, compare=False)
    ports: tuple[ChiParticipantPortBinding, ...] = ()
    node_ids: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("CHI participant binding requires a name")
        if not isinstance(self.dut, VirtualDut):
            raise TypeError("CHI participant binding requires VirtualDut")
        if not isinstance(self.component, SemanticComponent):
            raise TypeError(
                "CHI participant binding requires a SemanticComponent"
            )
        ports = tuple(self.ports)
        if not ports:
            raise ValueError("CHI participant binding requires transport ports")
        if any(not isinstance(item, ChiParticipantPortBinding) for item in ports):
            raise TypeError(
                "CHI participant binding ports require ChiParticipantPortBinding"
            )
        names = tuple(item.port.name for item in ports)
        if len(set(names)) != len(names):
            raise ValueError("CHI participant binds one transport port twice")
        for item in ports:
            try:
                declared = self.dut.port(item.port.name)
            except KeyError as error:
                raise ValueError(
                    f"CHI participant port {item.port.name!r} is not declared "
                    f"by VirtualDut {self.dut.name!r}"
                ) from error
            if not isinstance(declared, TransportPort) or declared != item.port:
                raise ValueError(
                    f"CHI participant port {self.dut.name}.{item.port.name} "
                    "does not match the VirtualDut boundary"
                )
        try:
            node_ids = frozenset(self.node_ids)
        except TypeError as error:
            raise TypeError("CHI participant NodeIDs must be iterable") from error
        if any(
            not isinstance(item, int) or isinstance(item, bool) or item < 0
            for item in node_ids
        ):
            raise ValueError("CHI participant NodeIDs must be non-negative integers")
        object.__setattr__(self, "ports", ports)
        object.__setattr__(self, "node_ids", node_ids)

    def ports_for(
        self,
        channel: ChiChannelKind,
        direction: TransportDirection,
    ) -> tuple[TransportPort, ...]:
        """Return boundary ports carrying one channel in one direction."""

        channel = ChiChannelKind(channel)
        direction = TransportDirection(direction)
        return tuple(
            item.port
            for item in self.ports
            if item.port.direction is direction and channel in item.channels
        )

    def require_one_port(
        self,
        channel: ChiChannelKind,
        direction: TransportDirection,
    ) -> TransportPort:
        """Resolve a single-port profile without constraining general CHI."""

        matches = self.ports_for(channel, direction)
        if len(matches) != 1:
            raise ValueError(
                f"CHI participant {self.name!r} requires exactly one "
                f"{direction.value} {channel.value.upper()} port for this "
                f"profile, found {len(matches)}"
            )
        return matches[0]


__all__ = ["ChiParticipantBinding", "ChiParticipantPortBinding"]
