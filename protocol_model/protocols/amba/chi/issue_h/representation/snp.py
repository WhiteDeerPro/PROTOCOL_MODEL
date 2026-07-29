"""Typed forms for the first executable CHI Issue H SNP-channel slice.

The SNP channel is intentionally different from REQ, RSP, and DAT: its
Network packet carries the issuing ``SrcID``, while the SNP protocol fields
have no ordinary ``TgtID``.  The interconnect chooses one or more Snoopees and
the Network-layer packet carries each per-copy destination.  Consequently the
protocol message below owns neither route endpoint.

``SnpShared``, the first clean ``SnpSharedFwd`` Direct Cache Transfer form,
``SnpNotSharedDirty``, ``SnpUnique``, and
``SnpCleanInvalid``/``SnpMakeInvalid`` are represented alongside the
hop-local ``SnpLCrdReturn`` form.  This module establishes the
channel/transport boundary; cache transitions, target selection, and response
matching are participant/system behavior, not fields silently inferred by
this local form.  A packed SNPFLIT codec remains outside the current slice.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar, TypeAlias

from .domain import ChiChannelKind, ChiChannelItemKind


class ChiSnpOpcode(IntEnum):
    """SNP opcodes implemented by the current representation slice."""

    LINK_CREDIT_RETURN = 0x00
    SNP_SHARED = 0x01
    SNP_NOT_SHARED_DIRTY = 0x04
    SNP_UNIQUE = 0x07
    SNP_CLEAN_INVALID = 0x09
    SNP_MAKE_INVALID = 0x0A
    SNP_SHARED_FWD = 0x11


def _require_uint(name: str, value: int, width: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < (1 << width)
    ):
        raise ValueError(f"{name} must be an unsigned {width}-bit integer")


def _require_bool(name: str, value: bool) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be bool")


@dataclass(frozen=True)
class _ChiCleanSnoopMessage:
    """Fields shared by the currently represented clean Snoop requests.

    The issuing and selected destination NodeIDs belong to the Network-layer
    carrier.  The destination can therefore differ for each replicated copy
    without modifying this shared protocol message.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.SNP
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int
    address: int
    qos: int = 0
    pas: int = 0
    do_not_go_to_shared_dirty: bool = False
    return_to_source: bool = False
    trace_tag: bool = False

    def __post_init__(self) -> None:
        _require_uint("transaction_id", self.transaction_id, 12)
        if (
            not isinstance(self.address, int)
            or isinstance(self.address, bool)
            or self.address < 0
        ):
            raise ValueError("address must be a non-negative integer")
        _require_uint("qos", self.qos, 4)
        _require_uint("pas", self.pas, 3)
        _require_bool(
            "do_not_go_to_shared_dirty",
            self.do_not_go_to_shared_dirty,
        )
        _require_bool("return_to_source", self.return_to_source)
        _require_bool("trace_tag", self.trace_tag)

    @property
    def semantic_key(self) -> int:
        """Return the transaction key within one issuing Home identity."""

        return self.transaction_id


@dataclass(frozen=True)
class ChiSnpSharedMessage(_ChiCleanSnoopMessage):
    """Request a clean cached copy to remain or become Shared."""

    @property
    def opcode(self) -> ChiSnpOpcode:
        return ChiSnpOpcode.SNP_SHARED


@dataclass(frozen=True)
class ChiSnpSharedFwdMessage(_ChiCleanSnoopMessage):
    """Forward a clean Shared copy directly to the original Requester.

    ``forward_node_id`` names the Requester that receives peer ``CompData``.
    ``forward_transaction_id`` is that Requester's original REQ TxnID and
    therefore becomes the TxnID of the forwarded ``CompData``.  In contrast,
    this message's own ``transaction_id`` is allocated by Home and correlates
    the response returned to Home and the Requester's later ``CompAck``.

    The current executable profile deliberately covers only the
    ``RetToSrc=0`` clean DCT flow.  The fields remain explicit here rather
    than being inferred from Network routing identities.
    """

    forward_node_id: int = 0
    forward_transaction_id: int = 0
    return_to_source: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_uint("forward_node_id", self.forward_node_id, 16)
        _require_uint(
            "forward_transaction_id",
            self.forward_transaction_id,
            12,
        )

    @property
    def opcode(self) -> ChiSnpOpcode:
        return ChiSnpOpcode.SNP_SHARED_FWD


@dataclass(frozen=True)
class ChiSnpNotSharedDirtyMessage(_ChiCleanSnoopMessage):
    """MESI snoop that prevents the target from remaining ``SD``."""

    do_not_go_to_shared_dirty: bool = True

    @property
    def opcode(self) -> ChiSnpOpcode:
        return ChiSnpOpcode.SNP_NOT_SHARED_DIRTY


@dataclass(frozen=True)
class ChiSnpUniqueMessage(_ChiCleanSnoopMessage):
    """Invalidate a cached copy and return Dirty data when required."""

    do_not_go_to_shared_dirty: bool = True

    @property
    def opcode(self) -> ChiSnpOpcode:
        return ChiSnpOpcode.SNP_UNIQUE


@dataclass(frozen=True)
class ChiSnpCleanInvalidMessage(_ChiCleanSnoopMessage):
    """Invalidate a peer and return Dirty data to Home when required."""

    do_not_go_to_shared_dirty: bool = True
    return_to_source: bool = False

    @property
    def opcode(self) -> ChiSnpOpcode:
        return ChiSnpOpcode.SNP_CLEAN_INVALID


