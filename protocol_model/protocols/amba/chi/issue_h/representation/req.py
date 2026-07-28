"""Typed forms for the first executable CHI Issue H REQ-channel slice.

This module deliberately represents fields by meaning rather than packing a
REQFLIT bit vector.  ``ReadNoSnp``, ``ReadShared``,
``ReadNotSharedDirty``, ``ReadUnique``, ``CleanUnique``, ``Evict``,
``WriteBackFull``, and ``PCrdReturn`` are the currently implemented
protocol messages;
``LCrdReturn`` is the REQ-channel link-maintenance flit.  Routing NodeIDs are
added by the Network packet.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar, TypeAlias

from .domain import ChiChannelKind, ChiChannelItemKind


class ChiReqOpcode(IntEnum):
    """REQ opcodes implemented by the current representation slice."""

    LINK_CREDIT_RETURN = 0x00
    READ_SHARED = 0x01
    READ_NO_SNP = 0x04
    PROTOCOL_CREDIT_RETURN = 0x05
    READ_UNIQUE = 0x07
    CLEAN_UNIQUE = 0x0B
    EVICT = 0x0D
    WRITE_BACK_FULL = 0x1B
    READ_NOT_SHARED_DIRTY = 0x26


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
class ChiReadNoSnpMessage:
    """Semantic fields of one supported ``ReadNoSnp`` REQ message.

    The request-address width is checked by :class:`ChiIssueHReqProfile`;
    routing NodeID width is checked on the containing packet.  Constant-width
    fields are checked while the value is constructed.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.REQ
    chi_item_kind: ClassVar[ChiChannelItemKind] = ChiChannelItemKind.PROTOCOL_MESSAGE

    transaction_id: int
    address: int
    size: int = 6
    qos: int = 0
    pas: int = 0
    likely_shared: bool = False
    allow_retry: bool = True
    order: int = 0
    protocol_credit_type: int = 0
    memory_attributes: int = 0
    snoop_attribute: bool = False
    exclusive: bool = False
    expect_completion_ack: bool = False
    tag_operation: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        for name, value, width in (
            ("transaction_id", self.transaction_id, 12),
            ("size", self.size, 3),
            ("qos", self.qos, 4),
            ("pas", self.pas, 3),
            ("order", self.order, 2),
            ("protocol_credit_type", self.protocol_credit_type, 4),
            ("memory_attributes", self.memory_attributes, 4),
            ("tag_operation", self.tag_operation, 2),
        ):
            _require_uint(name, value, width)
        if self.size == 7:
            raise ValueError("ReadNoSnp size encoding 7 is reserved")
        for name, value in (
            ("likely_shared", self.likely_shared),
            ("allow_retry", self.allow_retry),
            ("snoop_attribute", self.snoop_attribute),
            ("exclusive", self.exclusive),
            ("expect_completion_ack", self.expect_completion_ack),
            ("trace_tag", self.trace_tag),
        ):
            _require_bool(name, value)
        for name, value in (("address", self.address),):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    @property
    def opcode(self) -> ChiReqOpcode:
        return ChiReqOpcode.READ_NO_SNP

    @property
    def semantic_key(self) -> int:
        """Return the transaction key within one Requester identity."""

        return self.transaction_id


