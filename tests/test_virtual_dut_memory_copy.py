from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints.memory_copy import (
    build_amba_serialized_memory_copy_vdut,
)
from protocol_model.protocols.amba.ahb.ahb_lite import build_ahb_lite_interface
from protocol_model.protocols.amba.apb.apb4 import Apb4Config, build_apb4_interface
from protocol_model.protocols.amba.axi.axi4 import build_axi4_interface
from protocol_model.protocols.amba.axi.axi4_lite import (
    Axi4LiteConfig,
    build_axi4_lite_interface,
)
from protocol_model.semantics import CanonicalEvent
from protocol_model.virtual_dut.backend.memory_copy import (
    MemoryCopyDescriptor,
    MemoryCopyPhase,
    SerializedMemoryCopyBackend,
)
from protocol_model.virtual_dut.backend.transition import PortInput


class SerializedMemoryCopyTest(unittest.TestCase):
    @staticmethod
    def _engine(descriptor: MemoryCopyDescriptor):
        dut = build_amba_serialized_memory_copy_vdut(
            "dma",
            build_axi4_lite_interface(),
            descriptor,
            port_name="axi",
        )
        backend = dut.backend
        assert isinstance(backend, SerializedMemoryCopyBackend)
        return dut, backend

    @staticmethod
    def _read_response(data: int, *, response: str = "OKAY") -> PortInput:
        return PortInput(
            "axi",
            CanonicalEvent(
                "R", None, {"data": data, "resp": response}
            ),
        )

    @staticmethod
    def _write_response(*, response: str = "OKAY") -> PortInput:
        return PortInput(
            "axi", CanonicalEvent("B", None, {"resp": response})
        )

    def test_fixed_source_stride_copies_successive_beats_to_memory(self) -> None:
        descriptor = MemoryCopyDescriptor(
            0x1000,
            0x2000,
            length_bytes=8,
            beat_bytes=4,
            source_stride=0,
        )
        dut, backend = self._engine(descriptor)
        self.assertEqual("manager", dut.port("axi").role)
        self.assertEqual(4, descriptor.destination_stride)

        state = backend.initial_state()
        first_read = backend.advance(state)
        self.assertIsNone(first_read.fault)
        self.assertEqual(("AR",), tuple(
            item.event.kind for item in first_read.emissions
        ))
        self.assertEqual(0x1000, first_read.emissions[0].event.payload["addr"])
        self.assertEqual(MemoryCopyPhase.READ_PENDING, first_read.state.phase)

        read_done = backend.accept(
            first_read.state, self._read_response(0x11223344)
        )
        self.assertIsNone(read_done.fault)
        self.assertEqual(MemoryCopyPhase.NEED_WRITE, read_done.state.phase)

        first_write = backend.advance(read_done.state)
        self.assertEqual(("AW", "W"), tuple(
            item.event.kind for item in first_write.emissions
        ))
        self.assertEqual(0x2000, first_write.emissions[0].event.payload["addr"])
        self.assertEqual(
            0x11223344, first_write.emissions[1].event.payload["data"]
        )
        first_done = backend.accept(
            first_write.state, self._write_response()
        )
        self.assertEqual(4, first_done.state.bytes_copied)
        self.assertFalse(first_done.state.done)

        second_read = backend.advance(first_done.state)
        self.assertEqual(0x1000, second_read.emissions[0].event.payload["addr"])
        second_read_done = backend.accept(
            second_read.state, self._read_response(0x55667788)
        )
        second_write = backend.advance(second_read_done.state)
        self.assertEqual(0x2004, second_write.emissions[0].event.payload["addr"])
        completed = backend.accept(
            second_write.state, self._write_response()
        )

        self.assertIsNone(completed.fault)
        self.assertTrue(completed.state.done)
        self.assertFalse(completed.state.failed)
        self.assertEqual(8, completed.state.bytes_copied)
        self.assertEqual(2, completed.state.beat_index)
        self.assertTrue(backend.is_quiescent(completed.state))

    def test_endpoint_error_is_public_dma_state_not_model_fault(self) -> None:
        _, backend = self._engine(
            MemoryCopyDescriptor(0x1000, 0x2000, 4, 4)
        )
        read = backend.advance(backend.initial_state())
        failed = backend.accept(
            read.state,
            self._read_response(0, response="DECERR"),
        )

        self.assertIsNone(failed.fault)
        self.assertTrue(failed.state.failed)
        self.assertEqual(0, failed.state.bytes_copied)
        self.assertEqual("read", failed.state.error.operation)
        self.assertEqual(0x1000, failed.state.error.address)
        self.assertEqual("decode_error", failed.state.error.status.value)
        self.assertTrue(backend.is_quiescent(failed.state))

    def test_write_error_stops_before_counting_the_beat(self) -> None:
        _, backend = self._engine(
            MemoryCopyDescriptor(0x1000, 0x2000, 4, 4)
        )
        read = backend.advance(backend.initial_state())
        read_done = backend.accept(
            read.state,
            self._read_response(0xAABBCCDD),
        )
        write = backend.advance(read_done.state)
        failed = backend.accept(
            write.state, self._write_response(response="SLVERR")
        )

        self.assertIsNone(failed.fault)
        self.assertTrue(failed.state.failed)
        self.assertEqual(0, failed.state.bytes_copied)
        self.assertEqual("write", failed.state.error.operation)
        self.assertEqual(0x2000, failed.state.error.address)
        self.assertEqual("access_error", failed.state.error.status.value)

    def test_zero_length_is_already_done_and_descriptor_checks_alignment(self) -> None:
        _, backend = self._engine(
            MemoryCopyDescriptor(0x1000, 0x2000, 0, 4)
        )
        state = backend.initial_state()
        self.assertTrue(state.done)
        self.assertEqual((), backend.advance(state).emissions)
        self.assertTrue(backend.is_quiescent(state))

        with self.assertRaisesRegex(ValueError, "beat-aligned"):
            MemoryCopyDescriptor(0x1001, 0x2000, 4, 4)
        with self.assertRaisesRegex(ValueError, "whole number of beats"):
            MemoryCopyDescriptor(0x1000, 0x2000, 6, 4)
        with self.assertRaisesRegex(ValueError, "source stride"):
            MemoryCopyDescriptor(
                0x1000, 0x2000, 4, 4, source_stride=2
            )

    def test_amba_recipe_reuses_each_serialized_requester_attachment(self) -> None:
        descriptor = MemoryCopyDescriptor(0x1000, 0x2000, 4, 4)
        expected = (
            (build_axi4_interface(), "manager", "AR"),
            (build_axi4_lite_interface(), "manager", "AR"),
            (build_ahb_lite_interface(), "manager", "READ"),
            (build_apb4_interface(), "requester", "READ"),
        )

        for protocol, role, first_kind in expected:
            with self.subTest(protocol=protocol.name):
                dut = build_amba_serialized_memory_copy_vdut(
                    "dma", protocol, descriptor
                )
                backend = dut.backend
                assert isinstance(backend, SerializedMemoryCopyBackend)
                issued = backend.advance(backend.initial_state())
                self.assertIsNone(issued.fault)
                self.assertEqual(role, dut.port("bus").role)
                self.assertEqual(first_kind, issued.emissions[0].event.kind)

    def test_recipe_rejects_descriptor_geometry_before_runtime(self) -> None:
        with self.assertRaisesRegex(ValueError, "beat size must equal"):
            build_amba_serialized_memory_copy_vdut(
                "dma",
                build_apb4_interface(Apb4Config(data_width=32)),
                MemoryCopyDescriptor(0x1000, 0x2000, 1, 1),
            )

        with self.assertRaisesRegex(ValueError, "source range exceeds"):
            build_amba_serialized_memory_copy_vdut(
                "dma",
                build_axi4_lite_interface(Axi4LiteConfig(address_width=12)),
                MemoryCopyDescriptor(0xFFC, 0, 8, 4),
            )


if __name__ == "__main__":
    unittest.main()
