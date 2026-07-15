from __future__ import annotations

import unittest
from dataclasses import dataclass, replace

from protocol_model.virtual_dut.translation.contract import (
    BridgeProfile,
    CapabilityProjection,
    CapabilityRelation,
    CapabilitySet,
    CompletionOrigin,
    EquivalenceLevel,
    SemanticEffect,
    SemanticEffectKind,
    StageContract,
)
from protocol_model.virtual_dut.translation.engine import (
    CompleteParent,
    IssueChild,
    SerialExecutorProfile,
    SerialTranslationExecutor,
    TranslationFault,
)
from protocol_model.virtual_dut.translation.envelope import DecodedOperation
from protocol_model.virtual_dut.translation.lifecycle import (
    ChildLineage,
    ChildOwner,
    FanoutLedger,
    TokenRef,
)
from protocol_model.virtual_dut.translation.plan import (
    PlanClosureError,
    compile_translation_plan,
)
from protocol_model.virtual_dut.translation.resources import (
    CapacityFailure,
    CapacityFailureKind,
    CapacityLease,
    CapacityPool,
    CapacityPoolDecl,
    CapacityPoolState,
    ResourceKind,
    ResourceUnit,
)
from protocol_model.virtual_dut.translation.signature import OperationSignature
from protocol_model.virtual_dut.translation.stage import (
    Expanded,
    FanoutTranslationStage,
    IdentityTranslationStage,
    LocalCompletion,
    LoweredOne,
    UnaryTranslationStage,
)


@dataclass(frozen=True)
class Batch:
    values: tuple[int, ...]


@dataclass(frozen=True)
class BatchResult:
    values: tuple[int, ...]


@dataclass(frozen=True)
class Item:
    value: int


@dataclass(frozen=True)
class ItemResult:
    value: int


class DerivedItem(Item):
    pass


class DerivedItemResult(ItemResult):
    pass


@dataclass(frozen=True)
class AlternateItemResult:
    value: int


@dataclass(frozen=True)
class WrappedItem:
    value: int


@dataclass(frozen=True)
class WrappedItemResult:
    value: int


BATCH = OperationSignature(
    "test", "batch", "1", (Batch,), (BatchResult,)
)
ITEM = OperationSignature(
    "test", "item", "1", (Item,), (ItemResult,)
)
WRAPPED_ITEM = OperationSignature(
    "test", "wrapped_item", "1", (WrappedItem,), (WrappedItemResult,)
)


def _shape_projection(source: str, target: str) -> CapabilityProjection:
    return CapabilityProjection(
        CapabilitySet.of(shape=source),
        frozenset(("shape",)),
        CapabilitySet.of(shape=target),
    )


class BatchToItemStage(FanoutTranslationStage):
    name = "batch_to_item"
    source = BATCH
    target = ITEM
    contract = StageContract(
        CapabilityRelation(
            request=_shape_projection("batch", "item"),
            completion=_shape_projection("item", "batch"),
        ),
        (
            SemanticEffect("work", SemanticEffectKind.SPLIT),
            SemanticEffect("result", SemanticEffectKind.AGGREGATE),
        ),
        provenance="test.batch_to_item",
    )

    def begin(self, parent: Batch):
        if not parent.values:
            return LocalCompletion(BatchResult(()))
        return Expanded(len(parent.values), parent.values, ())

    def child_at(self, context: object | None, index: int) -> Item:
        assert isinstance(context, tuple)
        return Item(context[index])

    def fold_one(
        self,
        context: object | None,
        fold_state: object | None,
        index: int,
        child_result: ItemResult,
    ) -> tuple[int, ...]:
        assert isinstance(fold_state, tuple)
        return fold_state + (child_result.value,)

    def finish(
        self, context: object | None, fold_state: object | None
    ) -> BatchResult:
        assert isinstance(fold_state, tuple)
        return BatchResult(fold_state)


class WrapItemStage(UnaryTranslationStage):
    name = "wrap_item"
    source = ITEM
    target = WRAPPED_ITEM
    contract = StageContract(provenance="test.wrap_item")

    def lower(self, parent: Item):
        return LoweredOne(WrappedItem(parent.value), context="wrapped")

    def lift(
        self, context: object | None, child_result: WrappedItemResult
    ) -> ItemResult:
        if context != "wrapped":
            raise ValueError("unary context was not preserved")
        return ItemResult(child_result.value)


