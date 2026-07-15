"""Protocol-neutral strictly serial execution of a validated translation plan."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Union

from protocol_model.semantics.component import SemanticFault, SemanticStep
from protocol_model.semantics.model import ConstraintScope, ResourceDecl

from .contract import (
    CompletionOrigin,
    TranslationAccessMode,
)
from .envelope import DecodedOperation, ParentEnvelope
from .lifecycle import ChildLineage, ChildOwner, FanoutLedger, TokenRef
from .plan import TranslationPlan
from .resources import (
    CapacityFailure,
    CapacityLease,
    CapacityPool,
    CapacityPoolDecl,
    CapacityPoolState,
    ResourceKind,
    ResourceUnit,
)
from .signature import OperationSignature
from .stage import (
    Applicability,
    Expanded,
    FanoutTranslationStage,
    LocalCompletion,
    LoweredOne,
    Rejected,
    UnaryTranslationStage,
)


@dataclass(frozen=True)
class SerialExecutorProfile:
    parent_capacity: int = 8
    egress_binding: str = "egress"
    parent_pool_name: str = "translation.parents"
    egress_pool_name: str = "translation.egress"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.parent_capacity, int)
            or isinstance(self.parent_capacity, bool)
            or self.parent_capacity <= 0
        ):
            raise ValueError("serial executor parent capacity must be positive")
        for value, subject in (
            (self.egress_binding, "egress binding"),
            (self.parent_pool_name, "parent pool name"),
            (self.egress_pool_name, "egress pool name"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"serial executor {subject} must be non-empty")
        if self.parent_pool_name == self.egress_pool_name:
            raise ValueError("serial executor capacity pool names must differ")


@dataclass(frozen=True)
class IssueChild:
    owner: ChildOwner
    operation: object


@dataclass(frozen=True)
class CompleteParent:
    envelope: ParentEnvelope
    result: object
    origin: CompletionOrigin


TranslationEmission = Union[IssueChild, CompleteParent]


@dataclass(frozen=True)
class TranslationFault(SemanticFault):
    """A VirtualDut fault that retains typed translation-specific detail."""

    detail: object | None = None


@dataclass(frozen=True)
class _UnaryContext:
    stage: UnaryTranslationStage
    context: object | None


@dataclass(frozen=True)
class _QueuedParent:
    envelope: ParentEnvelope
    parent_lease: CapacityLease


@dataclass(frozen=True)
class _ActiveChild:
    owner: ChildOwner
    suffix_contexts: tuple[_UnaryContext, ...]
    egress_lease: CapacityLease


@dataclass(frozen=True)
class TranslationFrame:
    """One active parent and the contexts needed for reverse completion."""

    queued: _QueuedParent
    prefix_contexts: tuple[_UnaryContext, ...]
    ledger: FanoutLedger
    expansion: FanoutTranslationStage | None
    expansion_context: object | None = None
    fold_state: object | None = None
    single_child: object | None = None
    active_child: _ActiveChild | None = None
    completion_origins: frozenset[CompletionOrigin] = frozenset()


@dataclass(frozen=True)
class SerialTranslationState:
    ready: tuple[_QueuedParent, ...]
    active: TranslationFrame | None
    next_parent_serial: int
    next_child_serial: int
    parent_pool_state: CapacityPoolState
    egress_pool_state: CapacityPoolState


@dataclass(frozen=True)
class _ImmediateResult:
    result: object
    origin: CompletionOrigin


@dataclass(frozen=True)
class _LoweredChain:
    operation: object | None = None
    contexts: tuple[_UnaryContext, ...] = ()
    immediate: _ImmediateResult | None = None


class _ExecutionFailure(Exception):
    def __init__(self, rule: str, reason: str) -> None:
        super().__init__(reason)
        self.rule = rule
        self.reason = reason


class SerialTranslationExecutor:
    """Execute one linear plan with one active egress child.

    The executor consumes typed operations, not ``CanonicalEvent`` values.
    An attachment-aware VirtualDut backend can decode into
    ``DecodedOperation``, call this engine, encode the returned emissions, and
    commit the candidate state only when all encoding succeeds.  Consequently
    each public method is atomic: any fault returns the original state and no
    emissions.
    """

    def __init__(
        self,
        plan: TranslationPlan,
        profile: SerialExecutorProfile | None = None,
    ) -> None:
        if not isinstance(plan, TranslationPlan):
            raise TypeError("serial executor requires a TranslationPlan")
        plan.require_current_stage_metadata()
        if not plan.source.has_completion or not plan.target.has_completion:
            raise ValueError(
                "serial request/completion executor requires completion signatures"
            )
        if (
            plan.profile.access_mode
            is not TranslationAccessMode.STREAMING_SEQUENTIAL
        ):
            raise ValueError(
                "serial executor requires the streaming_sequential access mode"
            )
        self.plan = plan
        self.profile = SerialExecutorProfile() if profile is None else profile
        if not isinstance(self.profile, SerialExecutorProfile):
            raise TypeError("serial executor profile has the wrong type")
        self.parent_pool = CapacityPool(
            CapacityPoolDecl(
                self.profile.parent_pool_name,
                ResourceKind.PARENT,
                ResourceUnit.TRANSACTION,
                self.profile.parent_capacity,
                "accepted parent operations retained until completion",
            )
        )
        self.egress_pool = CapacityPool(
            CapacityPoolDecl(
                self.profile.egress_pool_name,
                ResourceKind.EXECUTION,
                ResourceUnit.CHILD,
                1,
                "strictly serial child execution slot",
            )
        )

    @property
    def capacity_declarations(self) -> tuple[CapacityPoolDecl, ...]:
        """Typed runtime resource facts retained beside generic projections."""

        return (self.parent_pool.declaration, self.egress_pool.declaration)

    @property
    def resource_declarations(self) -> tuple[ResourceDecl, ...]:
        return tuple(
            declaration.resource_decl()
            for declaration in self.capacity_declarations
        )

    def initial_state(self) -> SerialTranslationState:
        return SerialTranslationState(
            (),
            None,
            0,
            0,
            self.parent_pool.initial_state(),
            self.egress_pool.initial_state(),
        )

    def accept_parent(
        self,
        state: SerialTranslationState,
        decoded: DecodedOperation,
        *,
        ingress_binding: str,
    ) -> SemanticStep[SerialTranslationState, TranslationEmission]:
        self._validate_state(state)
        if not isinstance(decoded, DecodedOperation):
            raise TypeError("serial executor requires a DecodedOperation")
        if not isinstance(ingress_binding, str) or not ingress_binding:
            raise ValueError("serial executor requires an ingress binding")
        if not self.plan.source.accepts_request(decoded.operation):
            return self._fault_step(
                state,
                "parent_type",
                f"{self.plan.source.qualified_name} does not accept "
                f"{type(decoded.operation).__name__}",
            )

        token = TokenRef("parent", state.next_parent_serial)
        acquired = self.parent_pool.acquire(state.parent_pool_state, token)
        if acquired.failure is not None:
            return self._capacity_fault_step(state, acquired.failure)
        assert acquired.lease is not None
        envelope = ParentEnvelope(
            token,
            decoded.operation,
            decoded.reply_context,
            ingress_binding,
        )
        candidate = replace(
            state,
            ready=state.ready + (_QueuedParent(envelope, acquired.lease),),
            next_parent_serial=state.next_parent_serial + 1,
            parent_pool_state=acquired.state,
        )
        return self._drive_atomically(state, candidate)

    def accept_child_completion(
        self,
        state: SerialTranslationState,
        owner: ChildOwner,
        result: object,
        *,
        origin: CompletionOrigin = CompletionOrigin.DOWNSTREAM,
    ) -> SemanticStep[SerialTranslationState, TranslationEmission]:
        self._validate_state(state)
        if not isinstance(owner, ChildOwner):
            raise TypeError("child completion requires a ChildOwner")
        if not isinstance(origin, CompletionOrigin):
            raise TypeError("child completion origin must be CompletionOrigin")
        active = state.active
        if active is None or active.active_child is None:
            return self._fault_step(
                state,
                "orphan_completion",
                "child completion has no active owner",
            )
        if active.active_child.owner != owner:
            return self._fault_step(
                state,
                "completion_owner",
                f"child completion owner {owner!r} does not match "
                f"{active.active_child.owner!r}",
            )
        if not self.plan.target.accepts_completion(result):
            return self._fault_step(
                state,
                "completion_type",
                f"{self.plan.target.qualified_name} does not accept "
                f"{type(result).__name__} completion",
            )

        try:
            child_result = self._lift_unary_contexts(
                active.active_child.suffix_contexts, result
            )
            ledger = active.ledger.complete(owner.lineage)
            released = self.egress_pool.release(
                state.egress_pool_state,
                active.active_child.egress_lease,
                owner=owner,
            )
            if released.failure is not None:
                raise _ExecutionFailure(
                    "egress_release", released.failure.reason
                )
            next_frame = self._fold_child(
                replace(active, ledger=ledger, active_child=None),
                owner.child_index,
                child_result,
                origin,
            )
            candidate = replace(
                state,
                active=next_frame,
                egress_pool_state=released.state,
            )
        except _ExecutionFailure as error:
            return self._fault_step(state, error.rule, error.reason)
        except Exception as error:
            return self._exception_fault_step(state, error)
        return self._drive_atomically(state, candidate)

    def is_quiescent(self, state: SerialTranslationState) -> bool:
        self._validate_state(state)
        return (
            not state.ready
            and state.active is None
            and state.parent_pool_state.usage == 0
            and state.egress_pool_state.usage == 0
        )

    def resource_usage(self, state: SerialTranslationState) -> dict[str, int]:
        self._validate_state(state)
        return {
            self.parent_pool.declaration.name: state.parent_pool_state.usage,
            self.egress_pool.declaration.name: state.egress_pool_state.usage,
        }

    def _drive_atomically(
        self,
        original: SerialTranslationState,
        candidate: SerialTranslationState,
    ) -> SemanticStep[SerialTranslationState, TranslationEmission]:
        try:
            transition = self._drive(candidate)
            self._validate_state(transition.state)
            return transition
        except _ExecutionFailure as error:
            return self._fault_step(original, error.rule, error.reason)
        except Exception as error:
            return self._exception_fault_step(original, error)

    def _drive(
        self, state: SerialTranslationState
    ) -> SemanticStep[SerialTranslationState, TranslationEmission]:
        candidate = state
        emissions: list[TranslationEmission] = []
        while True:
            if candidate.active is None:
                if not candidate.ready:
                    return SemanticStep(candidate, tuple(emissions))
                queued = candidate.ready[0]
                opened = self._open_frame(queued)
                candidate = replace(candidate, ready=candidate.ready[1:])
                if isinstance(opened, _ImmediateResult):
                    candidate, completion = self._complete_parent(
                        candidate,
                        queued,
                        opened.result,
                        opened.origin,
                    )
                    emissions.append(completion)
                    continue
                candidate = replace(candidate, active=opened)

            frame = candidate.active
            assert frame is not None
            if frame.active_child is not None:
                return SemanticStep(candidate, tuple(emissions))

            if frame.ledger.can_finish:
                result = self._finish_parent_result(frame)
                origin = self._combined_origin(frame.completion_origins)
                candidate, completion = self._complete_parent(
                    replace(candidate, active=None),
                    frame.queued,
                    result,
                    origin,
                )
                emissions.append(completion)
                continue

            child_index = frame.ledger.issued
            child_operation = self._child_operation(frame, child_index)
            lowered = self._lower_unary_chain(
                child_operation, self.plan.suffix_stages
            )
            child_token = TokenRef("child", candidate.next_child_serial)
            if lowered.immediate is not None:
                lineage = ChildLineage(
                    frame.queued.envelope.token,
                    child_token,
                    child_index,
                )
                ledger = frame.ledger.issue(lineage).complete(lineage)
                frame = self._fold_child(
                    replace(frame, ledger=ledger),
                    child_index,
                    lowered.immediate.result,
                    lowered.immediate.origin,
                )
                candidate = replace(
                    candidate,
                    active=frame,
                    next_child_serial=candidate.next_child_serial + 1,
                )
                continue

            assert lowered.operation is not None
            if not self.plan.target.accepts_request(lowered.operation):
                raise _ExecutionFailure(
                    "child_type",
                    f"{self.plan.target.qualified_name} does not accept "
                    f"{type(lowered.operation).__name__}",
                )
            lineage = ChildLineage(
                frame.queued.envelope.token,
                child_token,
                child_index,
            )
            owner = ChildOwner(lineage, self.profile.egress_binding)
            acquired = self.egress_pool.acquire(
                candidate.egress_pool_state, owner
            )
            if acquired.failure is not None:
                raise _ExecutionFailure(
                    "egress_capacity", acquired.failure.reason
                )
            assert acquired.lease is not None
            frame = replace(
                frame,
                ledger=frame.ledger.issue(lineage),
                active_child=_ActiveChild(
                    owner, lowered.contexts, acquired.lease
                ),
            )
            candidate = replace(
                candidate,
                active=frame,
                next_child_serial=candidate.next_child_serial + 1,
                egress_pool_state=acquired.state,
            )
            emissions.append(IssueChild(owner, lowered.operation))
            return SemanticStep(candidate, tuple(emissions))

    def _open_frame(
        self, queued: _QueuedParent
    ) -> TranslationFrame | _ImmediateResult:
        lowered = self._lower_unary_chain(
            queued.envelope.operation, self.plan.prefix_stages
        )
        if lowered.immediate is not None:
            return lowered.immediate
        operation = lowered.operation
        assert operation is not None

        expansion = self.plan.expansion
        if expansion is None:
            return TranslationFrame(
                queued,
                lowered.contexts,
                FanoutLedger(queued.envelope.token, 1),
                None,
                single_child=operation,
            )
        applicability = self._applicability(expansion, operation)
        if not applicability.accepted:
            raise _ExecutionFailure(
                applicability.rule or "not_applicable",
                f"stage {expansion.name!r}: {applicability.reason}",
            )
        beginning = expansion.begin(operation)
        if isinstance(beginning, Rejected):
            raise _ExecutionFailure(
                beginning.rule or "rejected",
                f"stage {expansion.name!r}: {beginning.reason}",
            )
        if isinstance(beginning, LocalCompletion):
            self._require_completion(expansion.source, beginning.result)
            result = self._lift_unary_contexts(
                lowered.contexts, beginning.result
            )
            return _ImmediateResult(result, beginning.origin)
        if not isinstance(beginning, Expanded):
            raise _ExecutionFailure(
                "stage_outcome",
                f"stage {expansion.name!r} returned an invalid begin outcome",
            )
        return TranslationFrame(
            queued,
            lowered.contexts,
            FanoutLedger(queued.envelope.token, beginning.count),
            expansion,
            beginning.context,
            beginning.fold_state,
        )

    def _lower_unary_chain(
        self,
        operation: object,
        stages: tuple[UnaryTranslationStage, ...],
    ) -> _LoweredChain:
        current = operation
        contexts: list[_UnaryContext] = []
        for stage in stages:
            self._require_request(stage.source, current)
            applicability = self._applicability(stage, current)
            if not applicability.accepted:
                raise _ExecutionFailure(
                    applicability.rule or "not_applicable",
                    f"stage {stage.name!r}: {applicability.reason}",
                )
            outcome = stage.lower(current)
            if isinstance(outcome, Rejected):
                raise _ExecutionFailure(
                    outcome.rule or "rejected",
                    f"stage {stage.name!r}: {outcome.reason}",
                )
            if isinstance(outcome, LocalCompletion):
                self._require_completion(stage.source, outcome.result)
                result = self._lift_unary_contexts(
                    tuple(contexts), outcome.result
                )
                return _LoweredChain(
                    immediate=_ImmediateResult(result, outcome.origin)
                )
            if not isinstance(outcome, LoweredOne):
                raise _ExecutionFailure(
                    "stage_outcome",
                    f"stage {stage.name!r} returned an invalid lower outcome",
                )
            self._require_request(stage.target, outcome.child)
            contexts.append(_UnaryContext(stage, outcome.context))
            current = outcome.child
        return _LoweredChain(current, tuple(contexts))

    def _child_operation(
        self, frame: TranslationFrame, child_index: int
    ) -> object:
        if frame.expansion is None:
            if child_index != 0:
                raise _ExecutionFailure(
                    "child_index", "unary plan has only child index zero"
                )
            operation = frame.single_child
            self._require_request(self._body_signature(), operation)
            return operation
        operation = frame.expansion.child_at(
            frame.expansion_context, child_index
        )
        self._require_request(frame.expansion.target, operation)
        return operation

    def _fold_child(
        self,
        frame: TranslationFrame,
        child_index: int,
        child_result: object,
        origin: CompletionOrigin,
    ) -> TranslationFrame:
        body_signature = self._body_signature()
        self._require_completion(body_signature, child_result)
        if frame.expansion is None:
            fold_state = child_result
        else:
            fold_state = frame.expansion.fold_one(
                frame.expansion_context,
                frame.fold_state,
                child_index,
                child_result,
            )
        return replace(
            frame,
            fold_state=fold_state,
            completion_origins=frame.completion_origins | {origin},
        )

    def _finish_parent_result(self, frame: TranslationFrame) -> object:
        frame.ledger.require_finished()
        if frame.expansion is None:
            result = frame.fold_state
            self._require_completion(self._body_signature(), result)
        else:
            result = frame.expansion.finish(
                frame.expansion_context, frame.fold_state
            )
            self._require_completion(frame.expansion.source, result)
        result = self._lift_unary_contexts(frame.prefix_contexts, result)
        self._require_completion(self.plan.source, result)
        return result

    def _complete_parent(
        self,
        state: SerialTranslationState,
        queued: _QueuedParent,
        result: object,
        origin: CompletionOrigin,
    ) -> tuple[SerialTranslationState, CompleteParent]:
        self._require_completion(self.plan.source, result)
        released = self.parent_pool.release(
            state.parent_pool_state,
            queued.parent_lease,
            owner=queued.envelope.token,
        )
        if released.failure is not None:
            raise _ExecutionFailure(
                "parent_release", released.failure.reason
            )
        return (
            replace(state, parent_pool_state=released.state),
            CompleteParent(queued.envelope, result, origin),
        )

    def _lift_unary_contexts(
        self, contexts: tuple[_UnaryContext, ...], result: object
    ) -> object:
        current = result
        for item in reversed(contexts):
            self._require_completion(item.stage.target, current)
            current = item.stage.lift(item.context, current)
            self._require_completion(item.stage.source, current)
        return current

    @staticmethod
    def _applicability(
        stage: UnaryTranslationStage | FanoutTranslationStage,
        operation: object,
    ) -> Applicability:
        result = stage.applicable(operation)
        if not isinstance(result, Applicability):
            raise _ExecutionFailure(
                "applicability",
                f"stage {stage.name!r} returned an invalid applicability result",
            )
        return result

    def _body_signature(self) -> OperationSignature:
        if self.plan.expansion is not None:
            return self.plan.expansion.target
        if self.plan.suffix_stages:
            return self.plan.suffix_stages[0].source
        return self.plan.target

    @staticmethod
    def _require_request(signature: OperationSignature, value: object) -> None:
        if not signature.accepts_request(value):
            raise _ExecutionFailure(
                "request_type",
                f"{signature.qualified_name} does not accept "
                f"{type(value).__name__}",
            )

    @staticmethod
    def _require_completion(
        signature: OperationSignature, value: object
    ) -> None:
        if not signature.accepts_completion(value):
            raise _ExecutionFailure(
                "completion_type",
                f"{signature.qualified_name} does not accept "
                f"{type(value).__name__}",
            )

    @staticmethod
    def _combined_origin(
        origins: frozenset[CompletionOrigin],
    ) -> CompletionOrigin:
        if not origins:
            raise _ExecutionFailure(
                "completion_origin", "completed parent has no result origin"
            )
        if len(origins) == 1:
            return next(iter(origins))
        return CompletionOrigin.MIXED

    @staticmethod
    def _fault_step(
        state: SerialTranslationState,
        rule: str,
        reason: str,
        *,
        detail: object | None = None,
    ) -> SemanticStep[SerialTranslationState, TranslationEmission]:
        return SemanticStep(
            state,
            fault=TranslationFault(
                f"translation_executor.{rule}",
                reason,
                ConstraintScope.VIRTUAL_DUT,
                detail=detail,
            ),
        )

    def _exception_fault_step(
        self, state: SerialTranslationState, error: Exception
    ) -> SemanticStep[SerialTranslationState, TranslationEmission]:
        return self._fault_step(
            state,
            "stage_exception",
            f"{type(error).__name__}: {error}",
            detail=error,
        )

    def _capacity_fault_step(
        self, state: SerialTranslationState, failure: CapacityFailure
    ) -> SemanticStep[SerialTranslationState, TranslationEmission]:
        return self._fault_step(
            state,
            "capacity",
            f"pool={failure.pool!r} usage={failure.usage} "
            f"limit={failure.limit} owner={failure.owner!r}: {failure.reason}",
            detail=failure,
        )

    def _validate_state(self, state: SerialTranslationState) -> None:
        if not isinstance(state, SerialTranslationState):
            raise TypeError("serial executor requires SerialTranslationState")
        self.plan.require_current_stage_metadata()
        self.parent_pool.validate_state(state.parent_pool_state)
        self.egress_pool.validate_state(state.egress_pool_state)
        if not isinstance(state.ready, tuple):
            raise TypeError("serial executor ready queue must be a tuple")
        if (
            not isinstance(state.next_parent_serial, int)
            or isinstance(state.next_parent_serial, bool)
            or state.next_parent_serial < 0
        ):
            raise ValueError("next parent token serial must be non-negative")
        if (
            not isinstance(state.next_child_serial, int)
            or isinstance(state.next_child_serial, bool)
            or state.next_child_serial < 0
        ):
            raise ValueError("next child token serial must be non-negative")

        queued = list(state.ready)
        if state.active is not None:
            if not isinstance(state.active, TranslationFrame):
                raise TypeError("serial executor active state must be a frame")
            queued.append(state.active.queued)
        if any(not isinstance(item, _QueuedParent) for item in queued):
            raise TypeError("serial executor queue contains an invalid parent")
        parent_tokens = tuple(item.envelope.token for item in queued)
        if len(set(parent_tokens)) != len(parent_tokens):
            raise ValueError("serial executor parent tokens must be unique")
        if any(token.serial >= state.next_parent_serial for token in parent_tokens):
            raise ValueError("next parent serial must exceed every live parent token")
        parent_leases = {item.parent_lease.serial: item.parent_lease for item in queued}
        if len(parent_leases) != len(queued):
            raise ValueError("serial executor parent leases must be unique")
        for item in queued:
            if item.parent_lease.owner != item.envelope.token:
                raise ValueError("parent lease owner does not match its envelope")
        if parent_leases != dict(state.parent_pool_state.leases):
            raise ValueError("parent pool leases do not match live parent envelopes")

        active = state.active
        if active is None:
            if state.egress_pool_state.leases:
                raise ValueError("egress lease exists without an active parent")
            return
        if active.ledger.parent != active.queued.envelope.token:
            raise ValueError("active fan-out ledger belongs to another parent")
        if active.ledger.can_finish:
            raise ValueError("finished active parent should have been completed")
        child = active.active_child
        if child is None:
            raise ValueError("active serial parent must be waiting for one child")
        if child.owner.lineage not in active.ledger.inflight:
            raise ValueError("active child is absent from the fan-out ledger")
        if len(active.ledger.inflight) != 1:
            raise ValueError("serial executor permits one inflight child")
        if child.owner.child.serial >= state.next_child_serial:
            raise ValueError("next child serial must exceed the active child token")
        if child.egress_lease.owner != child.owner:
            raise ValueError("egress lease owner does not match the active child")
        if dict(state.egress_pool_state.leases) != {
            child.egress_lease.serial: child.egress_lease
        }:
            raise ValueError("egress pool lease does not match the active child")
