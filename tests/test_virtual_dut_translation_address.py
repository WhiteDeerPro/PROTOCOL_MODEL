from __future__ import annotations

import unittest

from protocol_model.virtual_dut.address.access import (
    AccessResult,
    AccessStatus,
    AddressRead,
    AddressWrite,
)
from protocol_model.virtual_dut.fabric.route import AddressRoute
from protocol_model.virtual_dut.translation.address import (
    ADDRESS_ACCESS_SIGNATURE,
    AddressRouteStage,
)
from protocol_model.virtual_dut.translation.contract import (
    TranslationProfile,
    CompletionOrigin,
    SemanticEffectKind,
)
from protocol_model.virtual_dut.translation.engine import (
    CompleteParent,
    IssueChild,
    SerialTranslationExecutor,
)
from protocol_model.virtual_dut.translation.envelope import DecodedOperation
from protocol_model.virtual_dut.translation.plan import compile_translation_plan
from protocol_model.virtual_dut.translation.stage import LoweredOne


class AddressRouteStageTest(unittest.TestCase):
    @staticmethod
    def _stage() -> AddressRouteStage:
        return AddressRouteStage(
            (
                AddressRoute(
                    "peripheral",
                    0x8000,
                    0x100,
                    "egress",
                    output_base_address=0x1000,
                ),
            )
        )

    def test_signature_and_route_hit_preserve_the_address_operation(self) -> None:
        self.assertTrue(
            ADDRESS_ACCESS_SIGNATURE.accepts_request(AddressRead(0, 4))
        )
        self.assertTrue(
            ADDRESS_ACCESS_SIGNATURE.accepts_request(
                AddressWrite(0, 4, 0x11223344)
            )
        )
        self.assertTrue(
            ADDRESS_ACCESS_SIGNATURE.accepts_completion(AccessResult())
        )

        stage = self._stage()
        access = AddressWrite(
            0x8004,
            4,
            0xAABBCCDD,
            byte_enable=0b0101,
            attributes={"prot": 0b010},
        )
        lowered = stage.lower(access)

        self.assertIsInstance(lowered, LoweredOne)
        assert isinstance(lowered, LoweredOne)
        self.assertEqual(0x1004, lowered.child.address)
        self.assertEqual(access.data, lowered.child.data)
        self.assertEqual(
            access.effective_byte_enable, lowered.child.effective_byte_enable
        )
        self.assertEqual(dict(access.attributes), dict(lowered.child.attributes))
        self.assertIs(
            SemanticEffectKind.REBIND,
            stage.contract.semantic_effects[0].kind,
        )

    def test_route_miss_completes_locally_without_an_egress_lease(self) -> None:
        stage = self._stage()
        plan = compile_translation_plan(
            TranslationProfile(
                "address_route.serial",
                ADDRESS_ACCESS_SIGNATURE,
                ADDRESS_ACCESS_SIGNATURE,
            ),
            prefix_stages=(stage,),
        )
        executor = SerialTranslationExecutor(plan)

        completed = executor.accept_parent(
            executor.initial_state(),
            DecodedOperation(AddressRead(0x9000, 4), {"wire_id": 7}),
            ingress_binding="ingress",
        )

        self.assertIsNone(completed.fault)
        self.assertEqual(
            (CompleteParent,), tuple(type(x) for x in completed.emissions)
        )
        parent = completed.emissions[0]
        assert isinstance(parent, CompleteParent)
        self.assertEqual(AccessStatus.DECODE_ERROR, parent.result.status)
        self.assertEqual(CompletionOrigin.LOCAL_POLICY, parent.origin)
        self.assertEqual(0, completed.state.egress_pool_state.peak_usage)
        self.assertTrue(executor.is_quiescent(completed.state))

    def test_route_hit_issues_one_remapped_child_and_lifts_its_result(self) -> None:
        plan = compile_translation_plan(
            TranslationProfile(
                "address_route.serial",
                ADDRESS_ACCESS_SIGNATURE,
                ADDRESS_ACCESS_SIGNATURE,
            ),
            prefix_stages=(self._stage(),),
        )
        executor = SerialTranslationExecutor(plan)
        accepted = executor.accept_parent(
            executor.initial_state(),
            DecodedOperation(AddressRead(0x8008, 4), "reply"),
            ingress_binding="ingress",
        )

        self.assertIsNone(accepted.fault)
        self.assertEqual((IssueChild,), tuple(type(x) for x in accepted.emissions))
        child = accepted.emissions[0]
        assert isinstance(child, IssueChild)
        self.assertEqual(AddressRead(0x1008, 4), child.operation)

        result = AccessResult(data=0x44332211)
        completed = executor.accept_child_completion(
            accepted.state, child.owner, result
        )
        self.assertIsNone(completed.fault)
        parent = completed.emissions[0]
        assert isinstance(parent, CompleteParent)
        self.assertEqual(result, parent.result)
        self.assertEqual("reply", parent.envelope.reply_context)
        self.assertTrue(executor.is_quiescent(completed.state))

    def test_routes_must_share_one_egress_and_remain_non_overlapping(self) -> None:
        with self.assertRaisesRegex(ValueError, "one egress"):
            AddressRouteStage(
                (
                    AddressRoute("a", 0, 0x100, "left"),
                    AddressRoute("b", 0x100, 0x100, "right"),
                )
            )
        with self.assertRaisesRegex(ValueError, "overlap"):
            AddressRouteStage(
                (
                    AddressRoute("a", 0, 0x100, "egress"),
                    AddressRoute("b", 0x80, 0x100, "egress"),
                )
            )


if __name__ == "__main__":
    unittest.main()
