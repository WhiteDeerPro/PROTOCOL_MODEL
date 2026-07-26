"""Named-field codec for the implemented CHI Issue H message forms.

The codec sits between typed protocol messages and packed channel flits:

``typed message <-> logical field record <-> future packed-bit codec``

A logical field record preserves the specification-facing field names,
per-opcode field presence, constants, and widths.  It deliberately has no bit
offsets, padding, parity, lane placement, or PHY meaning.  Network route and
fragment identities also remain on :class:`ChiNetworkPacket`; this module only
projects protocol-message fields.

The registry is local to this optional codec.  A typed message that has no
registered logical form can still be a valid CHI representation when a caller
provides a compatible profile.  Codec coverage must therefore not be used as
a global protocol-message allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, TypeAlias

from .dat import (
    ChiCompDataMessage,
    ChiDatOpcode,
    ChiSnpRespDataMessage,
)
from .domain import (
    CHI_ISSUE_H_CHANNEL_DOMAIN,
    ChiChannelKind,
    ChiChannelProfile,
    ChiProtocolMessage,
)
from .req import (
    ChiPCrdReturnMessage,
    ChiReadNoSnpMessage,
    ChiReadNotSharedDirtyMessage,
    ChiReadSharedMessage,
    ChiReadUniqueMessage,
    ChiReqOpcode,
)
from .rsp import (
    ChiCompAckMessage,
    ChiPCrdGrantMessage,
    ChiRetryAckMessage,
    ChiRspOpcode,
    ChiSnpRespMessage,
)
from .snp import (
    ChiSnpOpcode,
    ChiSnpNotSharedDirtyMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
)


ChiLogicalFieldValue: TypeAlias = int | bool


class ChiLogicalCodecError(ValueError):
    """A structural or profile error at the logical-field boundary."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        if not reasons:
            raise ValueError("logical codec error requires at least one reason")
        self.reasons = tuple(reasons)
        super().__init__("; ".join(self.reasons))


@dataclass(frozen=True)
class ChiLogicalFieldRecord:
    """One channel-qualified, immutable set of normalized logical fields.

    Boolean protocol fields remain Python ``bool`` values.  Integer fields,
    including ``Opcode`` and enums such as ``Resp``, are normalized to plain
    non-negative integers.  The selected opcode schema later decides the
    exact field set and widths.
    """

    channel: ChiChannelKind
    fields: Mapping[str, ChiLogicalFieldValue]

    def __post_init__(self) -> None:
        try:
            channel = ChiChannelKind(self.channel)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "logical field record requires a known CHI channel"
            ) from error
        normalized: dict[str, ChiLogicalFieldValue] = {}
        for name, value in dict(self.fields).items():
            if not isinstance(name, str) or not name:
                raise ValueError(
                    "logical field names must be non-empty strings"
                )
            if type(value) is bool:
                normalized[name] = value
                continue
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(
                    f"logical field {name} must be bool or a "
                    "non-negative integer"
                )
            normalized[name] = int(value)
        opcode = normalized.get("Opcode")
        if (
            not isinstance(opcode, int)
            or isinstance(opcode, bool)
            or opcode < 0
        ):
            raise ValueError(
                "logical field record requires an integer Opcode field"
            )
        object.__setattr__(self, "channel", channel)
        object.__setattr__(
            self,
            "fields",
            MappingProxyType(normalized),
        )

    @property
    def opcode(self) -> int:
        return int(self.fields["Opcode"])

    def to_data(self) -> dict[str, object]:
        """Return a JSON-friendly copy without assigning packed bit positions."""

        return {
            "channel": self.channel.value,
            "fields": dict(self.fields),
        }