@dataclass(frozen=True)
class ChiSnpMakeInvalidMessage(_ChiCleanSnoopMessage):
    """Invalidate a peer for a dataless ``MakeUnique`` request.

    The participant lifecycle responds with data-less ``SnpResp_I`` even
    when the invalidated copy was Dirty; that discard behavior is not an
    extra field on this SNP message.
    """

    do_not_go_to_shared_dirty: bool = True
    return_to_source: bool = False

    @property
    def opcode(self) -> ChiSnpOpcode:
        return ChiSnpOpcode.SNP_MAKE_INVALID


@dataclass(frozen=True)
class ChiSnpLCrdReturn:
    """SNP link flit returning one unused L-Credit to the receiver."""

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.SNP
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.LINK_MAINTENANCE_FLIT
    )

    @property
    def opcode(self) -> ChiSnpOpcode:
        return ChiSnpOpcode.LINK_CREDIT_RETURN

    @property
    def transaction_id(self) -> int:
        return 0


ChiSnpProtocolMessage: TypeAlias = (
    ChiSnpSharedMessage
    | ChiSnpSharedFwdMessage
    | ChiSnpNotSharedDirtyMessage
    | ChiSnpUniqueMessage
    | ChiSnpCleanInvalidMessage
    | ChiSnpMakeInvalidMessage
)
ChiSnpChannelItem: TypeAlias = ChiSnpProtocolMessage | ChiSnpLCrdReturn


@dataclass(frozen=True)
class ChiIssueHSnpProfile:
    """Variable widths used by the minimal Issue H SNP representation."""

    channel: ClassVar[ChiChannelKind] = ChiChannelKind.SNP

    node_id_width: int = 7
    snoop_address_width: int = 44

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_id_width, int)
            or isinstance(self.node_id_width, bool)
            or not 7 <= self.node_id_width <= 16
        ):
            raise ValueError("node_id_width must be in the Issue H range 7..16")
        if (
            not isinstance(self.snoop_address_width, int)
            or isinstance(self.snoop_address_width, bool)
            or not 44 <= self.snoop_address_width <= 52
        ):
            raise ValueError(
                "snoop_address_width must be in the Issue H range 44..52"
            )

    def explain(self, message: ChiSnpProtocolMessage) -> tuple[str, ...]:
        """Return local field/profile errors for the supported SNP form."""

        if not isinstance(
            message,
            (
                ChiSnpSharedMessage,
                ChiSnpSharedFwdMessage,
                ChiSnpNotSharedDirtyMessage,
                ChiSnpUniqueMessage,
                ChiSnpCleanInvalidMessage,
                ChiSnpMakeInvalidMessage,
            ),
        ):
            return ("expected a supported clean Snoop protocol message",)
        reasons: list[str] = []
        if message.address >= (1 << self.snoop_address_width):
            reasons.append(
                f"Addr {message.address:#x} exceeds "
                f"{self.snoop_address_width}-bit snoop address"
            )
        if message.address & 0b111:
            reasons.append(
                "Snoop address must be 8-byte aligned because SNP Addr "
                "does not carry address bits [2:0]"
            )
        if message.pas >= 6:
            reasons.append("PAS encodings 6 and 7 are reserved")
        if isinstance(message, ChiSnpSharedFwdMessage):
            if message.forward_node_id >= (1 << self.node_id_width):
                reasons.append(
                    f"FwdNID {message.forward_node_id:#x} exceeds "
                    f"{self.node_id_width}-bit NodeID"
                )
            if message.return_to_source:
                reasons.append(
                    "the current clean DCT profile requires "
                    "SnpSharedFwd RetToSrc=0"
                )
        if (
            isinstance(
                message,
                (
                    ChiSnpNotSharedDirtyMessage,
                    ChiSnpUniqueMessage,
                    ChiSnpCleanInvalidMessage,
                    ChiSnpMakeInvalidMessage,
                ),
            )
            and not message.do_not_go_to_shared_dirty
        ):
            reasons.append(
                "DoNotGoToSD must be one for "
                "SnpNotSharedDirty/SnpUnique/SnpCleanInvalid/"
                "SnpMakeInvalid"
            )
        if (
            isinstance(
                message,
                (
                    ChiSnpCleanInvalidMessage,
                    ChiSnpMakeInvalidMessage,
                ),
            )
            and message.return_to_source
        ):
            reasons.append(
                "RetToSrc must be zero for "
                "SnpCleanInvalid/SnpMakeInvalid"
            )
        return tuple(reasons)

    def contains(self, message: ChiSnpProtocolMessage) -> bool:
        return not self.explain(message)


__all__ = [
    "ChiIssueHSnpProfile",
    "ChiSnpChannelItem",
    "ChiSnpCleanInvalidMessage",
    "ChiSnpLCrdReturn",
    "ChiSnpMakeInvalidMessage",
    "ChiSnpNotSharedDirtyMessage",
    "ChiSnpOpcode",
    "ChiSnpProtocolMessage",
    "ChiSnpSharedFwdMessage",
    "ChiSnpSharedMessage",
    "ChiSnpUniqueMessage",
]