class LocalItemStage(UnaryTranslationStage):
    name = "local_item"
    source = ITEM
    target = ITEM
    contract = StageContract(
        completion_rule="test.local_item",
        provenance="test.local_item",
    )

    def lower(self, parent: Item):
        return LocalCompletion(
            ItemResult(parent.value),
            CompletionOrigin.LOCAL_POLICY,
            rule="test.local_item",
        )

    def lift(self, context: object | None, child_result: ItemResult):
        raise AssertionError("local completion must not call lift")


class FailingItemStage(UnaryTranslationStage):
    name = "failing_item"
    source = ITEM
    target = ITEM
    contract = StageContract(provenance="test.failing_item")

    def lower(self, parent: Item):
        raise RuntimeError("synthetic stage failure")

    def lift(self, context: object | None, child_result: ItemResult):
        return child_result


def _batch_plan(
    stage: BatchToItemStage | None = None,
    *,
    suffix_stages: tuple[UnaryTranslationStage, ...] = (),
):
    stage = BatchToItemStage() if stage is None else stage
    target = ITEM if not suffix_stages else suffix_stages[-1].target
    profile = BridgeProfile(
        "batch_to_item.serial",
        BATCH,
        target,
        source_request_capabilities=CapabilitySet.of(shape="batch"),
        target_request_requirements=CapabilitySet.of(shape="item"),
        target_completion_capabilities=CapabilitySet.of(shape="item"),
        source_completion_requirements=CapabilitySet.of(shape="batch"),
        provenance="test.profile",
    )
    return compile_translation_plan(
        profile, expansion=stage, suffix_stages=suffix_stages
    )