@dataclass(frozen=True)
class ChiLogicalFieldSpec:
    """One field in an opcode-specific logical message form.

    ``width`` is used for fixed-width fields.  ``profile_width`` names a
    profile attribute such as ``request_address_width`` or ``data_width``.
    A field with no ``attribute`` is a required constant and is not passed to
    the typed message constructor.
    """

    name: str
    attribute: str | None
    width: int | None = None
    profile_width: str | None = None
    boolean: bool = False
    constant: ChiLogicalFieldValue | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("logical field spec requires a name")
        if self.attribute is not None and (
            not isinstance(self.attribute, str) or not self.attribute
        ):
            raise ValueError(
                "logical field attribute must be a non-empty string"
            )
        if (self.width is None) == (self.profile_width is None):
            raise ValueError(
                "logical field spec requires exactly one width source"
            )
        if self.width is not None and (
            not isinstance(self.width, int)
            or isinstance(self.width, bool)
            or self.width <= 0
        ):
            raise ValueError("logical field width must be positive")
        if self.profile_width is not None and (
            not isinstance(self.profile_width, str)
            or not self.profile_width
        ):
            raise ValueError(
                "profile width source must be a non-empty attribute name"
            )
        if self.boolean and self.width != 1:
            raise ValueError(
                "logical boolean fields require a fixed one-bit width"
            )
        if self.attribute is None and self.constant is None:
            raise ValueError(
                "a field without a constructor attribute must be constant"
            )
        if self.attribute is not None and self.constant is not None:
            raise ValueError(
                "constructor fields cannot also declare a constant"
            )

    @property
    def is_constant(self) -> bool:
        return self.attribute is None

    def resolved_width(self, profile: ChiChannelProfile) -> int:
        if self.width is not None:
            return self.width
        assert self.profile_width is not None
        value = getattr(profile, self.profile_width, None)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
        ):
            raise ValueError(
                f"profile does not provide positive width "
                f"{self.profile_width}"
            )
        return value

    def value_from(
        self,
        message: ChiProtocolMessage,
    ) -> ChiLogicalFieldValue:
        if self.is_constant:
            assert self.constant is not None
            return self.constant
        assert self.attribute is not None
        value = getattr(message, self.attribute)
        if type(value) is bool:
            return value
        return int(value)


@dataclass(frozen=True)
class ChiLogicalMessageSchema:
    """The exact named-field form selected by one channel and opcode."""

    channel: ChiChannelKind
    opcode: int
    message_type: type
    fields: tuple[ChiLogicalFieldSpec, ...]

    def __post_init__(self) -> None:
        try:
            channel = ChiChannelKind(self.channel)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "logical message schema requires a known channel"
            ) from error
        if (
            not isinstance(self.opcode, int)
            or isinstance(self.opcode, bool)
            or self.opcode < 0
        ):
            raise ValueError(
                "logical message schema opcode must be non-negative"
            )
        fields = tuple(self.fields)
        names = tuple(item.name for item in fields)
        if len(set(names)) != len(names):
            raise ValueError(
                "logical message schema field names must be unique"
            )
        if not fields or fields[0].name != "Opcode":
            raise ValueError(
                "logical message schema must begin with Opcode"
            )
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "opcode", int(self.opcode))
        object.__setattr__(self, "fields", fields)

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields)

    def resolved_widths(
        self,
        profile: ChiChannelProfile,
    ) -> Mapping[str, int]:
        """Return immutable field-width metadata for reports and adapters."""

        return MappingProxyType(
            {
                field.name: field.resolved_width(profile)
                for field in self.fields
            }
        )


def _integer(
    name: str,
    attribute: str,
    width: int | None = None,
    *,
    profile_width: str | None = None,
) -> ChiLogicalFieldSpec:
    return ChiLogicalFieldSpec(
        name,
        attribute,
        width,
        profile_width,
    )


def _boolean(name: str, attribute: str) -> ChiLogicalFieldSpec:
    return ChiLogicalFieldSpec(
        name,
        attribute,
        width=1,
        boolean=True,
    )


def _constant(
    name: str,
    value: int,
    width: int,
) -> ChiLogicalFieldSpec:
    return ChiLogicalFieldSpec(
        name,
        None,
        width=width,
        constant=value,
    )


_READ_FIELDS = (
    _integer("TxnID", "transaction_id", 12),
    _integer(
        "Addr",
        "address",
        profile_width="request_address_width",
    ),
    _integer("Size", "size", 3),
    _integer("QoS", "qos", 4),
    _integer("PAS", "pas", 3),
    _boolean("LikelyShared", "likely_shared"),
    _boolean("AllowRetry", "allow_retry"),
    _integer("Order", "order", 2),
    _integer("PCrdType", "protocol_credit_type", 4),
    _integer("MemAttr", "memory_attributes", 4),
    _boolean("SnpAttr", "snoop_attribute"),
    _boolean("Excl", "exclusive"),
    _boolean("ExpCompAck", "expect_completion_ack"),
    _integer("TagOp", "tag_operation", 2),
    _boolean("TraceTag", "trace_tag"),
)

