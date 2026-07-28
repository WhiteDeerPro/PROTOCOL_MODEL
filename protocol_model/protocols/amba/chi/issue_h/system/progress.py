"""Read-only progress evidence for the executable CHI coherence runtime.

The DTOs in this module project participant-private transaction reservations
and endpoint-head backpressure.  They do not add another owner of scheduler
state, infer a wait-for graph, or claim that a blocked state is a deadlock.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from protocol_model.semantics import ConstraintScope, ResourceDemand

from ..participants.coherence import (
    ChiCoherentTransactionPending,
    ChiHomeWriteBackPending,
)
from ..participants.progress import chi_line_resource_name
from ..representation.domain import ChiChannelKind
from ..representation.packet import ChiNetworkPacket
from ..representation.req import (
    ChiCleanUniqueMessage,
    ChiEvictMessage,
    ChiWriteBackFullMessage,
)
from .coherence import ChiDeliverCoherencePacket

if TYPE_CHECKING:
    from .coherence_network import (
        ChiCoherenceNetworkSession,
        ChiCoherenceNetworkState,
    )


def _require_node_id(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative NodeID")


def _require_transaction_id(value: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < (1 << 12)
    ):
        raise ValueError("CHI progress transaction_id must be 12-bit")


class ChiLineRelease(str, Enum):
    """Protocol event that releases one projected line reservation."""

    COMP = "Comp"
    COMP_ACK = "CompAck"
    COMP_DATA = "CompData"
    COMP_DBID_RESP = "CompDBIDResp"
    COPY_BACK_WR_DATA = "CopyBackWrData"


@dataclass(frozen=True)
class ChiCoherenceTxnRef:
    """End-to-end coherent transaction identity used by progress evidence."""

    home_node_id: int
    requester_node_id: int
    transaction_id: int

    def __post_init__(self) -> None:
        _require_node_id("CHI progress Home", self.home_node_id)
        _require_node_id(
            "CHI progress requester", self.requester_node_id
        )
        _require_transaction_id(self.transaction_id)


@dataclass(frozen=True)
class ChiEndpointHeadRef:
    """Identity of one packet retained at a transport endpoint head."""

    connection: str
    channel: ChiChannelKind
    packet: ChiNetworkPacket

    def __post_init__(self) -> None:
        if not isinstance(self.connection, str) or not self.connection:
            raise ValueError(
                "CHI endpoint-head reference requires a connection"
            )
        channel = ChiChannelKind(self.channel)
        if not isinstance(self.packet, ChiNetworkPacket):
            raise TypeError(
                "CHI endpoint-head reference requires a network packet"
            )
        if self.packet.channel is not channel:
            raise ValueError(
                "CHI endpoint-head channel must match its packet"
            )
        object.__setattr__(self, "channel", channel)


@dataclass(frozen=True)
class ChiHeldLine:
    """One participant-local line reservation derived from pending state.

    ``release_transaction_id`` is the wire correlation carried by the event
    named in ``release_on``: a Home DBID for CompAck/CopyBackWrData and the
    original requester TxnID for RN completion acceptance.
    """

    resource: str
    scope: ConstraintScope
    holder_node_id: int
    address: int
    transaction: ChiCoherenceTxnRef
    release_on: ChiLineRelease
    release_transaction_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.resource, str) or not self.resource:
            raise ValueError("held CHI line requires a resource name")
        if not isinstance(self.scope, ConstraintScope):
            raise TypeError("held CHI line requires a constraint scope")
        _require_node_id("held CHI line owner", self.holder_node_id)
        if (
            not isinstance(self.address, int)
            or isinstance(self.address, bool)
            or self.address < 0
            or self.address % 64
        ):
            raise ValueError(
                "held CHI line address must be 64-byte aligned"
            )
        if not isinstance(self.transaction, ChiCoherenceTxnRef):
            raise TypeError(
                "held CHI line requires a coherent transaction reference"
            )
        object.__setattr__(
            self, "release_on", ChiLineRelease(self.release_on)
        )
        _require_transaction_id(self.release_transaction_id)


@dataclass(frozen=True)
class ChiLineWait:
    """One endpoint-head transaction waiting for a held line resource."""

    waiter: ChiCoherenceTxnRef
    endpoint: ChiEndpointHeadRef
    demand: ResourceDemand

    def __post_init__(self) -> None:
        if not isinstance(self.waiter, ChiCoherenceTxnRef):
            raise TypeError(
                "CHI line wait requires a coherent transaction reference"
            )
        if not isinstance(self.endpoint, ChiEndpointHeadRef):
            raise TypeError(
                "CHI line wait requires an endpoint-head reference"
            )
        if not isinstance(self.demand, ResourceDemand):
            raise TypeError("CHI line wait requires a resource demand")


@dataclass(frozen=True)
class ChiLineWakeup:
    """Evidence that a prior endpoint wait lost its exact line holder."""

    waiter: ChiCoherenceTxnRef
    endpoint: ChiEndpointHeadRef
    resource: str
    released_holder: ChiHeldLine

    def __post_init__(self) -> None:
        if not isinstance(self.waiter, ChiCoherenceTxnRef):
            raise TypeError(
                "CHI line wakeup requires a coherent transaction reference"
            )
        if not isinstance(self.endpoint, ChiEndpointHeadRef):
            raise TypeError(
                "CHI line wakeup requires an endpoint-head reference"
            )
        if not isinstance(self.resource, str) or not self.resource:
            raise ValueError("CHI line wakeup requires a resource")
        if not isinstance(self.released_holder, ChiHeldLine):
            raise TypeError(
                "CHI line wakeup requires its released line holder"
            )
        if self.resource != self.released_holder.resource:
            raise ValueError(
                "CHI line wakeup resource must match its released holder"
            )


@dataclass(frozen=True)
class ChiCoherenceProgress:
    """Current family-local held/waiting evidence."""

    held: tuple[ChiHeldLine, ...] = ()
    waiting: tuple[ChiLineWait, ...] = ()

    def __post_init__(self) -> None:
        held = tuple(self.held)
        waiting = tuple(self.waiting)
        if any(not isinstance(item, ChiHeldLine) for item in held):
            raise TypeError("CHI progress held entries must be line holders")
        if any(not isinstance(item, ChiLineWait) for item in waiting):
            raise TypeError("CHI progress waiting entries must be line waits")
        object.__setattr__(self, "held", held)
        object.__setattr__(self, "waiting", waiting)


def _transaction_ref(
    session: "ChiCoherenceNetworkSession",
    state: "ChiCoherenceNetworkState",
    packet: ChiNetworkPacket,
) -> ChiCoherenceTxnRef | None:
    message = packet.message
    transaction_id = getattr(message, "transaction_id", None)
    if not isinstance(transaction_id, int):
        return None

    if packet.target_id == session.coherence.home.node_id:
        return ChiCoherenceTxnRef(
            session.coherence.home.node_id,
            packet.source_id,
            transaction_id,
        )

    for pending in state.coherence.home.pending.values():
        if (
            pending.snoop_transaction_id == transaction_id
            and packet.target_id in pending.snoop_targets
        ):
            return ChiCoherenceTxnRef(
                session.coherence.home.node_id,
                pending.requester_id,
                pending.request.transaction_id,
            )
    return None


def _target_line_resource(
    session: "ChiCoherenceNetworkSession",
    packet: ChiNetworkPacket,
) -> str | None:
    """Return a packet target's line key without executing a participant."""

    address = getattr(packet.message, "address", None)
    if (
        not isinstance(address, int)
        or isinstance(address, bool)
        or address < 0
        or address % 64
    ):
        return None
    if packet.target_id == session.coherence.home.node_id:
        participant = session.coherence.home
    else:
        participant = session.coherence.request_nodes.get(packet.target_id)
    if participant is None:
        return None
    return chi_line_resource_name(participant.name, address)


