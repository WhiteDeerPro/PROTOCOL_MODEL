"""Typed forms for the first executable CHI Issue H DAT-channel slice.

The classes in this module carry fields by protocol meaning.  They are not a
bit codec for ``DATFLIT`` and do not try to materialize every physical field
that is inapplicable to the supported ``CompData``, ``SnpRespData``, and
``CopyBackWrData`` forms.  Packet-to-packet consistency and
transaction-lifecycle rules remain contracts above this local representation
profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar, TypeAlias

from .domain import ChiChannelKind, ChiChannelItemKind
from .response import ChiRespCode, ChiRespErr


class ChiDatOpcode(IntEnum):
    """DAT opcodes implemented by the current representation slice."""

    LINK_CREDIT_RETURN = 0x0
    SNP_RESP_DATA = 0x1
    COPY_BACK_WRITE_DATA = 0x2
    COMP_DATA = 0x4


def _require_uint(name: str, value: int, width: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value < (1 << width)
    ):
        raise ValueError(f"{name} must be an unsigned {width}-bit integer")


def _require_non_negative(name: str, value: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_bool(name: str, value: bool) -> None:
    if type(value) is not bool:
        raise TypeError(f"{name} must be bool")


@dataclass(frozen=True)
class ChiCopyBackWrDataMessage:
    """Data returned after a Completer grants a CopyBack DBID.

    ``transaction_id`` carries the DBID received in ``CompDBIDResp``, not the
    original REQ TxnID.  Data-bearing ``response`` values describe the
    Requester's cache state and whether dirty responsibility is passed.
    ``I`` is the canceled CopyBack indication, whose cache-state information
    is imprecise and ignored.  The current participant lifecycles accept
    full-line ``UD_PD`` for live dirty WriteBack, full-line ``UC`` for
    the data outcome of ``WriteEvictFull(CAH=0/1)``, or full-line
    ``UC``/``SC`` for the data outcome of
    ``WriteEvictOrEvict(CAH=0)``.  Their supported pre-response
    invalidating-Snoop cancellation paths use ``I`` with zero data and byte
    enables.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.DAT
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int
    data: int
    response: ChiRespCode | int = ChiRespCode.UD_PD
    data_id: int = 0
    qos: int = 0
    response_error: ChiRespErr | int = ChiRespErr.OK
    data_source: int = 0
    completer_busy: int = 0
    byte_enable: int = (1 << 64) - 1
    critical_chunk_id: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        for name, value, width in (
            ("transaction_id", self.transaction_id, 12),
            ("response", self.response, 3),
            ("data_id", self.data_id, 2),
            ("qos", self.qos, 4),
            ("response_error", self.response_error, 2),
            ("data_source", self.data_source, 8),
            ("completer_busy", self.completer_busy, 3),
            ("byte_enable", self.byte_enable, 64),
            ("critical_chunk_id", self.critical_chunk_id, 2),
        ):
            _require_uint(name, value, width)
        _require_non_negative("data", self.data)
        _require_bool("trace_tag", self.trace_tag)
        object.__setattr__(
            self,
            "response_error",
            ChiRespErr(self.response_error),
        )

        try:
            response = ChiRespCode(self.response)
        except ValueError as error:
            raise ValueError(
                "CopyBackWrData contains a reserved Resp encoding"
            ) from error
        if int(response) not in (
            int(ChiRespCode.I),
            int(ChiRespCode.SC),
            int(ChiRespCode.UC),
            int(ChiRespCode.UD_PD),
            int(ChiRespCode.SD_PD),
        ):
            raise ValueError(
                "CopyBackWrData Resp must be I, SC, UC, UD_PD, or SD_PD"
            )
        if response is ChiRespCode.I and (
            self.byte_enable != 0 or self.data != 0
        ):
            raise ValueError(
                "CopyBackWrData_I requires zero byte enables and zero data"
            )
        object.__setattr__(self, "response", response)

    @property
    def opcode(self) -> ChiDatOpcode:
        return ChiDatOpcode.COPY_BACK_WRITE_DATA

    @property
    def semantic_key(self) -> int:
        """Return the Completer-owned DBID carried in the DAT TxnID."""

        return self.transaction_id

    @property
    def passes_dirty(self) -> bool:
        """Whether the Requester passes memory-update responsibility."""

        return bool(int(self.response) & 0b100)