class TranslationPlanTest(unittest.TestCase):
    def test_capability_rewrite_requires_explicit_remove(self) -> None:
        hidden_rewrite = CapabilityProjection(
            provides=CapabilitySet.of(shape="item")
        ).apply(CapabilitySet.of(shape="batch"))
        self.assertFalse(hidden_rewrite.ok)
        self.assertEqual("shape", hidden_rewrite.gaps[0].name)

        explicit_rewrite = _shape_projection("batch", "item").apply(
            CapabilitySet.of(shape="batch")
        )
        self.assertTrue(explicit_rewrite.ok)

    def test_runtime_signature_boundary_is_exact(self) -> None:
        self.assertFalse(ITEM.accepts_request(DerivedItem(1)))
        self.assertFalse(ITEM.accepts_completion(DerivedItemResult(1)))

    def test_valid_plan_closes_both_directions_and_preserves_report(self) -> None:
        plan = _batch_plan()

        self.assertEqual(
            ("source", "after:batch_to_item"),
            tuple(
                item.boundary
                for item in plan.capability_closure.request_path
            ),
        )
        self.assertEqual(
            ("target", "before:batch_to_item"),
            tuple(
                item.boundary
                for item in plan.capability_closure.completion_path
            ),
        )
        self.assertEqual(
            (SemanticEffectKind.SPLIT, SemanticEffectKind.AGGREGATE),
            tuple(item.kind for item in plan.semantic_effects),
        )
        self.assertEqual(("test.batch_to_item",), plan.provenance.stages)

    def test_request_and_completion_signature_gaps_are_distinct(self) -> None:
        request_gap = OperationSignature(
            "test", "item", "1", (Batch,), (ItemResult,)
        )
        completion_gap = OperationSignature(
            "test", "batch", "1", (Batch,), (AlternateItemResult,)
        )
        cases = (
            (request_gap, "request_signature"),
            (completion_gap, "completion_signature"),
        )
        for signature, direction in cases:
            with self.subTest(direction=direction):
                stage = IdentityTranslationStage("gap", signature)
                profile = BridgeProfile("gap", BATCH, signature)
                with self.assertRaises(PlanClosureError) as raised:
                    compile_translation_plan(profile, prefix_stages=(stage,))
                self.assertEqual(direction, raised.exception.direction)
                self.assertEqual(0, raised.exception.stage_index)

    def test_stage_order_is_checked_through_intermediate_capabilities(self) -> None:
        needs_alignment = IdentityTranslationStage(
            "needs_alignment",
            ITEM,
            StageContract(
                CapabilityRelation(
                    request=CapabilityProjection(
                        requires=CapabilitySet.of(aligned=True)
                    )
                )
            ),
        )
        profile = BridgeProfile("order", ITEM, ITEM)
        with self.assertRaises(PlanClosureError) as raised:
            compile_translation_plan(
                profile, prefix_stages=(needs_alignment,)
            )
        self.assertEqual("request_capability", raised.exception.direction)
        self.assertEqual("aligned", raised.exception.property_name)

        establishes_alignment = IdentityTranslationStage(
            "establishes_alignment",
            ITEM,
            StageContract(
                CapabilityRelation(
                    request=CapabilityProjection(
                        provides=CapabilitySet.of(aligned=True)
                    )
                )
            ),
        )
        plan = compile_translation_plan(
            profile,
            prefix_stages=(establishes_alignment, needs_alignment),
        )
        self.assertEqual(2, len(plan.prefix_stages))

    def test_completion_capability_is_checked_in_reverse(self) -> None:
        needs_status = IdentityTranslationStage(
            "needs_status",
            ITEM,
            StageContract(
                CapabilityRelation(
                    completion=CapabilityProjection(
                        requires=CapabilitySet.of(status=True)
                    )
                )
            ),
        )
        with self.assertRaises(PlanClosureError) as raised:
            compile_translation_plan(
                BridgeProfile("missing_status", ITEM, ITEM),
                prefix_stages=(needs_status,),
            )
        self.assertEqual("completion_capability", raised.exception.direction)
        self.assertEqual("status", raised.exception.property_name)

        plan = compile_translation_plan(
            BridgeProfile(
                "has_status",
                ITEM,
                ITEM,
                target_completion_capabilities=CapabilitySet.of(status=True),
            ),
            prefix_stages=(needs_status,),
        )
        self.assertEqual(1, len(plan.prefix_stages))

    def test_undeclared_semantic_weakening_is_rejected(self) -> None:
        lossy = IdentityTranslationStage(
            "drop_qos",
            ITEM,
            StageContract(
                semantic_effects=(
                    SemanticEffect("qos", SemanticEffectKind.DROP),
                )
            ),
        )
        with self.assertRaises(PlanClosureError) as raised:
            compile_translation_plan(
                BridgeProfile("lossy", ITEM, ITEM),
                prefix_stages=(lossy,),
            )
        self.assertEqual("semantic_effect", raised.exception.direction)

        plan = compile_translation_plan(
            BridgeProfile(
                "allowed_loss",
                ITEM,
                ITEM,
                allowed_weakening=frozenset(("qos",)),
            ),
            prefix_stages=(lossy,),
        )
        self.assertEqual(SemanticEffectKind.DROP, plan.semantic_effects[0].kind)

    def test_plan_cannot_be_rewritten_around_the_compiler(self) -> None:
        plan = _batch_plan()
        with self.assertRaisesRegex(TypeError, "compile_translation_plan"):
            replace(plan, source=ITEM)

    def test_unimplemented_profile_promises_are_rejected(self) -> None:
        with self.assertRaises(PlanClosureError) as raised:
            compile_translation_plan(
                BridgeProfile(
                    "pin_cycle",
                    ITEM,
                    ITEM,
                    equivalence=EquivalenceLevel.PIN_CYCLE,
                )
            )
        self.assertEqual("profile_policy", raised.exception.direction)
        self.assertEqual("equivalence", raised.exception.property_name)

    def test_fanout_cannot_be_smuggled_into_unary_positions(self) -> None:
        with self.assertRaisesRegex(TypeError, "prefix accepts unary"):
            compile_translation_plan(
                BridgeProfile("two_fanouts", BATCH, ITEM),
                prefix_stages=(BatchToItemStage(),),
            )


