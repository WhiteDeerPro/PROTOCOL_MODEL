from __future__ import annotations

import unittest

from protocol_model.integrations.recipes import (
    ChiIssueHHomeVdutAssembly,
    attach_chi_issue_h_home,
    bind_chi_issue_h_home_vdut,
)
from protocol_model.protocols.amba.apb.apb4 import build_apb4_interface
from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiFacetKind,
    ChiHomeDirectoryEntry,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
)
from protocol_model.system import SystemProtocolBuilder
from protocol_model.virtual_dut.backend import (
    BackingLine,
    FullLineBackingCore,
    NoOpBackend,
)
from protocol_model.virtual_dut.boundary import (
    DutBehaviorTag,
    InterfacePort,
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class ChiIssueHHomeVdutRecipeTest(unittest.TestCase):
    HOME = 0x21
    ADDRESS = 0x8000
    DATA = (1 << 400) | 0xC0DE

    def backing_core(self, name: str = "hn0.backing") -> FullLineBackingCore:
        return FullLineBackingCore(
            name,
            line_bytes=64,
            initial_lines=(BackingLine(self.ADDRESS, self.DATA),),
        )

    @staticmethod
    def port(
        name: str,
        direction: TransportDirection,
        *,
        family: str = CHI_ISSUE_H_TRANSPORT_FAMILY,
    ) -> TransportPort:
        return TransportPort(name, family, direction)

    def directory(self) -> tuple[ChiHomeDirectoryEntry, ...]:
        return (ChiHomeDirectoryEntry(self.ADDRESS),)

    def test_attachment_creates_first_home_vdut_around_backing_core(
        self,
    ) -> None:
        core = self.backing_core()

        def retry_policy(request, state):
            return 5

        assembly = attach_chi_issue_h_home(
            "hn0",
            core,
            self.HOME,
            initial_directory=self.directory(),
            transaction_capacity=3,
            initial_snoop_transaction_id=0x120,
            initial_data_buffer_id=0x220,
            allow_dirty_data_transfer=True,
            default_protocol_credit_type=5,
            retry_policy=retry_policy,
            clock_domain="chi_clk",
            reset_domain="chi_reset",
        )

        self.assertIsInstance(assembly, ChiIssueHHomeVdutAssembly)
        self.assertIs(core, assembly.backing_core)
        self.assertIs(core, assembly.participant.backing_core)
        self.assertIs(assembly.virtual_dut, assembly.facets.dut)
        self.assertIs(assembly.virtual_dut, assembly.binding.dut)
        self.assertIs(assembly.participant, assembly.binding.component)
        self.assertIs(
            ChiFacetKind.TRANSACTION,
            assembly.facets.facets[0].kind,
        )
        self.assertEqual(frozenset((self.HOME,)), assembly.binding.node_ids)
        self.assertEqual(3, assembly.participant.transaction_capacity)
        self.assertEqual(
            0x120,
            assembly.participant.initial_snoop_transaction_id,
        )
        self.assertEqual(
            0x220,
            assembly.participant.initial_data_buffer_id,
        )
        self.assertTrue(assembly.participant.allow_dirty_data_transfer)
        self.assertEqual(
            5,
            assembly.participant.default_protocol_credit_type,
        )
        self.assertIs(retry_policy, assembly.participant.retry_policy)

        dut = assembly.virtual_dut
        self.assertEqual(
            frozenset(
                (
                    DutBehaviorTag.ADDRESSABLE,
                    DutBehaviorTag.INITIATING,
                )
            ),
            dut.behavior_tags,
        )
        tx = dut.port("chi_tx")
        rx = dut.port("chi_rx")
        self.assertIs(TransportDirection.TRANSMIT, tx.direction)
        self.assertIs(TransportDirection.RECEIVE, rx.direction)
        self.assertEqual("chi_clk", tx.clock_domain)
        self.assertEqual("chi_reset", rx.reset_domain)
        for channel in (
            ChiChannelKind.RSP,
            ChiChannelKind.SNP,
            ChiChannelKind.DAT,
        ):
            self.assertEqual(
                (tx,),
                assembly.binding.ports_for(
                    channel,
                    TransportDirection.TRANSMIT,
                ),
            )
        for channel in (
            ChiChannelKind.REQ,
            ChiChannelKind.RSP,
            ChiChannelKind.DAT,
        ):
            self.assertEqual(
                (rx,),
                assembly.binding.ports_for(
                    channel,
                    TransportDirection.RECEIVE,
                ),
            )
        self.assertEqual(
            (),
            assembly.binding.ports_for(
                ChiChannelKind.REQ,
                TransportDirection.TRANSMIT,
            ),
        )
        self.assertEqual(
            (),
            assembly.binding.ports_for(
                ChiChannelKind.SNP,
                TransportDirection.RECEIVE,
            ),
        )

    def test_binder_reuses_one_canonical_virtual_dut(self) -> None:
        tx = self.port("tx_rsp_snp_dat", TransportDirection.TRANSMIT)
        rx = self.port("rx_req_rsp_dat", TransportDirection.RECEIVE)
        dut = VirtualDut("hn0", {tx.name: tx, rx.name: rx})
        core = self.backing_core()

        assembly = bind_chi_issue_h_home_vdut(
            dut,
            core,
            self.HOME,
            port_channels={
                tx.name: frozenset(
                    (
                        ChiChannelKind.RSP,
                        ChiChannelKind.SNP,
                        ChiChannelKind.DAT,
                    )
                ),
                rx.name: frozenset(
                    (
                        ChiChannelKind.REQ,
                        ChiChannelKind.RSP,
                        ChiChannelKind.DAT,
                    )
                ),
            },
            initial_directory=self.directory(),
            participant_name="home",
            binding_name="hn0",
        )
        system = SystemProtocolBuilder("canonical_home").add_dut(dut).build()

        self.assertIs(dut, assembly.virtual_dut)
        self.assertIs(dut, assembly.facets.dut)
        self.assertIs(dut, assembly.binding.dut)
        self.assertIs(dut, system.virtual_duts["hn0"])
        self.assertIs(core, assembly.backing_core)
        self.assertIs(core, assembly.participant.backing_core)
        self.assertEqual("home", assembly.participant.name)
        self.assertEqual("hn0", assembly.binding.name)
        self.assertIs(tx, assembly.binding.ports[0].port)
        self.assertIs(rx, assembly.binding.ports[1].port)

    def test_binder_rejects_non_home_channel_directions(self) -> None:
        tx = self.port("tx", TransportDirection.TRANSMIT)
        rx = self.port("rx", TransportDirection.RECEIVE)
        dut = VirtualDut("hn0", {tx.name: tx, rx.name: rx})
        core = self.backing_core()

        with self.subTest("reference-backing Home does not transmit REQ"):
            with self.assertRaisesRegex(ValueError, "cannot transmit REQ"):
                bind_chi_issue_h_home_vdut(
                    dut,
                    core,
                    self.HOME,
                    port_channels={
                        tx.name: frozenset((ChiChannelKind.REQ,))
                    },
                    initial_directory=self.directory(),
                )
        with self.subTest("reference-backing Home does not receive SNP"):
            with self.assertRaisesRegex(ValueError, "cannot receive SNP"):
                bind_chi_issue_h_home_vdut(
                    dut,
                    core,
                    self.HOME,
                    port_channels={
                        rx.name: frozenset((ChiChannelKind.SNP,))
                    },
                    initial_directory=self.directory(),
                )

    def test_binder_rejects_invalid_transport_boundaries(self) -> None:
        core = self.backing_core()
        rx = self.port("rx", TransportDirection.RECEIVE)

        with self.subTest("unknown port"):
            with self.assertRaisesRegex(ValueError, "unknown ports"):
                bind_chi_issue_h_home_vdut(
                    VirtualDut("hn0", {rx.name: rx}),
                    core,
                    self.HOME,
                    port_channels={
                        "missing": frozenset((ChiChannelKind.REQ,))
                    },
                    initial_directory=self.directory(),
                )
        with self.subTest("another transport family"):
            other = self.port(
                "rx",
                TransportDirection.RECEIVE,
                family="another-transport",
            )
            with self.assertRaisesRegex(
                ValueError,
                "another transport family",
            ):
                bind_chi_issue_h_home_vdut(
                    VirtualDut("hn0", {other.name: other}),
                    core,
                    self.HOME,
                    port_channels={
                        other.name: frozenset((ChiChannelKind.REQ,))
                    },
                    initial_directory=self.directory(),
                )
        with self.subTest("non-transport port"):
            protocol = build_apb4_interface()
            interface_port = InterfacePort(
                "apb",
                protocol,
                "completer",
            )
            with self.assertRaisesRegex(TypeError, "not a TransportPort"):
                bind_chi_issue_h_home_vdut(
                    VirtualDut("hn0", {"apb": interface_port}),
                    core,
                    self.HOME,
                    port_channels={
                        "apb": frozenset((ChiChannelKind.REQ,))
                    },
                    initial_directory=self.directory(),
                )

    def test_binder_rejects_an_independent_executable_backend(self) -> None:
        rx = self.port("rx", TransportDirection.RECEIVE)
        dut = VirtualDut(
            "hn0",
            {rx.name: rx},
            backend=NoOpBackend(),
        )

        with self.assertRaisesRegex(
            ValueError,
            "without an executable backend",
        ):
            bind_chi_issue_h_home_vdut(
                dut,
                self.backing_core(),
                self.HOME,
                port_channels={
                    rx.name: frozenset((ChiChannelKind.REQ,))
                },
                initial_directory=self.directory(),
            )

    def test_attachment_requires_distinct_directional_port_names(self) -> None:
        with self.assertRaisesRegex(ValueError, "distinct"):
            attach_chi_issue_h_home(
                "hn0",
                self.backing_core(),
                self.HOME,
                initial_directory=self.directory(),
                transmit_port_name="chi",
                receive_port_name="chi",
            )

    def test_home_construction_closes_directory_against_backing(self) -> None:
        with self.subTest("CHI line geometry"):
            narrow = FullLineBackingCore(
                "narrow",
                line_bytes=32,
                initial_lines=(BackingLine(self.ADDRESS, 0xC0DE),),
            )
            with self.assertRaisesRegex(ValueError, "64-byte backing"):
                attach_chi_issue_h_home(
                    "hn0",
                    narrow,
                    self.HOME,
                    initial_directory=self.directory(),
                )
        with self.subTest("directory line must exist in backing"):
            with self.assertRaisesRegex(
                ValueError,
                "matching backing lines",
            ):
                attach_chi_issue_h_home(
                    "hn0",
                    self.backing_core(),
                    self.HOME,
                    initial_directory=(
                        ChiHomeDirectoryEntry(self.ADDRESS + 0x40),
                    ),
                )


if __name__ == "__main__":
    unittest.main()
