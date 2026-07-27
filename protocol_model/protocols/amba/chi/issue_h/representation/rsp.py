"""Typed forms for the first executable CHI Issue H RSP-channel slice.

The current forms cover Request Retry, non-data Snoop response, completion,
completion acknowledgement, and the combined completion/data-buffer grant
used by a CopyBack Write.  Routing NodeIDs are added by the Network packet
rather than repeated in each message form.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import ClassVar, TypeAlias

from .domain import ChiChannelKind, ChiChannelItemKind
from .response import ChiRespCode, ChiRespErr


class ChiRspOpcode(IntEnum):
    """RSP opcodes implemented by the current representation slice."""

    LINK_CREDIT_RETURN = 0x00
    SNP_RESP = 0x01
    COMP_ACK = 0x02
    RETRY_ACK = 0x03
    COMP = 0x04
    COMP_DBID_RESP = 0x05
    PROTOCOL_CREDIT_GRANT = 0x07


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
class ChiRetryAckMessage:
    """Semantic fields of one ``RetryAck`` response.

    The response identifies the rejected request with its original TxnID and
    names the P-Credit type required for a later retry.  Matching the response
    to a retained request is a protocol-lifecycle responsibility, not a local
    representation check.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.RSP
    chi_item_kind: ClassVar[ChiChannelItemKind] = ChiChannelItemKind.PROTOCOL_MESSAGE

    transaction_id: int
    protocol_credit_type: int
    qos: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        for name, value, width in (
            ("transaction_id", self.transaction_id, 12),
            ("protocol_credit_type", self.protocol_credit_type, 4),
            ("qos", self.qos, 4),
        ):
            _require_uint(name, value, width)
        _require_bool("trace_tag", self.trace_tag)

    @property
    def opcode(self) -> ChiRspOpcode:
        return ChiRspOpcode.RETRY_ACK

    @property
    def semantic_key(self) -> int:
        """Return the transaction key within one Requester identity."""

        return self.transaction_id


@dataclass(frozen=True)
class ChiSnpRespMessage:
    """Minimal non-data response to one Home-issued Snoop request."""

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.RSP
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int
    response: ChiRespCode | int
    qos: int = 0
    response_error: ChiRespErr | int = ChiRespErr.OK
    trace_tag: bool = False

    def __post_init__(self) -> None:
        _require_uint("transaction_id", self.transaction_id, 12)
        _require_uint("response", self.response, 3)
        _require_uint("qos", self.qos, 4)
        _require_uint("response_error", self.response_error, 2)
        _require_bool("trace_tag", self.trace_tag)
        object.__setattr__(
            self,
            "response_error",
            ChiRespErr(self.response_error),
        )
        try:
            response = ChiRespCode(self.response)
        except ValueError as error:
            raise ValueError("SnpResp contains a reserved Resp encoding") from error
        if int(response) & 0b100:
            raise ValueError(
                "PassDirty requires a data-bearing SnpRespData response"
            )
        object.__setattr__(self, "response", response)

    @property
    def opcode(self) -> ChiRspOpcode:
        return ChiRspOpcode.SNP_RESP

    @property
    def semantic_key(self) -> int:
        return self.transaction_id


@dataclass(frozen=True)
class ChiCompAckMessage:
    """Completion acknowledgement correlated by the Home-provided DBID."""

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.RSP
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int
    qos: int = 0
    response: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        _require_uint("transaction_id", self.transaction_id, 12)
        _require_uint("qos", self.qos, 4)
        _require_uint("response", self.response, 3)
        _require_bool("trace_tag", self.trace_tag)

    @property
    def opcode(self) -> ChiRspOpcode:
        return ChiRspOpcode.COMP_ACK

    @property
    def semantic_key(self) -> int:
        return self.transaction_id


@dataclass(frozen=True)
class ChiCompMessage:
    """Completion carrying the original TxnID and a Home-owned DBID.

    The generic RSP form keeps the legal completion-state encodings distinct
    from the current executable profile.  That profile deliberately accepts
    only ``Comp_UC`` for the first ``CleanUnique`` lifecycle; cross-message
    TxnID/DBID correlation remains a transaction contract.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.RSP
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int
    data_buffer_id: int
    qos: int = 0
    response_error: ChiRespErr | int = ChiRespErr.OK
    response: ChiRespCode | int = ChiRespCode.UC
    completer_busy: int = 0
    tag_operation: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        for name, value, width in (
            ("transaction_id", self.transaction_id, 12),
            ("data_buffer_id", self.data_buffer_id, 12),
            ("qos", self.qos, 4),
            ("response_error", self.response_error, 2),
            ("response", self.response, 3),
            ("completer_busy", self.completer_busy, 3),
            ("tag_operation", self.tag_operation, 2),
        ):
            _require_uint(name, value, width)
        _require_bool("trace_tag", self.trace_tag)
        object.__setattr__(
            self,
            "response_error",
            ChiRespErr(self.response_error),
        )
        try:
            response = ChiRespCode(self.response)
        except ValueError as error:
            raise ValueError("Comp contains a reserved Resp encoding") from error
        if response in (
            ChiRespCode.SD,
            ChiRespCode.I_PD,
            ChiRespCode.SC_PD,
        ):
            raise ValueError("Comp contains a reserved Resp encoding")
        object.__setattr__(self, "response", response)

    @property
    def opcode(self) -> ChiRspOpcode:
        return ChiRspOpcode.COMP

    @property
    def semantic_key(self) -> int:
        """Return the original Requester-owned transaction identifier."""

        return self.transaction_id


@dataclass(frozen=True)
class ChiCompDBIDRespMessage:
    """Combined completion and data-buffer grant for a Write transaction.

    ``transaction_id`` echoes the Requester's original REQ TxnID.
    ``data_buffer_id`` is allocated by the Completer; subsequent WriteData
    carries that DBID in its own TxnID field.  The cross-message correlation
    and buffer lifetime are protocol contracts above this local form.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.RSP
    chi_item_kind: ClassVar[ChiChannelItemKind] = (
        ChiChannelItemKind.PROTOCOL_MESSAGE
    )

    transaction_id: int
    data_buffer_id: int
    qos: int = 0
    response_error: ChiRespErr | int = ChiRespErr.OK
    response: int = 0
    completer_busy: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        for name, value, width in (
            ("transaction_id", self.transaction_id, 12),
            ("data_buffer_id", self.data_buffer_id, 12),
            ("qos", self.qos, 4),
            ("response_error", self.response_error, 2),
            ("response", self.response, 3),
            ("completer_busy", self.completer_busy, 3),
        ):
            _require_uint(name, value, width)
        _require_bool("trace_tag", self.trace_tag)
        object.__setattr__(
            self,
            "response_error",
            ChiRespErr(self.response_error),
        )

    @property
    def opcode(self) -> ChiRspOpcode:
        return ChiRspOpcode.COMP_DBID_RESP

    @property
    def semantic_key(self) -> int:
        """Return the original Requester-owned transaction identifier."""

        return self.transaction_id


