from __future__ import annotations

import unittest

from protocol_model.protocols.amba.chi.issue_h.participants import (
    ChiBehaviorFacet,
    ChiFacetKind,
    ChiParticipantBinding,
    ChiParticipantPortBinding,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (
    ChiChannelKind,
)
from protocol_model.protocols.amba.chi.issue_h.system import (
    ChiCoherenceAuthorityContract,
    ChiCoherenceDomain,
    ChiHomeAuthority,
    ChiResolvedCoherenceAuthorityPlan,
    ChiResolvedCoherenceDomain,
    resolve_chi_coherence_authority,
    resolve_chi_node_identities,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (
    CHI_ISSUE_H_TRANSPORT_FAMILY,
)
from protocol_model.semantics import SemanticComponent, SemanticStep
from protocol_model.system import (
    AddressClaim,
    AddressWindow,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.boundary import (
    TransportDirection,
    TransportPort,
    VirtualDut,
)


class _ParticipantComponent(SemanticComponent[object, None, object]):
    """Minimal behavior object: these tests exercise construction, not runtime."""

    def __init__(self, name: str) -> None:
        self.name = name

    def initial_state(self) -> None:
        return None

    def step(
        self,
        state: None,
        action: object,
    ) -> SemanticStep[None, object]:
        return SemanticStep(state)


class ChiIssueHCoherenceAuthorityTest(unittest.TestCase):
    WINDOW = AddressWindow(0x1000, 0x100)

    @staticmethod
    def _port(name: str) -> TransportPort:
        return TransportPort(
            name,
            CHI_ISSUE_H_TRANSPORT_FAMILY,
            TransportDirection.RECEIVE,
        )

    def _inputs(
        self,
        *,
        nodes: dict[str, tuple[str, ...]] | None = None,
        claims: tuple[
            tuple[str, str, str, AddressWindow],
            ...,
        ]
        | None = None,
        facet_specs: tuple[
            tuple[
                str,
                str,
                ChiFacetKind,
                frozenset[int],
                frozenset[str] | None,
            ],
            ...,
        ]
        | None = None,
    ):
        node_ports = nodes or {
            "rn0": ("link",),
            "rn1": ("link",),
            "hn0": ("home",),
        }
        claim_specs = (
            (("memory", "hn0", "home", self.WINDOW),)
            if claims is None
            else claims
        )
        specs = facet_specs or (
            (
                "rn0",
                "rn0",
                ChiFacetKind.TRANSACTION,
                frozenset((0x10,)),
                None,
            ),
            (
                "rn1",
                "rn1",
                ChiFacetKind.TRANSACTION,
                frozenset((0x11,)),
                None,
            ),
            (
                "hn0",
                "hn0",
                ChiFacetKind.TRANSACTION,
                frozenset((0x20,)),
                None,
            ),
        )

        builder = SystemProtocolBuilder("coherence_authority")
        duts: dict[str, VirtualDut] = {}
        for dut_name, port_names in node_ports.items():
            dut = VirtualDut(
                dut_name,
                {name: self._port(name) for name in port_names},
            )
            duts[dut_name] = dut
            builder.add_dut(dut)
            for port_name in port_names:
                builder.expose(
                    f"{dut_name}_{port_name}",
                    VirtualDutPortRef(dut_name, port_name),
                )
        for claim_name, dut_name, port_name, window in claim_specs:
            builder.add_address_claim(
                AddressClaim(
                    claim_name,
                    VirtualDutPortRef(dut_name, port_name),
                    window,
                )
            )
        system = builder.build().elaborate()

        facets: list[ChiBehaviorFacet] = []
        for name, dut_name, kind, node_ids, identity_ports in specs:
            dut = duts[dut_name]
            binding = ChiParticipantBinding(
                name,
                dut,
                _ParticipantComponent(f"{name}.component"),
                tuple(
                    ChiParticipantPortBinding(
                        dut.port(port_name),
                        frozenset((ChiChannelKind.REQ,)),
                    )
                    for port_name in node_ports[dut_name]
                ),
                node_ids,
            )
            facets.append(
                ChiBehaviorFacet.from_binding(
                    binding,
                    kind,
                    identity_ports=identity_ports,
                )
            )
        facet_items = tuple(facets)
        identities = resolve_chi_node_identities(system, facet_items)
        identities.require_closed()
        return system, facet_items, identities

    def _resolve(
        self,
        contract: ChiCoherenceAuthorityContract,
        **input_overrides,
    ) -> ChiResolvedCoherenceAuthorityPlan:
        system, facets, identities = self._inputs(**input_overrides)
        return resolve_chi_coherence_authority(
            system,
            facets,
            identities,
            contract,
        )

    @staticmethod
    def _contract(
        *,
        claim: str = "memory",
        home: str = "hn0",
        domain: str | None = "cluster",
    ) -> ChiCoherenceAuthorityContract:
        domains = (
            ()
            if domain is None
            else (
                ChiCoherenceDomain(
                    domain,
                    frozenset(("rn0", "rn1")),
                ),
            )
        )
        return ChiCoherenceAuthorityContract(
            (ChiHomeAuthority(claim, home, domain),),
            domains,
        )

    def test_address_selects_home_and_domain_members_select_snoopees(
        self,
    ) -> None:
        plan = self._resolve(self._contract())

        self.assertIsInstance(plan, ChiResolvedCoherenceAuthorityPlan)
        authority = plan.authority_for_address(0x1080)
        self.assertIs(authority, plan.authority_for_claim("memory"))
        self.assertEqual("hn0", authority.home)
        self.assertEqual(0x20, authority.home_node_id)
        self.assertEqual(
            plan.domain_for_claim("memory"),
            authority.coherence_domain,
        )
        assert authority.coherence_domain is not None
        self.assertEqual(
            ("rn0", "rn1"),
            authority.coherence_domain.members,
        )
        self.assertEqual(
            ("rn1",),
            plan.eligible_snoopees("memory", "rn0"),
        )
        self.assertEqual(
            ("rn0",),
            plan.eligible_snoopees("memory", "rn1"),
        )

    def test_single_requester_domain_derives_an_empty_peer_set(self) -> None:
        plan = self._resolve(
            ChiCoherenceAuthorityContract(
                (
                    ChiHomeAuthority(
                        "memory",
                        "hn0",
                        "single_requester",
                    ),
                ),
                (
                    ChiCoherenceDomain(
                        "single_requester",
                        frozenset(("rn0",)),
                    ),
                ),
            )
        )

        self.assertEqual(
            (),
            plan.eligible_snoopees("memory", "rn0"),
        )

    def test_authority_resolution_requires_generic_address_closure(
        self,
    ) -> None:
        with self.assertRaisesRegex(ValueError, "address plan"):
            self._resolve(self._contract(), claims=())

    def test_authority_rejects_unknown_claim_and_domain(self) -> None:
        with self.subTest("claim"):
            with self.assertRaisesRegex(ValueError, "unknown address claim"):
                self._resolve(self._contract(claim="missing"))
        with self.subTest("domain"):
            with self.assertRaisesRegex(ValueError, "unknown coherence domain"):
                self._resolve(
                    ChiCoherenceAuthorityContract(
                        (
                            ChiHomeAuthority(
                                "memory",
                                "hn0",
                                "missing",
                            ),
                        ),
                        (
                            ChiCoherenceDomain(
                                "cluster",
                                frozenset(("rn0", "rn1")),
                            ),
                        ),
                    )
                )
        with self.subTest("Home is not a coherent RN domain member"):
            with self.assertRaisesRegex(
                ValueError,
                "must not be a member",
            ):
                self._resolve(
                    ChiCoherenceAuthorityContract(
                        (
                            ChiHomeAuthority(
                                "memory",
                                "hn0",
                                "cluster",
                            ),
                        ),
                        (
                            ChiCoherenceDomain(
                                "cluster",
                                frozenset(("rn0", "hn0")),
                            ),
                        ),
                    )
                )

    def test_home_must_be_a_transaction_facet_on_the_claim_boundary(
        self,
    ) -> None:
        forwarding_home = (
            (
                "rn0",
                "rn0",
                ChiFacetKind.TRANSACTION,
                frozenset((0x10,)),
                None,
            ),
            (
                "rn1",
                "rn1",
                ChiFacetKind.TRANSACTION,
                frozenset((0x11,)),
                None,
            ),
            (
                "hn0",
                "hn0",
                ChiFacetKind.FORWARDING,
                frozenset((0x20,)),
                None,
            ),
        )
        with self.subTest("forwarding is not Home transaction authority"):
            with self.assertRaisesRegex(ValueError, "transaction facet"):
                self._resolve(
                    self._contract(),
                    facet_specs=forwarding_home,
                )

        mismatched_boundary = (
            *forwarding_home[:2],
            (
                "hn0",
                "hn0",
                ChiFacetKind.TRANSACTION,
                frozenset((0x20,)),
                frozenset(("identity",)),
            ),
        )
        with self.subTest("claim port is outside Home identity boundary"):
            with self.assertRaisesRegex(
                ValueError,
                "not part of Home identity boundary",
            ):
                self._resolve(
                    self._contract(),
                    nodes={
                        "rn0": ("link",),
                        "rn1": ("link",),
                        "hn0": ("home", "identity"),
                    },
                    facet_specs=mismatched_boundary,
                )

    def test_domain_member_must_resolve_to_one_node_id(self) -> None:
        compound_member = (
            (
                "rn0",
                "rn0",
                ChiFacetKind.TRANSACTION,
                frozenset((0x10, 0x12)),
                None,
            ),
            (
                "rn1",
                "rn1",
                ChiFacetKind.TRANSACTION,
                frozenset((0x11,)),
                None,
            ),
            (
                "hn0",
                "hn0",
                ChiFacetKind.TRANSACTION,
                frozenset((0x20,)),
                None,
            ),
        )

        with self.assertRaisesRegex(ValueError, "exactly one NodeID"):
            self._resolve(
                self._contract(),
                facet_specs=compound_member,
            )

        with self.assertRaisesRegex(ValueError, "distinct NodeIDs"):
            ChiResolvedCoherenceDomain(
                "shared_identity",
                ("rn0", "rn1"),
                {"rn0": 0x10, "rn1": 0x10},
            )

    def test_home_authority_windows_must_not_overlap(self) -> None:
        nodes = {
            "rn0": ("link",),
            "rn1": ("link",),
            "hn0": ("home",),
            "hn1": ("home",),
        }
        claims = (
            ("memory0", "hn0", "home", self.WINDOW),
            ("memory1", "hn1", "home", self.WINDOW),
        )
        facets = (
            (
                "rn0",
                "rn0",
                ChiFacetKind.TRANSACTION,
                frozenset((0x10,)),
                None,
            ),
            (
                "rn1",
                "rn1",
                ChiFacetKind.TRANSACTION,
                frozenset((0x11,)),
                None,
            ),
            (
                "hn0",
                "hn0",
                ChiFacetKind.TRANSACTION,
                frozenset((0x20,)),
                None,
            ),
            (
                "hn1",
                "hn1",
                ChiFacetKind.TRANSACTION,
                frozenset((0x21,)),
                None,
            ),
        )
        contract = ChiCoherenceAuthorityContract(
            (
                ChiHomeAuthority("memory0", "hn0"),
                ChiHomeAuthority("memory1", "hn1"),
            )
        )

        with self.assertRaisesRegex(ValueError, "overlap"):
            self._resolve(
                contract,
                nodes=nodes,
                claims=claims,
                facet_specs=facets,
            )


if __name__ == "__main__":
    unittest.main()