@dataclass(frozen=True)
class _ChiCoherentRequestMessage:
    """Fields shared by the currently represented coherent requests.

    Node identities remain on the containing Network packet.  Defaults select
    the ordinary RN-F shape used by the clean coherence reference profile; a
    wider participant profile can still choose other legal field values.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.REQ
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int
    address: int
    size: int = 6
    qos: int = 0
    pas: int = 0
    likely_shared: bool = False
    allow_retry: bool = True
    order: int = 0
    protocol_credit_type: int = 0
    memory_attributes: int = 0b0101
    snoop_attribute: bool = True
    exclusive: bool = False
    expect_completion_ack: bool = True
    tag_operation: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        for name, value, width in (
            ("transaction_id", self.transaction_id, 12),
            ("size", self.size, 3),
            ("qos", self.qos, 4),
            ("pas", self.pas, 3),
            ("order", self.order, 2),
            ("protocol_credit_type", self.protocol_credit_type, 4),
            ("memory_attributes", self.memory_attributes, 4),
            ("tag_operation", self.tag_operation, 2),
        ):
            _require_uint(name, value, width)
        if self.size == 7:
            raise ValueError("coherent request size encoding 7 is reserved")
        for name, value in (
            ("likely_shared", self.likely_shared),
            ("allow_retry", self.allow_retry),
            ("snoop_attribute", self.snoop_attribute),
            ("exclusive", self.exclusive),
            ("expect_completion_ack", self.expect_completion_ack),
            ("trace_tag", self.trace_tag),
        ):
            _require_bool(name, value)
        if (
            not isinstance(self.address, int)
            or isinstance(self.address, bool)
            or self.address < 0
        ):
            raise ValueError("address must be a non-negative integer")

    @property
    def semantic_key(self) -> int:
        return self.transaction_id


@dataclass(frozen=True)
class ChiReadSharedMessage(_ChiCoherentRequestMessage):
    """Semantic fields of one coherent ``ReadShared`` request."""

    @property
    def opcode(self) -> ChiReqOpcode:
        return ChiReqOpcode.READ_SHARED


@dataclass(frozen=True)
class ChiReadNotSharedDirtyMessage(_ChiCoherentRequestMessage):
    """Coherent read for a MESI requester that cannot install ``SD``."""

    @property
    def opcode(self) -> ChiReqOpcode:
        return ChiReqOpcode.READ_NOT_SHARED_DIRTY


@dataclass(frozen=True)
class ChiReadUniqueMessage(_ChiCoherentRequestMessage):
    """Semantic fields of one coherent ``ReadUnique`` request."""

    @property
    def opcode(self) -> ChiReqOpcode:
        return ChiReqOpcode.READ_UNIQUE


@dataclass(frozen=True)
class ChiCleanUniqueMessage(_ChiCoherentRequestMessage):
    """Dataless request to upgrade an existing line to Unique permission.

    The first executable profile uses the ordinary non-Exclusive, full-line
    form.  Cache-state eligibility and the later local store are participant
    lifecycle concerns rather than fields of this REQ message.
    """

    @property
    def opcode(self) -> ChiReqOpcode:
        return ChiReqOpcode.CLEAN_UNIQUE


@dataclass(frozen=True)
class ChiEvictMessage(_ChiCoherentRequestMessage):
    """Dataless request to remove one clean resident line from coherence.

    The ordinary initial form is a full-line, non-Exclusive Normal-memory
    request with ``SnpAttr=1``, ``LikelyShared=0``, ``AllowRetry=1``,
    ``PCrdType=0``, and ``ExpCompAck=0``.  Holder eligibility and directory
    removal are lifecycle contracts above this representation.
    """

    expect_completion_ack: bool = False

    @property
    def opcode(self) -> ChiReqOpcode:
        return ChiReqOpcode.EVICT


@dataclass(frozen=True)
class ChiWriteBackFullMessage:
    """One full-line CopyBack request from a coherent Request Node.

    The message starts a ``WriteBackFull`` transaction; it does not carry the
    cache-line data.  The Home later returns ``CompDBIDResp`` and the
    Requester uses that DBID in ``CopyBackWrData``.  Routing NodeIDs remain on
    the containing Network packet.

    Defaults select the ordinary first-attempt, 64-byte Normal-memory form.
    Retry correlation and the requirement that the Requester currently holds
    a Dirty line are transaction-lifecycle checks above this representation.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.REQ
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int
    address: int
    size: int = 6
    qos: int = 0
    pas: int = 0
    likely_shared: bool = False
    allow_retry: bool = True
    order: int = 0
    protocol_credit_type: int = 0
    memory_attributes: int = 0b0101
    snoop_attribute: bool = True
    exclusive: bool = False
    expect_completion_ack: bool = False
    tag_operation: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        for name, value, width in (
            ("transaction_id", self.transaction_id, 12),
            ("size", self.size, 3),
            ("qos", self.qos, 4),
            ("pas", self.pas, 3),
            ("order", self.order, 2),
            ("protocol_credit_type", self.protocol_credit_type, 4),
            ("memory_attributes", self.memory_attributes, 4),
            ("tag_operation", self.tag_operation, 2),
        ):
            _require_uint(name, value, width)
        for name, value in (
            ("likely_shared", self.likely_shared),
            ("allow_retry", self.allow_retry),
            ("snoop_attribute", self.snoop_attribute),
            ("exclusive", self.exclusive),
            ("expect_completion_ack", self.expect_completion_ack),
            ("trace_tag", self.trace_tag),
        ):
            _require_bool(name, value)
        if (
            not isinstance(self.address, int)
            or isinstance(self.address, bool)
            or self.address < 0
        ):
            raise ValueError("address must be a non-negative integer")

    @property
    def opcode(self) -> ChiReqOpcode:
        return ChiReqOpcode.WRITE_BACK_FULL

    @property
    def semantic_key(self) -> int:
        """Return the original Requester-owned transaction identifier."""

        return self.transaction_id