class FanoutLedgerTest(unittest.TestCase):
    def test_obligations_are_independent_from_runtime_capacity(self) -> None:
        parent = TokenRef("parent", 7)
        ledger = FanoutLedger(parent, 3)
        snapshots = [ledger]
        for index in range(3):
            lineage = ChildLineage(
                parent, TokenRef("child", index), index
            )
            ledger = ledger.issue(lineage)
            self.assertEqual(1, len(ledger.inflight))
            ledger = ledger.complete(lineage)
            snapshots.append(ledger)

        self.assertEqual((0, 1, 2, 3), tuple(item.completed for item in snapshots))
        self.assertTrue(ledger.can_finish)
        self.assertEqual(3, ledger.total)

    def test_invalid_child_lifecycle_keeps_the_original_ledger(self) -> None:
        parent = TokenRef("parent", 0)
        ledger = FanoutLedger(parent, 2)
        skipped = ChildLineage(parent, TokenRef("child", 1), 1)
        with self.assertRaisesRegex(ValueError, "next fan-out child"):
            ledger.issue(skipped)
        self.assertEqual(0, ledger.issued)

        lineage = ChildLineage(parent, TokenRef("child", 0), 0)
        issued = ledger.issue(lineage)
        completed = issued.complete(lineage)
        with self.assertRaisesRegex(ValueError, "no inflight"):
            completed.complete(lineage)
        with self.assertRaisesRegex(ValueError, "cannot finish"):
            issued.require_finished()
        self.assertEqual(1, issued.issued)
        self.assertEqual(0, issued.completed)


class CapacityPoolTest(unittest.TestCase):
    def test_live_lease_cannot_be_overwritten_by_next_serial(self) -> None:
        lease = CapacityLease("pool", 0, 1, "owner")
        with self.assertRaisesRegex(ValueError, "exceed every live lease"):
            CapacityPoolState(
                {0: lease},
                next_serial=0,
                peak_usage=1,
                cumulative_acquisitions=1,
                cumulative_amount=1,
            )

    def test_one_slot_is_reused_for_three_child_obligations(self) -> None:
        pool = CapacityPool(
            CapacityPoolDecl(
                "child_slot",
                ResourceKind.EXECUTION,
                ResourceUnit.CHILD,
                1,
            )
        )
        state = pool.initial_state()
        for index in range(3):
            owner = ("child", index)
            acquired = pool.acquire(state, owner)
            self.assertTrue(acquired.ok)
            self.assertEqual(1, acquired.state.usage)
            assert acquired.lease is not None
            released = pool.release(
                acquired.state, acquired.lease, owner=owner
            )
            self.assertTrue(released.ok)
            state = released.state

        self.assertEqual(0, state.usage)
        self.assertEqual(1, state.peak_usage)
        self.assertEqual(3, state.cumulative_acquisitions)
        self.assertEqual(1, pool.declaration.resource_decl().capacity)

    def test_capacity_failure_is_atomic_and_structured(self) -> None:
        pool = CapacityPool(
            CapacityPoolDecl(
                "parent_slot",
                ResourceKind.PARENT,
                ResourceUnit.TRANSACTION,
                1,
            )
        )
        initial = pool.initial_state()
        first = pool.acquire(initial, "first")
        full = pool.acquire(first.state, "second")

        self.assertFalse(full.ok)
        self.assertIs(full.state, first.state)
        assert full.failure is not None
        self.assertEqual(CapacityFailureKind.FULL, full.failure.kind)
        self.assertEqual("parent_slot", full.failure.pool)
        self.assertEqual((1, 1, "second"), (
            full.failure.usage,
            full.failure.limit,
            full.failure.owner,
        ))
        assert first.lease is not None
        wrong = pool.release(first.state, first.lease, owner="second")
        assert wrong.failure is not None
        self.assertEqual(
            CapacityFailureKind.OWNER_MISMATCH, wrong.failure.kind
        )
        self.assertIs(wrong.state, first.state)

        released = pool.release(first.state, first.lease, owner="first")
        self.assertTrue(released.ok)
        duplicate = pool.release(released.state, first.lease, owner="first")
        assert duplicate.failure is not None
        self.assertEqual(
            CapacityFailureKind.UNKNOWN_LEASE, duplicate.failure.kind
        )
        self.assertIs(duplicate.state, released.state)


