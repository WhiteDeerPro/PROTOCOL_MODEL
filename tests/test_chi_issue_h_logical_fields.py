from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.representation import (
    CHI_ISSUE_H_LOGICAL_FIELD_CODEC,
    ChiChannelKind,
    ChiCompAckMessage,
    ChiCompDBIDRespMessage,
    ChiCompDataMessage,
    ChiCopyBackWrDataMessage,
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiLogicalCodecError,
    ChiLogicalFieldRecord,
    ChiPCrdGrantMessage,
    ChiPCrdReturnMessage,
    ChiReadNoSnpMessage,
    ChiReadNotSharedDirtyMessage,
    ChiReadSharedMessage,
    ChiReadUniqueMessage,
    ChiReqLCrdReturn,
    ChiRespCode,
    ChiRetryAckMessage,
    ChiSnpRespMessage,
    ChiSnpRespDataMessage,
    ChiSnpNotSharedDirtyMessage,
    ChiSnpSharedMessage,
    ChiSnpUniqueMessage,
    ChiWriteBackFullMessage,
)


class ChiIssueHLogicalFieldCodecTest(unittest.TestCase):
    def setUp(self) -> None:
        self.codec = CHI_ISSUE_H_LOGICAL_FIELD_CODEC

    def test_every_current_protocol_message_round_trips(self) -> None:
        messages = (
            (ChiReadNoSnpMessage(1, 0x4000), None),
            (ChiReadSharedMessage(2, 0x8000), None),
            (ChiReadNotSharedDirtyMessage(3, 0xA000), None),
            (ChiReadUniqueMessage(4, 0xC000), None),
            (
                ChiWriteBackFullMessage(
                    0x12,
                    0xE000,
                    qos=3,
                    trace_tag=True,
                ),
                None,
            ),
            (ChiPCrdReturnMessage(2), None),
            (ChiSnpRespMessage(4, ChiRespCode.I), None),
            (
                ChiSnpRespDataMessage(
                    0x104,
                    (1 << 400) | 0xD177,
                    ChiRespCode.I_PD,
                ),
                ChiIssueHDatProfile(data_width=512),
            ),
            (ChiCompAckMessage(5), None),
            (
                ChiCompDBIDRespMessage(
                    0x12,
                    0x234,
                    qos=2,
                    completer_busy=3,
                    trace_tag=True,
                ),
                None,
            ),
            (ChiRetryAckMessage(6, 3), None),
            (ChiPCrdGrantMessage(3), None),
            (ChiSnpSharedMessage(7, 0x8000), None),
            (ChiSnpNotSharedDirtyMessage(8, 0xA000), None),
            (
                ChiSnpUniqueMessage(
                    9,
                    0xC000,
                    return_to_source=True,
                ),
                None,
            ),
            (
                ChiCompDataMessage(
                    9,
                    (1 << 400) | 0x1234,
                    home_node_id=0x21,
                    response=ChiRespCode.UC,
                    data_buffer_id=0x200,
                ),
                ChiIssueHDatProfile(data_width=512),
            ),
            (
                ChiCopyBackWrDataMessage(
                    0x234,
                    (1 << 400) | 0xD177,
                    data_id=0,
                    qos=4,
                    completer_busy=2,
                    trace_tag=True,
                ),
                ChiIssueHDatProfile(data_width=512),
            ),
        )

        for message, profile in messages:
            with self.subTest(message=type(message).__name__):
                record = self.codec.encode(message, profile)
                restored = self.codec.decode(record, profile)

                self.assertEqual(message, restored)
                self.assertEqual(
                    record,
                    self.codec.encode(restored, profile),
                )
                self.assertEqual(
                    message.chi_channel.value,
                    record.to_data()["channel"],
                )

    def test_channel_and_opcode_jointly_select_the_message_form(self) -> None:
        request = self.codec.encode(
            ChiReadUniqueMessage(1, 0x8000)
        )
        snoop = self.codec.encode(
            ChiSnpUniqueMessage(2, 0x8000)
        )

        self.assertEqual(request.opcode, snoop.opcode)
        self.assertIs(ChiChannelKind.REQ, request.channel)
        self.assertIs(ChiChannelKind.SNP, snoop.channel)
        self.assertIsInstance(
            self.codec.decode(request),
            ChiReadUniqueMessage,
        )
        self.assertIsInstance(
            self.codec.decode(snoop),
            ChiSnpUniqueMessage,
        )

    def test_message_fields_exclude_network_and_transport_identity(self) -> None:
        record = self.codec.encode(
            ChiSnpUniqueMessage(2, 0x8000)
        )

        self.assertNotIn("SrcID", record.fields)
        self.assertNotIn("TgtID", record.fields)
        self.assertNotIn("PacketIndex", record.fields)
        self.assertEqual(True, record.fields["DoNotGoToSD"])

        with self.assertRaisesRegex(
            ChiLogicalCodecError,
            "coverage gap",
        ):
            self.codec.encode(ChiReqLCrdReturn())

    def test_decode_requires_the_exact_opcode_field_set(self) -> None:
        valid = self.codec.encode(
            ChiSnpUniqueMessage(2, 0x8000)
        )
        missing = dict(valid.fields)
        del missing["RetToSrc"]
        extra = dict(valid.fields)
        extra["TgtID"] = 0x07

        self.assertIn(
            "missing logical fields",
            self.codec.explain_decode(
                ChiLogicalFieldRecord(valid.channel, missing)
            )[0],
        )
        self.assertIn(
            "unexpected logical fields",
            self.codec.explain_decode(
                ChiLogicalFieldRecord(valid.channel, extra)
            )[0],
        )

    def test_boolean_fields_do_not_accept_integer_substitutes(self) -> None:
        valid = self.codec.encode(
            ChiSnpUniqueMessage(2, 0x8000)
        )
        fields = dict(valid.fields)
        fields["DoNotGoToSD"] = 1

        reasons = self.codec.explain_decode(
            ChiLogicalFieldRecord(valid.channel, fields)
        )

        self.assertIn("must be bool", reasons[0])

    def test_constants_and_profile_rules_are_checked_on_decode(self) -> None:
        grant = self.codec.encode(ChiPCrdGrantMessage(3))
        grant_fields = dict(grant.fields)
        grant_fields["TxnID"] = 1
        unique = self.codec.encode(
            ChiReadUniqueMessage(2, 0x8000)
        )
        unique_fields = dict(unique.fields)
        unique_fields["MemAttr"] = 0
        snoop = self.codec.encode(
            ChiSnpUniqueMessage(3, 0x8000)
        )
        snoop_fields = dict(snoop.fields)
        snoop_fields["DoNotGoToSD"] = False

        self.assertIn(
            "must be constant",
            self.codec.explain_decode(
                ChiLogicalFieldRecord(
                    grant.channel,
                    grant_fields,
                )
            )[0],
        )
        self.assertTrue(
            any(
                "MemAttr" in reason
                for reason in self.codec.explain_decode(
                    ChiLogicalFieldRecord(
                        unique.channel,
                        unique_fields,
                    )
                )
            )
        )
        self.assertTrue(
            any(
                "DoNotGoToSD" in reason
                for reason in self.codec.explain_decode(
                    ChiLogicalFieldRecord(
                        snoop.channel,
                        snoop_fields,
                    )
                )
            )
        )

    def test_coherent_read_profile_rejects_illegal_attributes(self) -> None:
        invalid_messages = (
            (
                ChiReadUniqueMessage(2, 0x8000, size=5),
                "Size",
            ),
            (
                ChiReadUniqueMessage(
                    2,
                    0x8000,
                    snoop_attribute=False,
                ),
                "SnpAttr",
            ),
            (
                ChiReadUniqueMessage(
                    2,
                    0x8000,
                    memory_attributes=0,
                ),
                "MemAttr",
            ),
            (
                ChiReadUniqueMessage(2, 0x8000, order=1),
                "Order",
            ),
            (
                ChiReadUniqueMessage(
                    2,
                    0x8000,
                    expect_completion_ack=False,
                ),
                "ExpCompAck",
            ),
            (
                ChiReadUniqueMessage(2, 0x8000, exclusive=True),
                "Excl",
            ),
            (
                ChiReadUniqueMessage(
                    2,
                    0x8000,
                    likely_shared=True,
                ),
                "LikelyShared",
            ),
        )

        for message, field_name in invalid_messages:
            with self.subTest(field=field_name):
                reasons = ChiIssueHReqProfile().explain(message)
                self.assertTrue(
                    any(field_name in reason for reason in reasons)
                )
                with self.assertRaises(ChiLogicalCodecError):
                    self.codec.encode(message)

    def test_req_logical_address_keeps_critical_chunk_bits(self) -> None:
        message = ChiReadUniqueMessage(2, 0x8008)

        record = self.codec.encode(message)

        self.assertEqual(0x8008, record.fields["Addr"])
        self.assertEqual(message, self.codec.decode(record))

    def test_schema_exposes_widths_without_bit_offsets(self) -> None:
        schema = self.codec.schema_for_message(
            ChiReadUniqueMessage(1, 0x8000)
        )
        assert schema is not None

        widths = schema.resolved_widths(
            ChiIssueHReqProfile(request_address_width=52)
        )

        self.assertEqual(7, widths["Opcode"])
        self.assertEqual(52, widths["Addr"])
        self.assertEqual(1, widths["ExpCompAck"])
        self.assertFalse(hasattr(schema, "bit_offset"))

    def test_writeback_forms_have_exact_logical_field_sets(self) -> None:
        cases = (
            (
                ChiWriteBackFullMessage(0x12, 0x8000),
                (
                    "Opcode",
                    "TxnID",
                    "Addr",
                    "Size",
                    "QoS",
                    "PAS",
                    "LikelyShared",
                    "AllowRetry",
                    "Order",
                    "PCrdType",
                    "MemAttr",
                    "SnpAttr",
                    "Excl",
                    "ExpCompAck",
                    "TagOp",
                    "TraceTag",
                ),
            ),
            (
                ChiCompDBIDRespMessage(0x12, 0x234),
                (
                    "Opcode",
                    "TxnID",
                    "DBID",
                    "QoS",
                    "RespErr",
                    "Resp",
                    "CBusy",
                    "TraceTag",
                ),
            ),
            (
                ChiCopyBackWrDataMessage(
                    0x234,
                    (1 << 400) | 0xD177,
                ),
                (
                    "Opcode",
                    "TxnID",
                    "Data",
                    "DataID",
                    "QoS",
                    "RespErr",
                    "Resp",
                    "DataSource",
                    "CBusy",
                    "BE",
                    "CCID",
                    "TraceTag",
                ),
            ),
        )

        for message, expected_fields in cases:
            with self.subTest(message=type(message).__name__):
                schema = self.codec.schema_for_message(message)
                assert schema is not None

                self.assertEqual(expected_fields, schema.field_names)
                self.assertEqual(
                    expected_fields,
                    tuple(
                        self.codec.encode(
                            message,
                            (
                                ChiIssueHDatProfile(data_width=512)
                                if isinstance(
                                    message,
                                    ChiCopyBackWrDataMessage,
                                )
                                else None
                            ),
                        ).fields
                    ),
                )

    def test_writeback_forms_use_their_channel_profiles(self) -> None:
        invalid_cases = (
            (
                ChiWriteBackFullMessage(
                    1,
                    0x8000,
                    size=5,
                ),
                None,
                "Size=6",
            ),
            (
                ChiCompDBIDRespMessage(
                    1,
                    2,
                    response=ChiRespCode.SC,
                ),
                None,
                "Resp=0",
            ),
            (
                ChiCopyBackWrDataMessage(
                    2,
                    1 << 200,
                ),
                ChiIssueHDatProfile(data_width=128),
                "configured 128-bit payload",
            ),
        )

        for message, profile, expected in invalid_cases:
            with self.subTest(message=type(message).__name__):
                reasons = self.codec.explain_encode(message, profile)

                self.assertTrue(
                    any(expected in reason for reason in reasons)
                )
                with self.assertRaises(ChiLogicalCodecError):
                    self.codec.encode(message, profile)

    def test_unknown_opcode_is_a_codec_coverage_gap(self) -> None:
        record = ChiLogicalFieldRecord(
            ChiChannelKind.REQ,
            {"Opcode": 0x3F},
        )

        reasons = self.codec.explain_decode(record)

        self.assertIn("coverage gap", reasons[0])


if __name__ == "__main__":
    unittest.main()
