from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.endpoints.memory_copy import (
    build_amba_serialized_memory_copy_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.queued import (
    build_amba_queued_address_responder_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.sensor_fifo import (
    build_amba_sensor_fifo_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics.axi4_lite_crossbar import (
    build_axi4_lite_address_crossbar_vdut,
)
from protocol_model.protocols.amba.axi.axi4_lite import build_axi4_lite_interface
from protocol_model.system import (
    AddressClaim,
    AddressRouterContract,
    AddressWindow,
    DutAdvanceAction,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address.access import AddressRead
from protocol_model.virtual_dut.address.memory import MemoryRegion
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.backend.memory_copy import (
    MemoryCopyDescriptor,
    SerializedMemoryCopyState,
)
from protocol_model.virtual_dut.backend.queued_address import (
    QueuedAddressResponderState,
    constant_address_delay,
)
from protocol_model.virtual_dut.backend.sensor_fifo import (
    SensorFifoConfig,
    SensorFifoState,
    SensorFullPolicy,
    incrementing_sample_policy,
)
from protocol_model.virtual_dut.fabric.route import AddressRoute


class SensorDmaSystemTest(unittest.TestCase):
    SAMPLE_BASE = 0x10203040
    SOURCE_BASE = 0x1000
    DESTINATION_BASE = 0x2000
    BEAT_BYTES = 4

    def _system(self, *, copy_beats: int, sensor_capacity: int):
        protocol = build_axi4_lite_interface()
        descriptor = MemoryCopyDescriptor(
            self.SOURCE_BASE,
            self.DESTINATION_BASE,
            copy_beats * self.BEAT_BYTES,
            self.BEAT_BYTES,
            source_stride=0,
        )
        dma = build_amba_serialized_memory_copy_vdut(
            "dma", protocol, descriptor, port_name="axi"
        )
        sensor = build_amba_sensor_fifo_vdut(
            "sensor",
            protocol,
            SensorFifoConfig(
                0,
                self.BEAT_BYTES,
                sensor_capacity,
                full_policy=SensorFullPolicy.DROP_NEWEST,
            ),
            incrementing_sample_policy(start=self.SAMPLE_BASE),
            port_name="axi",
        )
        memory_space = AddressSpace((MemoryRegion("ram", 0x100),))
        memory = build_amba_queued_address_responder_vdut(
            "memory",
            protocol,
            memory_space,
            capacity=2,
            delay_policy=constant_address_delay(0),
            port_name="axi",
        )
        routes = (
            AddressRoute(
                "sensor_data",
                self.SOURCE_BASE,
                self.BEAT_BYTES,
                "m_sensor",
                output_base_address=0,
            ),
            AddressRoute(
                "memory",
                self.DESTINATION_BASE,
                0x100,
                "m_memory",
                output_base_address=0,
            ),
        )
        router = AddressRouterContract(
            "dma_router",
            "crossbar",
            ("s_dma",),
            ("m_sensor", "m_memory"),
            routes,
        )
        builder = SystemProtocolBuilder("sensor_dma_capture")
        for dut in (dma, sensor, memory):
            builder.add_dut(dut)
        builder.construct_address_router(
            router,
            lambda contract: build_axi4_lite_address_crossbar_vdut(
                contract.router,
                protocol,
                contract.ingress_ports,
                contract.egress_ports,
                contract.routes,
                ingress_queue_capacity=2,
            ),
        )
        builder.connect(
            "dma_bus",
            protocol,
            {
                "manager": VirtualDutPortRef("dma", "axi"),
                "subordinate": VirtualDutPortRef("crossbar", "s_dma"),
            },
        )
        builder.connect(
            "sensor_bus",
            protocol,
            {
                "manager": VirtualDutPortRef("crossbar", "m_sensor"),
                "subordinate": VirtualDutPortRef("sensor", "axi"),
            },
        )
        builder.connect(
            "memory_bus",
            protocol,
            {
                "manager": VirtualDutPortRef("crossbar", "m_memory"),
                "subordinate": VirtualDutPortRef("memory", "axi"),
            },
        )
        builder.add_address_claim(
            AddressClaim(
                "sensor_data_local",
                VirtualDutPortRef("sensor", "axi"),
                AddressWindow(0, self.BEAT_BYTES),
            )
        )
        builder.add_address_claim(
            AddressClaim(
                "memory_local",
                VirtualDutPortRef("memory", "axi"),
                AddressWindow(0, 0x100),
            )
        )
        return builder.build(), memory_space

    def _copy(self, system, *, sensor_service_steps: int, copy_beats: int):
        session = system.open_session()
        state = session.initial_state()
        produced = session.step(
            state,
            DutAdvanceAction("sensor", steps=sensor_service_steps),
        )
        self.assertIsNone(produced.fault)
        self.assertIsNone(produced.blocked)
        state = produced.state

        for _ in range(copy_beats):
            for dut in ("dma", "crossbar", "dma", "crossbar", "memory"):
                progressed = session.step(state, DutAdvanceAction(dut))
                self.assertIsNone(progressed.fault, dut)
                self.assertIsNone(progressed.blocked, dut)
                state = progressed.state
        return session, state

    def _memory_bytes(self, state, memory_space, length: int) -> bytes:
        memory_state = state.dut_states["memory"]
        self.assertIsInstance(memory_state, QueuedAddressResponderState)
        read = memory_space.access(
            memory_state.handler_state, AddressRead(0, length)
        )
        self.assertTrue(read.result.succeeded)
        assert read.result.data is not None
        return read.result.data.to_bytes(length, "little")

    def test_dma_moves_sensor_samples_through_crossbar_to_memory(self) -> None:
        copy_beats = 3
        system, memory_space = self._system(
            copy_beats=copy_beats, sensor_capacity=copy_beats
        )
        session, state = self._copy(
            system,
            sensor_service_steps=copy_beats,
            copy_beats=copy_beats,
        )

        expected = b"".join(
            (self.SAMPLE_BASE + index).to_bytes(4, "little")
            for index in range(copy_beats)
        )
        self.assertEqual(
            expected,
            self._memory_bytes(state, memory_space, len(expected)),
        )
        dma_state = state.dut_states["dma"]
        sensor_state = state.dut_states["sensor"]
        self.assertIsInstance(dma_state, SerializedMemoryCopyState)
        self.assertIsInstance(sensor_state, SensorFifoState)
        self.assertTrue(dma_state.done)
        self.assertEqual(len(expected), dma_state.bytes_copied)
        self.assertEqual((), sensor_state.samples)
        self.assertEqual(0, sensor_state.overrun_count)
        self.assertTrue(session.is_quiescent(state))

        trace = session.trace(state)
        self.assertEqual(
            {"dma_bus", "sensor_bus", "memory_bus"},
            {event.connection for event in trace.events},
        )
        self.assertEqual(
            copy_beats,
            sum(
                event.connection == "sensor_bus" and event.event.kind == "AR"
                for event in trace.events
            ),
        )
        self.assertEqual(
            copy_beats,
            sum(
                event.connection == "memory_bus" and event.event.kind == "B"
                for event in trace.events
            ),
        )
        first_beat_path = tuple(
            (event.connection, event.event.kind) for event in trace.events[:10]
        )
        self.assertEqual(
            (
                ("dma_bus", "AR"),
                ("sensor_bus", "AR"),
                ("sensor_bus", "R"),
                ("dma_bus", "R"),
                ("dma_bus", "AW"),
                ("dma_bus", "W"),
                ("memory_bus", "AW"),
                ("memory_bus", "W"),
                ("memory_bus", "B"),
                ("dma_bus", "B"),
            ),
            first_beat_path,
        )

    def test_fast_sensor_drops_new_samples_and_dma_copies_retained_fifo(self) -> None:
        copy_beats = 2
        system, memory_space = self._system(
            copy_beats=copy_beats, sensor_capacity=copy_beats
        )
        session, state = self._copy(
            system,
            sensor_service_steps=5,
            copy_beats=copy_beats,
        )

        sensor_state = state.dut_states["sensor"]
        self.assertIsInstance(sensor_state, SensorFifoState)
        self.assertEqual(3, sensor_state.overrun_count)
        self.assertEqual(5, sensor_state.service_index)
        expected = b"".join(
            (self.SAMPLE_BASE + index).to_bytes(4, "little")
            for index in range(copy_beats)
        )
        self.assertEqual(
            expected,
            self._memory_bytes(state, memory_space, len(expected)),
        )
        self.assertTrue(session.is_quiescent(state))

    def test_empty_sensor_blocks_crossbar_step_then_retries_after_sample(self) -> None:
        system, memory_space = self._system(
            copy_beats=1, sensor_capacity=1
        )
        session = system.open_session()
        initial = session.initial_state()
        read_queued = session.step(initial, DutAdvanceAction("dma"))
        self.assertIsNone(read_queued.fault)

        blocked = session.step(
            read_queued.state, DutAdvanceAction("crossbar")
        )
        self.assertIsNone(blocked.fault)
        self.assertIsNotNone(blocked.blocked)
        assert blocked.blocked is not None
        self.assertEqual(
            "sensor.sensor_fifo.sample_available",
            blocked.blocked.resource,
        )
        self.assertEqual("sensor.axi", blocked.blocked.location)
        self.assertIs(blocked.state, read_queued.state)
        self.assertEqual(
            read_queued.state.events,
            blocked.state.events,
        )

        sampled = session.step(
            blocked.state, DutAdvanceAction("sensor")
        )
        retried = session.step(
            sampled.state, DutAdvanceAction("crossbar")
        )
        self.assertIsNone(retried.blocked)
        self.assertEqual(
            ("AR", "R", "R"),
            tuple(item.event.kind for item in retried.emissions),
        )

        write_issued = session.step(
            retried.state, DutAdvanceAction("dma")
        )
        write_forwarded = session.step(
            write_issued.state, DutAdvanceAction("crossbar")
        )
        completed = session.step(
            write_forwarded.state, DutAdvanceAction("memory")
        )
        self.assertEqual(
            self.SAMPLE_BASE.to_bytes(4, "little"),
            self._memory_bytes(completed.state, memory_space, 4),
        )
        self.assertTrue(session.is_quiescent(completed.state))


if __name__ == "__main__":
    unittest.main()