class SerialTranslationExecutorTest(unittest.TestCase):
    def test_one_to_one_stage_preserves_reverse_context(self) -> None:
        plan = compile_translation_plan(
            BridgeProfile("wrap", ITEM, WRAPPED_ITEM),
            prefix_stages=(WrapItemStage(),),
        )
        executor = SerialTranslationExecutor(plan)
        accepted = executor.accept_parent(
            executor.initial_state(),
            DecodedOperation(Item(5), {"wire_id": 3}),
            ingress_binding="ingress",
        )

        issued = accepted.emissions[0]
        self.assertIsInstance(issued, IssueChild)
        assert isinstance(issued, IssueChild)
        self.assertEqual(WrappedItem(5), issued.operation)
        completed = executor.accept_child_completion(
            accepted.state, issued.owner, WrappedItemResult(6)
        )

        self.assertIsNone(completed.fault)
        self.assertEqual(ItemResult(6), completed.emissions[0].result)
        self.assertTrue(executor.is_quiescent(completed.state))

    def test_three_children_are_generated_lazily_and_folded(self) -> None:
        executor = SerialTranslationExecutor(
            _batch_plan(), SerialExecutorProfile(parent_capacity=2)
        )
        context = {"wire_id": 91}
        accepted = executor.accept_parent(
            executor.initial_state(),
            DecodedOperation(Batch((10, 20, 30)), context),
            ingress_binding="ingress",
        )

        self.assertIsNone(accepted.fault)
        self.assertIsInstance(accepted.emissions[0], IssueChild)
        self.assertEqual(1, accepted.state.active.ledger.issued)
        self.assertEqual(0, accepted.state.active.ledger.completed)
        state = accepted.state
        for index, value in enumerate((10, 20, 30)):
            issued = next(
                item for item in accepted.emissions if isinstance(item, IssueChild)
            ) if index == 0 else next(
                item for item in transition.emissions if isinstance(item, IssueChild)
            )
            transition = executor.accept_child_completion(
                state, issued.owner, ItemResult(value)
            )
            self.assertIsNone(transition.fault)
            state = transition.state
            if index < 2:
                self.assertEqual(index + 2, state.active.ledger.issued)
                self.assertEqual(index + 1, state.active.ledger.completed)

        completion = next(
            item
            for item in transition.emissions
            if isinstance(item, CompleteParent)
        )
        self.assertEqual(BatchResult((10, 20, 30)), completion.result)
        self.assertIs(context, completion.envelope.reply_context)
        self.assertNotEqual(
            context["wire_id"], completion.envelope.token.serial
        )
        self.assertEqual(CompletionOrigin.DOWNSTREAM, completion.origin)
        self.assertTrue(executor.is_quiescent(state))
        self.assertEqual(1, state.egress_pool_state.peak_usage)
        self.assertEqual(3, state.egress_pool_state.cumulative_acquisitions)

    def test_second_parent_waits_then_starts_after_first_completion(self) -> None:
        executor = SerialTranslationExecutor(
            _batch_plan(), SerialExecutorProfile(parent_capacity=2)
        )
        first = executor.accept_parent(
            executor.initial_state(),
            DecodedOperation(Batch((1,)), "first"),
            ingress_binding="ingress",
        )
        second = executor.accept_parent(
            first.state,
            DecodedOperation(Batch((2,)), "second"),
            ingress_binding="ingress",
        )
        self.assertEqual((), second.emissions)

        first_issue = first.emissions[0]
        assert isinstance(first_issue, IssueChild)
        completed = executor.accept_child_completion(
            second.state, first_issue.owner, ItemResult(1)
        )
        self.assertEqual(
            (CompleteParent, IssueChild),
            tuple(type(item) for item in completed.emissions),
        )
        self.assertEqual(
            "first", completed.emissions[0].envelope.reply_context
        )
        self.assertEqual(
            "second",
            completed.state.active.queued.envelope.reply_context,
        )
        second_issue = completed.emissions[1]
        assert isinstance(second_issue, IssueChild)
        finished = executor.accept_child_completion(
            completed.state, second_issue.owner, ItemResult(2)
        )
        self.assertEqual("second", finished.emissions[0].envelope.reply_context)
        self.assertEqual(0, finished.state.parent_pool_state.usage)
        self.assertEqual(0, finished.state.egress_pool_state.usage)
        self.assertEqual(2, finished.state.parent_pool_state.cumulative_acquisitions)
        self.assertTrue(executor.is_quiescent(finished.state))

    def test_local_completion_never_acquires_the_egress_slot(self) -> None:
        executor = SerialTranslationExecutor(
            _batch_plan(suffix_stages=(LocalItemStage(),))
        )
        completed = executor.accept_parent(
            executor.initial_state(),
            DecodedOperation(Batch((4, 5)), "local"),
            ingress_binding="ingress",
        )

        self.assertIsNone(completed.fault)
        self.assertEqual((CompleteParent,), tuple(type(x) for x in completed.emissions))
        self.assertEqual(BatchResult((4, 5)), completed.emissions[0].result)
        self.assertEqual(
            CompletionOrigin.LOCAL_POLICY, completed.emissions[0].origin
        )
        self.assertEqual(0, completed.state.egress_pool_state.peak_usage)
        self.assertEqual(
            0, completed.state.egress_pool_state.cumulative_acquisitions
        )
        self.assertTrue(executor.is_quiescent(completed.state))

    def test_fanout_suffix_lifts_before_result_fold(self) -> None:
        executor = SerialTranslationExecutor(
            _batch_plan(suffix_stages=(WrapItemStage(),))
        )
        accepted = executor.accept_parent(
            executor.initial_state(),
            DecodedOperation(Batch((7,)), "wrapped"),
            ingress_binding="ingress",
        )
        issued = accepted.emissions[0]
        assert isinstance(issued, IssueChild)
        self.assertEqual(WrappedItem(7), issued.operation)

        completed = executor.accept_child_completion(
            accepted.state, issued.owner, WrappedItemResult(8)
        )
        self.assertEqual(BatchResult((8,)), completed.emissions[0].result)
        self.assertTrue(executor.is_quiescent(completed.state))

    def test_parent_capacity_fault_is_structured_and_atomic(self) -> None:
        executor = SerialTranslationExecutor(
            _batch_plan(), SerialExecutorProfile(parent_capacity=1)
        )
        first = executor.accept_parent(
            executor.initial_state(),
            DecodedOperation(Batch((1,)), "first"),
            ingress_binding="ingress",
        )
        rejected = executor.accept_parent(
            first.state,
            DecodedOperation(Batch((2,)), "second"),
            ingress_binding="ingress",
        )

        self.assertIs(rejected.state, first.state)
        self.assertEqual((), rejected.emissions)
        self.assertIsInstance(rejected.fault, TranslationFault)
        assert isinstance(rejected.fault, TranslationFault)
        self.assertIsInstance(rejected.fault.detail, CapacityFailure)
        assert isinstance(rejected.fault.detail, CapacityFailure)
        self.assertEqual((1, 1), (
            rejected.fault.detail.usage,
            rejected.fault.detail.limit,
        ))

        issued = first.emissions[0]
        assert isinstance(issued, IssueChild)
        recovered = executor.accept_child_completion(
            first.state, issued.owner, ItemResult(1)
        )
        self.assertTrue(executor.is_quiescent(recovered.state))

    def test_stage_exception_rolls_back_parent_admission(self) -> None:
        executor = SerialTranslationExecutor(
            compile_translation_plan(
                BridgeProfile("failing", ITEM, ITEM),
                prefix_stages=(FailingItemStage(),),
            )
        )
        initial = executor.initial_state()
        faulted = executor.accept_parent(
            initial,
            DecodedOperation(Item(1), None),
            ingress_binding="ingress",
        )

        self.assertIs(faulted.state, initial)
        self.assertEqual((), faulted.emissions)
        self.assertIsInstance(faulted.fault, TranslationFault)
        assert isinstance(faulted.fault, TranslationFault)
        self.assertIsInstance(faulted.fault.detail, RuntimeError)
        self.assertTrue(executor.is_quiescent(faulted.state))

    def test_wrong_child_owner_fault_rolls_back_executor_state(self) -> None:
        executor = SerialTranslationExecutor(_batch_plan())
        accepted = executor.accept_parent(
            executor.initial_state(),
            DecodedOperation(Batch((4,)), None),
            ingress_binding="ingress",
        )
        issued = accepted.emissions[0]
        assert isinstance(issued, IssueChild)
        wrong = ChildOwner(
            ChildLineage(
                issued.owner.parent,
                TokenRef("child", issued.owner.child.serial + 1),
                issued.owner.child_index,
            ),
            issued.owner.egress_binding,
        )
        faulted = executor.accept_child_completion(
            accepted.state, wrong, ItemResult(4)
        )

        self.assertIsNotNone(faulted.fault)
        self.assertIs(faulted.state, accepted.state)
        self.assertEqual((), faulted.emissions)
        recovered = executor.accept_child_completion(
            accepted.state, issued.owner, ItemResult(4)
        )
        self.assertIsNone(recovered.fault)
        self.assertTrue(executor.is_quiescent(recovered.state))


if __name__ == "__main__":
    unittest.main()
