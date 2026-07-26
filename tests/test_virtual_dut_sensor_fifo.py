from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints.sensor_fifo import (
    build_amba_sensor_fifo_vdut,
)
from protocol_model.protocols.amba.ahb.ahb_lite import build_ahb_lite_interface
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.axi.axi4 import build_axi4_interface
from protocol_model.protocols.amba.axi.axi4_lite import (
    Axi4LiteConfig,
    build_axi4_lite_interface,
)
from protocol_model.semantics import CanonicalEvent
from protocol_model.virtual_dut.backend.sensor_fifo import (
    SensorEmptyPolicy,
    SensorFifoBackend,
    SensorFifoConfig,
    SensorFullPolicy,
    incrementing_sample_policy,
)
from protocol_model.virtual_dut.backend.transition import PortInput


class SensorFifoTest(unittest.TestCase):
    @staticmethod
    def _sensor(
        *,
        capacity: int = 2,
        empty_policy=SensorEmptyPolicy.BLOCK,
        full_policy=SensorFullPolicy.DROP_NEWEST,
    ):
        dut = build_amba_sensor_fifo_vdut(
            "sensor",
            build_axi4_lite_interface(),
            SensorFifoConfig(
                0x1000,
                4,
                capacity,
                empty_policy=empty_policy,
                full_policy=full_policy,
            ),
            incrementing_sample_policy(start=0x10),
            port_name="axi",
        )
        backend = dut.backend
        assert isinstance(backend, SensorFifoBackend)
        return dut, backend

    @staticmethod
    def _read(address: int = 0x1000) -> PortInput:
        return PortInput(
            "axi",
            CanonicalEvent("AR", None, {"addr": address, "prot": 0}),
        )

    def test_service_produces_fifo_samples_and_data_read_pops_oldest(self) -> None:
        dut, backend = self._sensor()
        generated = backend.advance(backend.initial_state(), steps=2)

        self.assertIsNone(generated.fault)
        self.assertEqual("subordinate", dut.port("axi").role)
        self.assertEqual((0x10, 0x11), generated.state.samples)
        self.assertEqual((2, 2), backend.queue_usage(generated.state))

        first = backend.accept(generated.state, self._read())
        self.assertIsNone(first.fault)
        self.assertEqual(("R",), tuple(
            item.event.kind for item in first.emissions
        ))
        self.assertEqual(0x10, first.emissions[0].event.payload["data"])
        self.assertEqual((0x11,), first.state.samples)
        self.assertEqual(1, first.state.samples_read)

        second = backend.accept(first.state, self._read())
        self.assertEqual(0x11, second.emissions[0].event.payload["data"])
        empty = backend.accept(second.state, self._read())
        self.assertIsNone(empty.fault)
        self.assertIsNotNone(empty.blocked)
        self.assertIs(empty.state, second.state)
        self.assertEqual("sensor_fifo.sample_available", empty.blocked.resource)
        self.assertEqual((), empty.emissions)

    def test_drop_newest_counts_overrun_and_preserves_oldest_sample(self) -> None:
        _, backend = self._sensor(capacity=1)
        first = backend.advance(backend.initial_state())
        dropped = backend.advance(first.state)

        self.assertIsNone(dropped.fault)
        self.assertIsNone(dropped.blocked)
        self.assertEqual((0x10,), dropped.state.samples)
        self.assertEqual(2, dropped.state.service_index)
        self.assertEqual(1, dropped.state.accepted_samples)
        self.assertEqual(1, dropped.state.overrun_count)

        read = backend.accept(dropped.state, self._read())
        next_sample = backend.advance(read.state)
        self.assertEqual((0x12,), next_sample.state.samples)
        self.assertEqual(1, next_sample.state.overrun_count)

    def test_full_block_rejects_service_without_recording_overrun(self) -> None:
        _, backend = self._sensor(
            capacity=1, full_policy=SensorFullPolicy.BLOCK
        )
        full = backend.advance(backend.initial_state())
        blocked = backend.advance(full.state)

        self.assertIsNone(blocked.fault)
        self.assertIsNotNone(blocked.blocked)
        self.assertIs(blocked.state, full.state)
        self.assertEqual("sensor_fifo.free_slot", blocked.blocked.resource)
        self.assertEqual(1, blocked.state.service_index)
        self.assertEqual(0, blocked.state.overrun_count)

    def test_empty_access_error_returns_protocol_completion(self) -> None:
        _, backend = self._sensor(
            empty_policy=SensorEmptyPolicy.ACCESS_ERROR
        )
        completed = backend.accept(backend.initial_state(), self._read())

        self.assertIsNone(completed.fault)
        self.assertIsNone(completed.blocked)
        self.assertEqual(("R",), tuple(
            item.event.kind for item in completed.emissions
        ))
        self.assertEqual("SLVERR", completed.emissions[0].event.payload["resp"])
        self.assertEqual(0, completed.state.samples_read)

    def test_integration_recipe_supports_lite_ahb_apb_but_not_full_axi(self) -> None:
        config = SensorFifoConfig(0x1000, 4, 2)
        policy = incrementing_sample_policy()
        expected = (
            (build_axi4_lite_interface(), "subordinate"),
            (build_ahb_lite_interface(), "subordinate"),
            (build_apb4_interface(), "completer"),
        )
        for protocol, role in expected:
            with self.subTest(protocol=protocol.name):
                dut = build_amba_sensor_fifo_vdut(
                    "sensor", protocol, config, policy
                )
                self.assertEqual(role, dut.port("bus").role)
                self.assertIsInstance(dut.backend, SensorFifoBackend)

        with self.assertRaisesRegex(ValueError, "full AXI4"):
            build_amba_sensor_fifo_vdut(
                "sensor", build_axi4_interface(), config, policy
            )

        with self.assertRaisesRegex(ValueError, "exceeds.*address space"):
            build_amba_sensor_fifo_vdut(
                "sensor",
                build_axi4_lite_interface(Axi4LiteConfig(address_width=12)),
                SensorFifoConfig(0x1000, 4, 2),
                policy,
            )


if __name__ == "__main__":
    unittest.main()