def _held_lines(
    session: "ChiCoherenceNetworkSession",
    state: "ChiCoherenceNetworkState",
) -> tuple[ChiHeldLine, ...]:
    home = session.coherence.home
    held: list[ChiHeldLine] = []
    for pending in state.coherence.home.pending.values():
        assert isinstance(pending, ChiCoherentTransactionPending)
        held.append(
            ChiHeldLine(
                chi_line_resource_name(
                    home.name, pending.request.address
                ),
                ConstraintScope.SYSTEM,
                home.node_id,
                pending.request.address,
                ChiCoherenceTxnRef(
                    home.node_id,
                    pending.requester_id,
                    pending.request.transaction_id,
                ),
                ChiLineRelease.COMP_ACK,
                pending.data_buffer_id,
            )
        )
    for pending in state.coherence.home.pending_writebacks.values():
        assert isinstance(pending, ChiHomeWriteBackPending)
        held.append(
            ChiHeldLine(
                chi_line_resource_name(
                    home.name, pending.request.address
                ),
                ConstraintScope.SYSTEM,
                home.node_id,
                pending.request.address,
                ChiCoherenceTxnRef(
                    home.node_id,
                    pending.requester_id,
                    pending.request.transaction_id,
                ),
                ChiLineRelease.COPY_BACK_WR_DATA,
                pending.data_buffer_id,
            )
        )

    for node_id, node_state in state.coherence.request_nodes.items():
        node = session.coherence.request_nodes[node_id]
        for request in node_state.pending_transactions.values():
            held.append(
                ChiHeldLine(
                    chi_line_resource_name(node.name, request.address),
                    ConstraintScope.VIRTUAL_DUT,
                    node_id,
                    request.address,
                    ChiCoherenceTxnRef(
                        home.node_id, node_id, request.transaction_id
                    ),
                    (
                        ChiLineRelease.COMP
                        if isinstance(
                            request,
                            (ChiCleanUniqueMessage, ChiEvictMessage),
                        )
                        else ChiLineRelease.COMP_DATA
                    ),
                    request.transaction_id,
                )
            )
        for pending in node_state.pending_writebacks.values():
            request = pending.request
            assert isinstance(request, ChiWriteBackFullMessage)
            held.append(
                ChiHeldLine(
                    chi_line_resource_name(node.name, request.address),
                    ConstraintScope.VIRTUAL_DUT,
                    node_id,
                    request.address,
                    ChiCoherenceTxnRef(
                        home.node_id, node_id, request.transaction_id
                    ),
                    ChiLineRelease.COMP_DBID_RESP,
                    request.transaction_id,
                )
            )
    return tuple(
        sorted(
            held,
            key=lambda item: (
                item.resource,
                item.holder_node_id,
                item.transaction.transaction_id,
            ),
        )
    )