@dataclass(frozen=True)
class ChiCompDataMessage:
    """Semantic fields of one supported ``CompData`` protocol message.

    HomeNID and data width depend on the configured representation profile;
    source and destination route identities are checked on the containing
    packet.  This type does not claim all conditional DATFLIT fields or packed
    bit positions.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.DAT
    chi_item_kind: ClassVar[ChiChannelItemKind] = ChiChannelItemKind.PROTOCOL_MESSAGE

    transaction_id: int
    data: int
    data_id: int = 0
    home_node_id: int = 0
    qos: int = 0
    response_error: ChiRespErr | int = ChiRespErr.OK
    response: int = 0
    data_source: int = 0
    completer_busy: int = 0
    data_buffer_id: int = 0
    critical_chunk_id: int = 0
    trace_tag: bool = False
    copy_at_home: bool = False

    def __post_init__(self) -> None:
        for name, value, width in (
            ("transaction_id", self.transaction_id, 12),
            ("data_id", self.data_id, 2),
            ("qos", self.qos, 4),
            ("response_error", self.response_error, 2),
            ("response", self.response, 3),
            ("data_source", self.data_source, 8),
            ("completer_busy", self.completer_busy, 3),
            ("data_buffer_id", self.data_buffer_id, 12),
            ("critical_chunk_id", self.critical_chunk_id, 2),
        ):
            _require_uint(name, value, width)
        for name, value in (
            ("home_node_id", self.home_node_id),
            ("data", self.data),
        ):
            _require_non_negative(name, value)
        _require_bool("trace_tag", self.trace_tag)
        _require_bool("copy_at_home", self.copy_at_home)
        object.__setattr__(
            self,
            "response_error",
            ChiRespErr(self.response_error),
        )

    @property
    def opcode(self) -> ChiDatOpcode:
        return ChiDatOpcode.COMP_DATA

    @property
    def semantic_key(self) -> int:
        """Return the transaction key within one Requester identity."""

        return self.transaction_id

    @property
    def passes_dirty(self) -> bool:
        """Whether this completion transfers memory-update responsibility."""

        return bool(int(self.response) & 0b100)


@dataclass(frozen=True)
class ChiSnpRespDataMessage:
    """One full-line ``SnpRespData`` response from a coherent Request Node.

    Route ``SrcID``/``TgtID`` remain on :class:`ChiNetworkPacket`.  The
    current executable profile models a complete 64-byte line and keeps
    partial-data, DataPull, byte-enable, poison, and forwarding variants as
    separate future forms.

    ``Resp`` carries two independent facts in one protocol encoding: the
    Snoopee's final stable state and whether dirty responsibility is passed.
    Keeping that encoding distinct from ``data`` matters because receiving
    bytes alone does not transfer responsibility for updating memory.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.DAT
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int
    data: int
    response: int
    data_id: int = 0
    qos: int = 0
    response_error: ChiRespErr | int = ChiRespErr.OK
    data_source: int = 0
    completer_busy: int = 0
    data_buffer_id: int = 0
    critical_chunk_id: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        for name, value, width in (
            ("transaction_id", self.transaction_id, 12),
            ("response", self.response, 3),
            ("data_id", self.data_id, 2),
            ("qos", self.qos, 4),
            ("response_error", self.response_error, 2),
            ("data_source", self.data_source, 8),
            ("completer_busy", self.completer_busy, 3),
            ("data_buffer_id", self.data_buffer_id, 12),
            ("critical_chunk_id", self.critical_chunk_id, 2),
        ):
            _require_uint(name, value, width)
        _require_non_negative("data", self.data)
        _require_bool("trace_tag", self.trace_tag)
        object.__setattr__(
            self,
            "response_error",
            ChiRespErr(self.response_error),
        )

        try:
            response = ChiRespCode(self.response)
        except ValueError as error:
            raise ValueError(
                "SnpRespData contains a reserved Resp encoding"
            ) from error
        if response is ChiRespCode.SD_PD:
            raise ValueError(
                "Resp=0b111 is reserved for non-forward SnpRespData"
            )
        object.__setattr__(self, "response", response)

    @property
    def opcode(self) -> ChiDatOpcode:
        return ChiDatOpcode.SNP_RESP_DATA

    @property
    def semantic_key(self) -> int:
        """Return the Home-issued Snoop TxnID."""

        return self.transaction_id

    @property
    def passes_dirty(self) -> bool:
        """Whether the response passes responsibility for stale memory."""

        return bool(int(self.response) & 0b100)