@dataclass(frozen=True)
class ChiPCrdReturnMessage:
    """Return one unused protocol credit to the named Home Node.

    ``PCrdReturn`` is ordinary routable REQ protocol traffic.  It is distinct
    from :class:`ChiReqLCrdReturn`, which terminates at one transport hop.
    Issue H fixes the transaction identifier of this opcode to zero.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.REQ
    chi_item_kind: ClassVar[ChiChannelItemKind] = ChiChannelItemKind.PROTOCOL_MESSAGE

    protocol_credit_type: int

    def __post_init__(self) -> None:
        _require_uint(
            "protocol_credit_type",
            self.protocol_credit_type,
            4,
        )

    @property
    def opcode(self) -> ChiReqOpcode:
        return ChiReqOpcode.PROTOCOL_CREDIT_RETURN

    @property
    def transaction_id(self) -> int:
        return 0


@dataclass(frozen=True)
class ChiReqLCrdReturn:
    """REQ link flit returning one unused L-Credit to the receiver."""

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.REQ
    chi_item_kind: ClassVar[ChiChannelItemKind] = ChiChannelItemKind.LINK_MAINTENANCE_FLIT

    @property
    def opcode(self) -> ChiReqOpcode:
        return ChiReqOpcode.LINK_CREDIT_RETURN

    @property
    def transaction_id(self) -> int:
        return 0


ChiReqProtocolMessage: TypeAlias = (
    ChiReadNoSnpMessage
    | ChiReadSharedMessage
    | ChiReadNotSharedDirtyMessage
    | ChiReadUniqueMessage
    | ChiCleanUniqueMessage
    | ChiEvictMessage
    | ChiWriteBackFullMessage
    | ChiPCrdReturnMessage
)
ChiReqChannelItem: TypeAlias = ChiReqProtocolMessage | ChiReqLCrdReturn


@dataclass(frozen=True)
class ChiIssueHReqProfile:
    """Variable field widths used by the minimal Issue H REQ representation."""

    channel: ClassVar[ChiChannelKind] = ChiChannelKind.REQ

    node_id_width: int = 7
    request_address_width: int = 44

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_id_width, int)
            or isinstance(self.node_id_width, bool)
            or not 7 <= self.node_id_width <= 16
        ):
            raise ValueError("node_id_width must be in the Issue H range 7..16")
        if (
            not isinstance(self.request_address_width, int)
            or isinstance(self.request_address_width, bool)
            or not 44 <= self.request_address_width <= 52
        ):
            raise ValueError(
                "request_address_width must be in the Issue H range 44..52"
            )

    def explain(self, message: ChiReqProtocolMessage) -> tuple[str, ...]:
        """Return representation errors decidable for this minimal profile."""

        if not isinstance(
            message,
            (
                ChiReadNoSnpMessage,
                ChiReadSharedMessage,
                ChiReadNotSharedDirtyMessage,
                ChiReadUniqueMessage,
                ChiCleanUniqueMessage,
                ChiEvictMessage,
                ChiWriteBackFullMessage,
                ChiPCrdReturnMessage,
            ),
        ):
            return ("expected a supported REQ protocol message",)
        reasons: list[str] = []
        if isinstance(
            message,
            (
                ChiReadNoSnpMessage,
                ChiReadSharedMessage,
                ChiReadNotSharedDirtyMessage,
                ChiReadUniqueMessage,
                ChiCleanUniqueMessage,
                ChiEvictMessage,
                ChiWriteBackFullMessage,
            ),
        ):
            if message.address >= (1 << self.request_address_width):
                reasons.append(
                    f"Addr {message.address:#x} exceeds "
                    f"{self.request_address_width}-bit request address"
                )
            if isinstance(message, ChiReadNoSnpMessage):
                if message.likely_shared:
                    reasons.append("LikelyShared must be zero for ReadNoSnp")
                if message.snoop_attribute:
                    reasons.append("SnpAttr must be zero for ReadNoSnp")
            elif isinstance(message, ChiEvictMessage):
                if message.size != 6:
                    reasons.append("Evict requires Size=6 (64 bytes)")
                if not message.snoop_attribute:
                    reasons.append("Evict requires SnpAttr=1")
                if message.memory_attributes != 0b0101:
                    reasons.append("Evict requires MemAttr 0101")
                if message.order != 0:
                    reasons.append("Evict requires Order=0")
                if message.exclusive:
                    reasons.append("Evict requires Excl=0")
                if message.likely_shared:
                    reasons.append("Evict requires LikelyShared=0")
                if message.expect_completion_ack:
                    reasons.append("Evict requires ExpCompAck=0")
                if message.tag_operation != 0:
                    reasons.append("Evict requires TagOp=0")
            elif isinstance(message, ChiWriteBackFullMessage):
                if message.size != 6:
                    reasons.append(
                        "WriteBackFull requires Size=6 (64 bytes)"
                    )
                if not message.snoop_attribute:
                    reasons.append(
                        "WriteBackFull requires SnpAttr=1"
                    )
                if message.memory_attributes not in (0b0101, 0b1101):
                    reasons.append(
                        "WriteBackFull requires MemAttr 0101 or 1101"
                    )
                if message.order != 0:
                    reasons.append("WriteBackFull requires Order=0")
                if message.exclusive:
                    reasons.append("WriteBackFull requires Excl=0")
                if message.expect_completion_ack:
                    reasons.append(
                        "WriteBackFull requires ExpCompAck=0"
                    )
            else:
                if message.size != 6:
                    reasons.append(
                        "coherent request profile requires Size=6 (64 bytes)"
                    )
                if not message.snoop_attribute:
                    reasons.append(
                        "coherent request profile requires SnpAttr=1"
                    )
                if message.memory_attributes not in (0b0101, 0b1101):
                    reasons.append(
                        "coherent request profile requires "
                        "MemAttr 0101 or 1101"
                    )
                if message.order != 0:
                    reasons.append(
                        "coherent request profile requires Order=0"
                    )
                if not message.expect_completion_ack:
                    reasons.append(
                        "coherent request profile requires ExpCompAck=1"
                    )
                if isinstance(message, ChiReadUniqueMessage):
                    if message.exclusive:
                        reasons.append("ReadUnique requires Excl=0")
                    if message.likely_shared:
                        reasons.append(
                            "ReadUnique requires LikelyShared=0"
                        )
                if isinstance(message, ChiCleanUniqueMessage):
                    if message.exclusive:
                        reasons.append("CleanUnique requires Excl=0")
                    if message.likely_shared:
                        reasons.append(
                            "CleanUnique requires LikelyShared=0"
                        )
            if message.pas >= 6:
                reasons.append("PAS encodings 6 and 7 are reserved")
            if message.allow_retry and message.protocol_credit_type:
                reasons.append("PCrdType must be zero when AllowRetry is set")
        else:
            if message.transaction_id != 0:
                reasons.append("TxnID must be zero for PCrdReturn")
            if not 0 <= message.protocol_credit_type < (1 << 4):
                reasons.append("PCrdType exceeds its 4-bit field")
        return tuple(reasons)

    def contains(self, message: ChiReqProtocolMessage) -> bool:
        return not self.explain(message)


__all__ = [
    "ChiCleanUniqueMessage",
    "ChiEvictMessage",
    "ChiIssueHReqProfile",
    "ChiPCrdReturnMessage",
    "ChiReadNoSnpMessage",
    "ChiReadNotSharedDirtyMessage",
    "ChiReadSharedMessage",
    "ChiReadUniqueMessage",
    "ChiWriteBackFullMessage",
    "ChiReqChannelItem",
    "ChiReqLCrdReturn",
    "ChiReqOpcode",
    "ChiReqProtocolMessage",
]