def _project_chi_coherence_progress(
    session: "ChiCoherenceNetworkSession",
    state: "ChiCoherenceNetworkState",
) -> ChiCoherenceProgress:
    """Project held lines and currently blocked endpoint heads."""

    held = _held_lines(session, state)
    held_resources = {item.resource for item in held}
    waiting: list[ChiLineWait] = []
    for connection, channel in sorted(
        session.endpoint_targets,
        key=lambda item: (item[0], item[1].value),
    ):
        delivery = session.network.peek_delivery(
            state.network, connection, channel
        )
        if delivery is None:
            continue
        binding = session.binding_by_node_id.get(
            delivery.packet.target_id
        )
        route = session.route_by_packet_key.get(
            (
                delivery.packet.source_id,
                delivery.packet.target_id,
                channel,
            )
        )
        if (
            binding is None
            or delivery.packet.target_id
            not in session.endpoint_targets[(connection, channel)]
            or route is None
            or route[-1] != connection
        ):
            continue
        target_resource = _target_line_resource(
            session, delivery.packet
        )
        if target_resource not in held_resources:
            continue
        participant = session.coherence.step(
            state.coherence,
            ChiDeliverCoherencePacket(delivery.packet),
        )
        demand = participant.blocked
        if demand is None or demand.resource != target_resource:
            continue
        waiter = _transaction_ref(session, state, delivery.packet)
        if waiter is None:
            continue
        waiting.append(
            ChiLineWait(
                waiter,
                ChiEndpointHeadRef(
                    connection, channel, delivery.packet
                ),
                demand,
            )
        )
    return ChiCoherenceProgress(held, tuple(waiting))


def _project_chi_line_wakeups(
    before: ChiCoherenceProgress,
    after: ChiCoherenceProgress,
) -> tuple[ChiLineWakeup, ...]:
    """Return waits whose exact projected holder was released.

    This is release evidence only.  It does not claim that the waiting packet
    has already been accepted or that no unrelated blocker can remain.
    """

    if not isinstance(before, ChiCoherenceProgress) or not isinstance(
        after, ChiCoherenceProgress
    ):
        raise TypeError("CHI wakeup projection requires progress snapshots")
    after_waits = {
        (item.waiter, item.endpoint, item.demand.resource)
        for item in after.waiting
    }
    after_holders = set(after.held)
    wakeups: list[ChiLineWakeup] = []
    for wait in before.waiting:
        key = (wait.waiter, wait.endpoint, wait.demand.resource)
        if key in after_waits:
            continue
        released = next(
            (
                holder
                for holder in before.held
                if holder.resource == wait.demand.resource
                and holder not in after_holders
            ),
            None,
        )
        if released is not None:
            wakeups.append(
                ChiLineWakeup(
                    wait.waiter,
                    wait.endpoint,
                    wait.demand.resource,
                    released,
                )
            )
    return tuple(wakeups)


__all__ = [
    "ChiCoherenceProgress",
    "ChiCoherenceTxnRef",
    "ChiEndpointHeadRef",
    "ChiHeldLine",
    "ChiLineRelease",
    "ChiLineWait",
    "ChiLineWakeup",
]