@dataclass(frozen=True)
class ChiDatLCrdReturn:
    """DAT link flit returning one unused L-Credit to the receiver."""

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.DAT
    chi_item_kind: ClassVar[ChiChannelItemKind] = ChiChannelItemKind.LINK_MAINTENANCE_FLIT

    @property
    def opcode(self) -> ChiDatOpcode:
        return ChiDatOpcode.LINK_CREDIT_RETURN

    @property
    def transaction_id(self) -> int:
        return 0


ChiDatProtocolMessage: TypeAlias = (
    ChiCompDataMessage
    | ChiCopyBackWrDataMessage
    | ChiSnpRespDataMessage
)
ChiDatChannelItem: TypeAlias = ChiDatProtocolMessage | ChiDatLCrdReturn


@dataclass(frozen=True)
class ChiIssueHDatProfile:
    """Variable widths used by the minimal Issue H DAT representation."""

    channel: ClassVar[ChiChannelKind] = ChiChannelKind.DAT

    node_id_width: int = 7
    data_width: int = 128

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_id_width, int)
            or isinstance(self.node_id_width, bool)
            or not 7 <= self.node_id_width <= 16
        ):
            raise ValueError("node_id_width must be in the Issue H range 7..16")
        if self.data_width not in (128, 256, 512):
            raise ValueError("data_width must be 128, 256, or 512 bits")

    @property
    def valid_data_ids(self) -> tuple[int, ...]:
        """Return legal packet positions for this DAT data-bus width."""

        return {
            128: (0b00, 0b01, 0b10, 0b11),
            256: (0b00, 0b10),
            512: (0b00,),
        }[self.data_width]

    def explain(self, message: ChiDatProtocolMessage) -> tuple[str, ...]:
        """Return representation errors decidable for this local profile."""

        if not isinstance(
            message,
            (
                ChiCompDataMessage,
                ChiCopyBackWrDataMessage,
                ChiSnpRespDataMessage,
            ),
        ):
            return (
                "expected a supported DAT protocol message",
            )
        reasons: list[str] = []
        node_limit = 1 << self.node_id_width
        if (
            isinstance(message, ChiCompDataMessage)
            and message.home_node_id >= node_limit
        ):
            reasons.append(
                f"HomeNID {message.home_node_id} exceeds "
                f"{self.node_id_width}-bit NodeID"
            )
        if message.data >= (1 << self.data_width):
            reasons.append(
                f"Data exceeds the configured {self.data_width}-bit payload"
            )
        if message.data_id not in self.valid_data_ids:
            encoded = f"0b{message.data_id:02b}"
            reasons.append(
                f"DataID {encoded} is reserved for a {self.data_width}-bit "
                "DAT channel"
            )
        return tuple(reasons)

    def contains(self, message: ChiDatProtocolMessage) -> bool:
        return not self.explain(message)


__all__ = [
    "ChiCompDataMessage",
    "ChiCopyBackWrDataMessage",
    "ChiDatChannelItem",
    "ChiDatLCrdReturn",
    "ChiDatOpcode",
    "ChiDatProtocolMessage",
    "ChiIssueHDatProfile",
    "ChiSnpRespDataMessage",
]