@dataclass(frozen=True)
class ChiPCrdGrantMessage:
    """Semantic fields of one transaction-independent ``PCrdGrant``.

    PCrdGrant is not associated with a particular TxnID.  The architectural
    TxnID field is therefore exposed as the required constant zero property.
    A later Retry ledger pools grants by participant identity and PCrdType.
    """

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.RSP
    chi_item_kind: ClassVar[ChiChannelItemKind] = ChiChannelItemKind.PROTOCOL_MESSAGE

    protocol_credit_type: int
    qos: int = 0
    trace_tag: bool = False

    def __post_init__(self) -> None:
        _require_uint(
            "protocol_credit_type", self.protocol_credit_type, 4
        )
        _require_uint("qos", self.qos, 4)
        _require_bool("trace_tag", self.trace_tag)

    @property
    def opcode(self) -> ChiRspOpcode:
        return ChiRspOpcode.PROTOCOL_CREDIT_GRANT

    @property
    def transaction_id(self) -> int:
        return 0

    @property
    def credit_key(self) -> int:
        """Return the credit type within one endpoint-pair identity."""

        return self.protocol_credit_type


@dataclass(frozen=True)
class ChiRspLCrdReturn:
    """RSP link flit returning one unused L-Credit to the receiver."""

    chi_channel: ClassVar[ChiChannelKind] = ChiChannelKind.RSP
    chi_item_kind: ClassVar[ChiChannelItemKind] = ChiChannelItemKind.LINK_MAINTENANCE_FLIT

    @property
    def opcode(self) -> ChiRspOpcode:
        return ChiRspOpcode.LINK_CREDIT_RETURN

    @property
    def transaction_id(self) -> int:
        return 0


ChiRspProtocolMessage: TypeAlias = (
    ChiSnpRespMessage
    | ChiCompAckMessage
    | ChiCompMessage
    | ChiCompDBIDRespMessage
    | ChiRetryAckMessage
    | ChiPCrdGrantMessage
)
ChiRspChannelItem: TypeAlias = ChiRspProtocolMessage | ChiRspLCrdReturn


@dataclass(frozen=True)
class ChiIssueHRspProfile:
    """Variable field widths used by the minimal Issue H RSP forms."""

    channel: ClassVar[ChiChannelKind] = ChiChannelKind.RSP

    node_id_width: int = 7

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_id_width, int)
            or isinstance(self.node_id_width, bool)
            or not 7 <= self.node_id_width <= 16
        ):
            raise ValueError("node_id_width must be in the Issue H range 7..16")

    def explain(self, message: ChiRspProtocolMessage) -> tuple[str, ...]:
        """Return representation errors decidable for this local profile."""

        if not isinstance(
            message,
            (
                ChiSnpRespMessage,
                ChiCompAckMessage,
                ChiCompMessage,
                ChiCompDBIDRespMessage,
                ChiRetryAckMessage,
                ChiPCrdGrantMessage,
            ),
        ):
            return ("expected a supported RSP protocol message",)
        reasons: list[str] = []
        if isinstance(message, ChiCompDBIDRespMessage) and message.response != 0:
            reasons.append(
                "CompDBIDResp requires Resp=0 for a Write completion",
            )
        if isinstance(message, ChiCompMessage):
            if message.response is not ChiRespCode.UC:
                reasons.append(
                    "the current Comp profile requires Resp=UC"
                )
            if message.response_error != 0:
                reasons.append(
                    "the current Comp profile requires RespErr=0"
                )
            if message.tag_operation != 0:
                reasons.append(
                    "the current Comp profile requires TagOp=0"
                )
        return tuple(reasons)

    def contains(self, message: ChiRspProtocolMessage) -> bool:
        return not self.explain(message)


__all__ = [
    "ChiIssueHRspProfile",
    "ChiCompAckMessage",
    "ChiCompMessage",
    "ChiCompDBIDRespMessage",
    "ChiPCrdGrantMessage",
    "ChiRetryAckMessage",
    "ChiSnpRespMessage",
    "ChiRspChannelItem",
    "ChiRspLCrdReturn",
    "ChiRspOpcode",
    "ChiRspProtocolMessage",
]