_SNOOP_FIELDS = (
    _integer("TxnID", "transaction_id", 12),
    _integer(
        "Addr",
        "address",
        profile_width="snoop_address_width",
    ),
    _integer("QoS", "qos", 4),
    _integer("PAS", "pas", 3),
    _boolean("DoNotGoToSD", "do_not_go_to_shared_dirty"),
    _boolean("RetToSrc", "return_to_source"),
    _boolean("TraceTag", "trace_tag"),
)


def _schema(
    channel: ChiChannelKind,
    opcode: int,
    opcode_width: int,
    message_type: type,
    fields: tuple[ChiLogicalFieldSpec, ...],
) -> ChiLogicalMessageSchema:
    return ChiLogicalMessageSchema(
        channel,
        int(opcode),
        message_type,
        (
            _constant("Opcode", int(opcode), opcode_width),
            *fields,
        ),
    )


_CHI_ISSUE_H_LOGICAL_SCHEMAS = (
    _schema(
        ChiChannelKind.REQ,
        ChiReqOpcode.READ_NO_SNP,
        7,
        ChiReadNoSnpMessage,
        _READ_FIELDS,
    ),
    _schema(
        ChiChannelKind.REQ,
        ChiReqOpcode.READ_SHARED,
        7,
        ChiReadSharedMessage,
        _READ_FIELDS,
    ),
    _schema(
        ChiChannelKind.REQ,
        ChiReqOpcode.READ_NOT_SHARED_DIRTY,
        7,
        ChiReadNotSharedDirtyMessage,
        _READ_FIELDS,
    ),
    _schema(
        ChiChannelKind.REQ,
        ChiReqOpcode.READ_UNIQUE,
        7,
        ChiReadUniqueMessage,
        _READ_FIELDS,
    ),
    _schema(
        ChiChannelKind.REQ,
        ChiReqOpcode.PROTOCOL_CREDIT_RETURN,
        7,
        ChiPCrdReturnMessage,
        (
            _constant("TxnID", 0, 12),
            _integer("PCrdType", "protocol_credit_type", 4),
        ),
    ),
    _schema(
        ChiChannelKind.RSP,
        ChiRspOpcode.SNP_RESP,
        5,
        ChiSnpRespMessage,
        (
            _integer("TxnID", "transaction_id", 12),
            _integer("Resp", "response", 3),
            _integer("QoS", "qos", 4),
            _integer("RespErr", "response_error", 2),
            _boolean("TraceTag", "trace_tag"),
        ),
    ),
    _schema(
        ChiChannelKind.RSP,
        ChiRspOpcode.COMP_ACK,
        5,
        ChiCompAckMessage,
        (
            _integer("TxnID", "transaction_id", 12),
            _integer("QoS", "qos", 4),
            _integer("Resp", "response", 3),
            _boolean("TraceTag", "trace_tag"),
        ),
    ),
    _schema(
        ChiChannelKind.RSP,
        ChiRspOpcode.RETRY_ACK,
        5,
        ChiRetryAckMessage,
        (
            _integer("TxnID", "transaction_id", 12),
            _integer("PCrdType", "protocol_credit_type", 4),
            _integer("QoS", "qos", 4),
            _boolean("TraceTag", "trace_tag"),
        ),
    ),
    _schema(
        ChiChannelKind.RSP,
        ChiRspOpcode.PROTOCOL_CREDIT_GRANT,
        5,
        ChiPCrdGrantMessage,
        (
            _constant("TxnID", 0, 12),
            _integer("PCrdType", "protocol_credit_type", 4),
            _integer("QoS", "qos", 4),
            _boolean("TraceTag", "trace_tag"),
        ),
    ),
    _schema(
        ChiChannelKind.SNP,
        ChiSnpOpcode.SNP_SHARED,
        5,
        ChiSnpSharedMessage,
        _SNOOP_FIELDS,
    ),
    _schema(
        ChiChannelKind.SNP,
        ChiSnpOpcode.SNP_NOT_SHARED_DIRTY,
        5,
        ChiSnpNotSharedDirtyMessage,
        _SNOOP_FIELDS,
    ),
    _schema(
        ChiChannelKind.SNP,
        ChiSnpOpcode.SNP_UNIQUE,
        5,
        ChiSnpUniqueMessage,
        _SNOOP_FIELDS,
    ),
    _schema(
        ChiChannelKind.DAT,
        ChiDatOpcode.SNP_RESP_DATA,
        4,
        ChiSnpRespDataMessage,
        (
            _integer("TxnID", "transaction_id", 12),
            _integer(
                "Data",
                "data",
                profile_width="data_width",
            ),
            _integer("DataID", "data_id", 2),
            _integer("QoS", "qos", 4),
            _integer("RespErr", "response_error", 2),
            _integer("Resp", "response", 3),
            _integer("DataSource", "data_source", 8),
            _integer("CBusy", "completer_busy", 3),
            _constant("DBID", 0, 12),
            _integer("CCID", "critical_chunk_id", 2),
            _boolean("TraceTag", "trace_tag"),
        ),
    ),
    _schema(
        ChiChannelKind.DAT,
        ChiDatOpcode.COMP_DATA,
        4,
        ChiCompDataMessage,
        (
            _integer("TxnID", "transaction_id", 12),
            _integer(
                "Data",
                "data",
                profile_width="data_width",
            ),
            _integer("DataID", "data_id", 2),
            _integer(
                "HomeNID",
                "home_node_id",
                profile_width="node_id_width",
            ),
            _integer("QoS", "qos", 4),
            _integer("RespErr", "response_error", 2),
            _integer("Resp", "response", 3),
            _integer("DataSource", "data_source", 8),
            _integer("CBusy", "completer_busy", 3),
            _integer("DBID", "data_buffer_id", 12),
            _integer("CCID", "critical_chunk_id", 2),
            _boolean("TraceTag", "trace_tag"),
        ),
    ),
)


