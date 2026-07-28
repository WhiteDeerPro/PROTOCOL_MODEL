from __future__ import annotations

import unittest

from protocol_model.integrations.recipes.amba.bridges.axi4_ahb import (
    build_axi4_to_ahb_lite_bridge_vdut,
)
from protocol_model.integrations.recipes.amba.bridges.serial_burst import (
    build_amba_serial_burst_bridge_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.ahb import (
    build_ahb_address_space_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.apb import (
    build_apb_address_space_vdut,
)
from protocol_model.integrations.attachments.amba.axi.axi4 import (
    Axi4BurstAssemblyProfile,
    Axi4BurstTranslationAttachment,
)
from protocol_model.protocols.amba.ahb.ahb_lite import build_ahb_lite_interface
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.axi.axi4 import Axi4Config, build_axi4_interface
from protocol_model.semantics import CanonicalEvent
from protocol_model.system import (
    InterfaceConnection,
    SystemAction,
    SystemProtocol,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AccessStatus,
    AddressRead,
)
from protocol_model.virtual_dut.address.burst import (
    AddressBurst,
    AddressBurstResult,
)
from protocol_model.virtual_dut.address.memory import MemoryRegion
from protocol_model.virtual_dut.address.space import AddressSpace
from protocol_model.virtual_dut.backend.simple import CaptureBackend
from protocol_model.virtual_dut.boundary.module import VirtualDut
from protocol_model.virtual_dut.boundary.port import InterfacePort
from protocol_model.virtual_dut.fabric.route import AddressRoute
from protocol_model.virtual_dut.translation.address_burst import (
    BurstToAccessStage,
)


def _axi_address(
    kind: str,
    *,
    key: int,
    address: int,
    length: int,
    prot: int = 0,
) -> CanonicalEvent:
    return CanonicalEvent(
        kind,
        key,
        {
            "addr": address,
            "len": length,
            "size": 2,
            "burst": "INCR",
            "lock": 0,
            "cache": 0,
            "prot": prot,
            "qos": 0,
            "region": 0,
        },
    )


class BurstToAccessStageTest(unittest.TestCase):
    def test_children_and_results_keep_beat_order(self) -> None:
        burst = AddressBurst(
            (
                AddressRead(0x1000, 4),
                AddressRead(0x1004, 4),
                AddressRead(0x1008, 4),
            )
        )
        stage = BurstToAccessStage()
        beginning = stage.begin(burst)

        self.assertEqual(3, beginning.count)
        self.assertEqual(
            burst.accesses,
            tuple(stage.child_at(beginning.context, i) for i in range(3)),
        )
        folded = beginning.fold_state
        expected = (
            AccessResult(data=0x11),
            AccessResult(status=AccessStatus.ACCESS_ERROR),
            AccessResult(data=0x33),
        )
        for index, result in enumerate(expected):
            folded = stage.fold_one(
                beginning.context, folded, index, result
            )
        self.assertEqual(
            AddressBurstResult(expected),
            stage.finish(beginning.context, folded),
        )

    def test_axi_ingress_fragment_capacity_is_distinct_from_parent_capacity(
        self,
    ) -> None:
        protocol = build_axi4_interface(Axi4Config(data_width=32, id_width=4))
        attachment = Axi4BurstTranslationAttachment(
            protocol,
            assembly_profile=Axi4BurstAssemblyProfile(max_pending_aw=1),
        )
        initial = attachment.initial_state()
        first = attachment.decode_operation(
            initial,
            _axi_address("AW", key=1, address=0x8000, length=0),
        )
        overflow = attachment.decode_operation(
            first.state,
            _axi_address("AW", key=2, address=0x8004, length=0),
        )

        self.assertIsNone(first.fault)
        self.assertIsNotNone(overflow.fault)
        self.assertEqual(
            "axi4_burst_translation.pending_aw_capacity",
            overflow.fault.rule,
        )
        self.assertEqual(first.state, overflow.state)


class Axi4ToAhbLiteBridgeTest(unittest.TestCase):
    @staticmethod
    def _system(
        *, route_size: int = 0x100, capture_ahb: bool = False
    ) -> SystemProtocol:
        axi = build_axi4_interface(Axi4Config(data_width=32, id_width=4))
        ahb = build_ahb_lite_interface()
        manager = VirtualDut(
            "manager",
            {"axi": InterfacePort("axi", axi, "manager")},
            backend=CaptureBackend(),
        )
        bridge = build_axi4_to_ahb_lite_bridge_vdut(
            "bridge",
            axi,
            ahb,
            (
                AddressRoute(
                    "memory",
                    0x8000,
                    route_size,
                    "m_ahb",
                    output_base_address=0x1000,
                ),
            ),
        )
        if capture_ahb:
            memory = VirtualDut(
                "memory",
                {"ahb": InterfacePort("ahb", ahb, "subordinate")},
                backend=CaptureBackend(),
            )
        else:
            memory = build_ahb_address_space_vdut(
                "memory",
                ahb,
                AddressSpace(
                    (
                        MemoryRegion(
                            "ram",
                            0x100,
                            base_address=0x1000,
                            initial_content=bytes.fromhex(
                                "112233445566778899aabbcc"
                            ),
                        ),
                    )
                ),
            )
        return SystemProtocol(
            "axi4_to_ahb_lite",
            {item.name: item for item in (manager, bridge, memory)},
            {
                "axi": InterfaceConnection(
                    "axi",
                    axi,
                    {
                        "manager": VirtualDutPortRef("manager", "axi"),
                        "subordinate": VirtualDutPortRef("bridge", "s_axi"),
                    },
                ),
                "ahb": InterfaceConnection(
                    "ahb",
                    ahb,
                    {
                        "manager": VirtualDutPortRef("bridge", "m_ahb"),
                        "subordinate": VirtualDutPortRef("memory", "ahb"),
                    },
                ),
            },
        )

    @staticmethod
    def _action(event: CanonicalEvent) -> SystemAction:
        return SystemAction(VirtualDutPortRef("manager", "axi"), event)

    def test_incr_read_becomes_ordered_ahb_single_transfers(self) -> None:
        session = self._system().open_session()
        transition = session.step(
            session.initial_state(),
            self._action(
                _axi_address(
                    "AR", key=5, address=0x8000, length=2, prot=0b101
                )
            ),
        )

        self.assertIsNone(transition.fault)
        ahb_requests = tuple(
            item.event
            for item in transition.emissions
            if item.connection == "ahb" and item.event.kind == "READ"
        )
        self.assertEqual(
            (0x1000, 0x1004, 0x1008),
            tuple(event.payload["addr"] for event in ahb_requests),
        )
        self.assertEqual(
            (("SINGLE", "NONSEQ"),) * 3,
            tuple(
                (event.payload["burst"], event.payload["trans"])
                for event in ahb_requests
            ),
        )
        self.assertEqual(
            (0b0010, 0b0010, 0b0010),
            tuple(event.payload["prot"] for event in ahb_requests),
        )

        responses = tuple(
            item.event
            for item in transition.emissions
            if item.connection == "axi" and item.event.kind == "R"
        )
        self.assertEqual((5, 5, 5), tuple(event.key for event in responses))
        self.assertEqual(
            (0x44332211, 0x88776655, 0xCCBBAA99),
            tuple(event.payload["data"] for event in responses),
        )
        self.assertEqual(
            (False, False, True),
            tuple(event.payload["last"] for event in responses),
        )
        self.assertTrue(session.is_quiescent(transition.state))

    def test_route_miss_folds_local_decerr_without_ahb_traffic(self) -> None:
        session = self._system().open_session()
        transition = session.step(
            session.initial_state(),
            self._action(
                _axi_address("AR", key=7, address=0x9000, length=1)
            ),
        )

        self.assertIsNone(transition.fault)
        self.assertFalse(
            any(item.connection == "ahb" for item in transition.emissions)
        )
        responses = tuple(
            item.event
            for item in transition.emissions
            if item.event.kind == "R"
        )
        self.assertEqual(
            ("DECERR", "DECERR"),
            tuple(event.payload["resp"] for event in responses),
        )
        self.assertEqual(
            (False, True), tuple(event.payload["last"] for event in responses)
        )
        self.assertTrue(session.is_quiescent(transition.state))

    def test_burst_route_is_preflighted_before_the_first_child(self) -> None:
        session = self._system(route_size=8).open_session()
        transition = session.step(
            session.initial_state(),
            self._action(
                _axi_address("AR", key=8, address=0x8004, length=1)
            ),
        )

        self.assertIsNone(transition.fault)
        self.assertFalse(
            any(item.connection == "ahb" for item in transition.emissions)
        )
        responses = tuple(
            item.event
            for item in transition.emissions
            if item.event.kind == "R"
        )
        self.assertEqual(2, len(responses))
        self.assertEqual(
            ("DECERR", "DECERR"),
            tuple(event.payload["resp"] for event in responses),
        )

    def test_two_beat_write_folds_ahb_error_into_one_axi_b(self) -> None:
        session = self._system(capture_ahb=True).open_session()
        address = session.step(
            session.initial_state(),
            self._action(
                _axi_address("AW", key=9, address=0x8000, length=1)
            ),
        )
        first_data = session.step(
            address.state,
            self._action(
                CanonicalEvent(
                    "W",
                    None,
                    {
                        "data": 0xAABBCCDD,
                        "strb": 0b1111,
                        "last": False,
                    },
                )
            ),
        )
        issued = session.step(
            first_data.state,
            self._action(
                CanonicalEvent(
                    "W",
                    None,
                    {
                        "data": 0x11223344,
                        "strb": 0b1111,
                        "last": True,
                    },
                )
            ),
        )

        for transition in (address, first_data, issued):
            self.assertIsNone(transition.fault)
        first_writes = tuple(
            item.event
            for item in issued.emissions
            if item.connection == "ahb" and item.event.kind == "WRITE"
        )
        self.assertEqual((0x1000,), tuple(
            event.payload["addr"] for event in first_writes
        ))

        first_completion = session.step(
            issued.state,
            SystemAction(
                VirtualDutPortRef("memory", "ahb"),
                CanonicalEvent("WRITE_RESPONSE", None, {"resp": "OKAY"}),
            ),
        )
        second_writes = tuple(
            item.event
            for item in first_completion.emissions
            if item.connection == "ahb" and item.event.kind == "WRITE"
        )
        self.assertIsNone(first_completion.fault)
        self.assertEqual((0x1004,), tuple(
            event.payload["addr"] for event in second_writes
        ))

        completed = session.step(
            first_completion.state,
            SystemAction(
                VirtualDutPortRef("memory", "ahb"),
                CanonicalEvent("WRITE_RESPONSE", None, {"resp": "ERROR"}),
            ),
        )
        self.assertIsNone(completed.fault)
        responses = tuple(
            item.event
            for item in completed.emissions
            if item.connection == "axi" and item.event.kind == "B"
        )
        self.assertEqual(1, len(responses))
        self.assertEqual(9, responses[0].key)
        self.assertEqual("SLVERR", responses[0].payload["resp"])
        self.assertTrue(session.is_quiescent(completed.state))

    def test_sparse_later_write_beat_is_rejected_before_any_ahb_effect(
        self,
    ) -> None:
        session = self._system(capture_ahb=True).open_session()
        address = session.step(
            session.initial_state(),
            self._action(
                _axi_address("AW", key=10, address=0x8000, length=1)
            ),
        )
        first_data = session.step(
            address.state,
            self._action(
                CanonicalEvent(
                    "W",
                    None,
                    {"data": 0xAABBCCDD, "strb": 0b1111, "last": False},
                )
            ),
        )
        completed = session.step(
            first_data.state,
            self._action(
                CanonicalEvent(
                    "W",
                    None,
                    {"data": 0x11223344, "strb": 0b0101, "last": True},
                )
            ),
        )

        self.assertIsNone(completed.fault)
        self.assertFalse(
            any(item.connection == "ahb" for item in completed.emissions)
        )
        response = next(
            item.event
            for item in completed.emissions
            if item.event.kind == "B"
        )
        self.assertEqual("SLVERR", response.payload["resp"])
        self.assertTrue(session.is_quiescent(completed.state))

    def test_same_burst_root_executes_against_apb4(self) -> None:
        axi = build_axi4_interface(Axi4Config(data_width=32, id_width=4))
        apb = build_apb4_interface()
        manager = VirtualDut(
            "manager",
            {"axi": InterfacePort("axi", axi, "manager")},
            backend=CaptureBackend(),
        )
        bridge = build_amba_serial_burst_bridge_vdut(
            "bridge",
            axi,
            apb,
            (
                AddressRoute(
                    "memory",
                    0x8000,
                    0x100,
                    "m_apb",
                    output_base_address=0x1000,
                ),
            ),
            ingress_port="s_axi",
            egress_port="m_apb",
        )
        memory = build_apb_address_space_vdut(
            "memory",
            apb,
            AddressSpace(
                (
                    MemoryRegion(
                        "ram",
                        8,
                        base_address=0x1000,
                        initial_content=bytes.fromhex("1122334455667788"),
                    ),
                )
            ),
        )
        system = SystemProtocol(
            "axi4_to_apb4",
            {item.name: item for item in (manager, bridge, memory)},
            {
                "axi": InterfaceConnection(
                    "axi",
                    axi,
                    {
                        "manager": VirtualDutPortRef("manager", "axi"),
                        "subordinate": VirtualDutPortRef("bridge", "s_axi"),
                    },
                ),
                "apb": InterfaceConnection(
                    "apb",
                    apb,
                    {
                        "requester": VirtualDutPortRef("bridge", "m_apb"),
                        "completer": VirtualDutPortRef("memory", "apb"),
                    },
                ),
            },
        )
        session = system.open_session()
        transition = session.step(
            session.initial_state(),
            self._action(
                _axi_address("AR", key=11, address=0x8000, length=1)
            ),
        )

        self.assertIsNone(transition.fault)
        self.assertEqual(
            (0x1000, 0x1004),
            tuple(
                item.event.payload["addr"]
                for item in transition.emissions
                if item.connection == "apb" and item.event.kind == "READ"
            ),
        )
        self.assertEqual(
            (0x44332211, 0x88776655),
            tuple(
                item.event.payload["data"]
                for item in transition.emissions
                if item.connection == "axi" and item.event.kind == "R"
            ),
        )
        self.assertTrue(session.is_quiescent(transition.state))


if __name__ == "__main__":
    unittest.main()