class ChiIssueHLogicalFieldCodec:
    """Strict bidirectional codec for the registered logical message forms."""

    def __init__(
        self,
        schemas: tuple[ChiLogicalMessageSchema, ...] = (
            _CHI_ISSUE_H_LOGICAL_SCHEMAS
        ),
    ) -> None:
        schemas = tuple(schemas)
        by_key: dict[
            tuple[ChiChannelKind, int],
            ChiLogicalMessageSchema,
        ] = {}
        by_type: dict[type, ChiLogicalMessageSchema] = {}
        for schema in schemas:
            key = (schema.channel, schema.opcode)
            if key in by_key:
                raise ValueError(
                    f"duplicate logical codec form for "
                    f"{schema.channel.name} opcode {schema.opcode:#x}"
                )
            if schema.message_type in by_type:
                raise ValueError(
                    f"duplicate logical codec form for "
                    f"{schema.message_type.__name__}"
                )
            by_key[key] = schema
            by_type[schema.message_type] = schema
        self._schemas = schemas
        self._by_key = MappingProxyType(by_key)
        self._by_type = MappingProxyType(by_type)

    @property
    def schemas(self) -> tuple[ChiLogicalMessageSchema, ...]:
        return self._schemas

    def schema_for_message(
        self,
        message: object,
    ) -> ChiLogicalMessageSchema | None:
        """Return this codec's form without classifying global legality."""

        return self._by_type.get(type(message))

    def schema_for_record(
        self,
        record: ChiLogicalFieldRecord,
    ) -> ChiLogicalMessageSchema | None:
        if not isinstance(record, ChiLogicalFieldRecord):
            raise TypeError(
                "logical codec record lookup requires "
                "ChiLogicalFieldRecord"
            )
        return self._by_key.get((record.channel, record.opcode))

    def explain_encode(
        self,
        message: object,
        profile: ChiChannelProfile | None = None,
    ) -> tuple[str, ...]:
        """Explain why a typed message cannot use this logical codec."""

        schema = self.schema_for_message(message)
        if schema is None:
            return (
                f"{type(message).__name__} has no registered logical-field "
                "form; this is a codec coverage gap, not a global protocol "
                "legality verdict",
            )
        selected, reasons = self._select_profile(
            schema.channel,
            profile,
        )
        if reasons:
            return reasons
        assert selected is not None
        value_reasons: list[str] = []
        for field in schema.fields:
            value_reasons.extend(
                self._explain_field_value(
                    field,
                    field.value_from(message),
                    selected,
                )
            )
        value_reasons.extend(
            CHI_ISSUE_H_CHANNEL_DOMAIN.explain_profile(
                message,
                selected,
            )
        )
        return tuple(value_reasons)

    def encode(
        self,
        message: object,
        profile: ChiChannelProfile | None = None,
    ) -> ChiLogicalFieldRecord:
        """Project one legal typed message into its exact named fields."""

        reasons = self.explain_encode(message, profile)
        if reasons:
            raise ChiLogicalCodecError(reasons)
        schema = self.schema_for_message(message)
        assert schema is not None
        return ChiLogicalFieldRecord(
            schema.channel,
            {
                field.name: field.value_from(message)
                for field in schema.fields
            },
        )

    def explain_decode(
        self,
        record: ChiLogicalFieldRecord,
        profile: ChiChannelProfile | None = None,
    ) -> tuple[str, ...]:
        """Explain why a named-field record cannot restore a typed message."""

        _, reasons = self._decode(record, profile)
        return reasons

    def decode(
        self,
        record: ChiLogicalFieldRecord,
        profile: ChiChannelProfile | None = None,
    ) -> ChiProtocolMessage:
        """Restore one typed message after exact-shape and profile checks."""

        message, reasons = self._decode(record, profile)
        if reasons:
            raise ChiLogicalCodecError(reasons)
        assert message is not None
        return message

    def _decode(
        self,
        record: ChiLogicalFieldRecord,
        profile: ChiChannelProfile | None,
    ) -> tuple[ChiProtocolMessage | None, tuple[str, ...]]:
        if not isinstance(record, ChiLogicalFieldRecord):
            return None, (
                "logical decode requires ChiLogicalFieldRecord",
            )
        schema = self.schema_for_record(record)
        if schema is None:
            return None, (
                f"no logical-field form is registered for "
                f"{record.channel.name} opcode {record.opcode:#x}; this is "
                "a codec coverage gap",
            )
        selected, profile_reasons = self._select_profile(
            schema.channel,
            profile,
        )
        reasons = list(profile_reasons)
        expected = set(schema.field_names)
        actual = set(record.fields)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            reasons.append(f"missing logical fields {missing!r}")
        if extra:
            reasons.append(f"unexpected logical fields {extra!r}")
        if selected is not None:
            for field in schema.fields:
                if field.name in record.fields:
                    reasons.extend(
                        self._explain_field_value(
                            field,
                            record.fields[field.name],
                            selected,
                        )
                    )
        if reasons:
            return None, tuple(reasons)

        kwargs = {
            field.attribute: record.fields[field.name]
            for field in schema.fields
            if field.attribute is not None
        }
        try:
            message = schema.message_type(**kwargs)
        except (TypeError, ValueError) as error:
            return None, (
                f"typed message construction failed: {error}",
            )
        assert selected is not None
        reasons = list(
            CHI_ISSUE_H_CHANNEL_DOMAIN.explain_profile(
                message,
                selected,
            )
        )
        if reasons:
            return None, tuple(reasons)
        return message, ()

    @staticmethod
    def _select_profile(
        channel: ChiChannelKind,
        profile: ChiChannelProfile | None,
    ) -> tuple[ChiChannelProfile | None, tuple[str, ...]]:
        selected = (
            profile
            if profile is not None
            else CHI_ISSUE_H_CHANNEL_DOMAIN.default_profile(channel)
        )
        if selected is None:
            return None, (
                f"no representation profile is installed for "
                f"{channel.name}",
            )
        try:
            profile_channel = ChiChannelKind(selected.channel)
        except (AttributeError, TypeError, ValueError):
            return None, (
                "logical codec profile does not declare a known channel",
            )
        if profile_channel is not channel:
            return None, (
                f"{profile_channel.name} profile cannot be used with "
                f"{channel.name} logical fields",
            )
        return selected, ()

    @staticmethod
    def _explain_field_value(
        field: ChiLogicalFieldSpec,
        value: ChiLogicalFieldValue,
        profile: ChiChannelProfile,
    ) -> tuple[str, ...]:
        if field.boolean:
            if type(value) is not bool:
                return (
                    f"{field.name} must be bool in the logical record",
                )
        elif (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            return (
                f"{field.name} must be a non-negative integer in the "
                "logical record",
            )
        try:
            width = field.resolved_width(profile)
        except ValueError as error:
            return (str(error),)
        encoded = int(value)
        reasons: list[str] = []
        if encoded >= (1 << width):
            reasons.append(
                f"{field.name}={encoded} exceeds its {width}-bit "
                "logical width"
            )
        if field.is_constant and value != field.constant:
            reasons.append(
                f"{field.name} must be constant {field.constant!r}"
            )
        return tuple(reasons)


CHI_ISSUE_H_LOGICAL_FIELD_CODEC = ChiIssueHLogicalFieldCodec()


__all__ = [
    "CHI_ISSUE_H_LOGICAL_FIELD_CODEC",
    "ChiIssueHLogicalFieldCodec",
    "ChiLogicalCodecError",
    "ChiLogicalFieldRecord",
    "ChiLogicalFieldSpec",
    "ChiLogicalFieldValue",
    "ChiLogicalMessageSchema",
]
