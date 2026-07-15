"""Compiler-validated, runtime-state-free linear translation plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from .contract import (
    BridgeProfile,
    CapabilityGap,
    CapabilitySet,
    EquivalenceLevel,
    ResetCancelPolicy,
    SemanticEffect,
    SemanticEffectKind,
    StageContract,
    TranslationAccessMode,
    UnsupportedPolicy,
)
from .signature import OperationSignature
from .stage import (
    FanoutTranslationStage,
    StageCardinality,
    UnaryTranslationStage,
)


TranslationStage = Union[UnaryTranslationStage, FanoutTranslationStage]
_PLAN_SEAL = object()


class PlanClosureError(ValueError):
    """A construction failure located at one plan boundary or property."""

    def __init__(
        self,
        direction: str,
        reason: str,
        *,
        stage_index: int | None = None,
        stage_name: str = "",
        expected: object | None = None,
        observed: object | None = None,
        property_name: str = "",
    ) -> None:
        self.direction = direction
        self.reason = reason
        self.stage_index = stage_index
        self.stage_name = stage_name
        self.expected = expected
        self.observed = observed
        self.property_name = property_name
        location = (
            "plan boundary"
            if stage_index is None
            else f"stage {stage_index} {stage_name!r}"
        )
        super().__init__(f"{direction} closure failed at {location}: {reason}")


@dataclass(frozen=True)
class CapabilitySnapshot:
    boundary: str
    capabilities: CapabilitySet


@dataclass(frozen=True)
class CapabilityClosure:
    request_path: tuple[CapabilitySnapshot, ...]
    completion_path: tuple[CapabilitySnapshot, ...]


@dataclass(frozen=True)
class PlanProvenance:
    profile: str
    stages: tuple[str, ...]


@dataclass(frozen=True)
class _StageFingerprint:
    name: str
    source: OperationSignature
    target: OperationSignature
    contract: StageContract
    cardinality: StageCardinality


@dataclass(frozen=True)
class _CompiledPlanWitness:
    payload: tuple[object, ...]
    stage_fingerprints: tuple[_StageFingerprint, ...]
    seal: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class TranslationPlan:
    """A compiler-produced, runtime-state-free linear plan.

    Stage implementations are required to be stateless.  The plan records a
    metadata fingerprint and the executor rechecks it before use; arbitrary
    Python side effects inside a stage cannot be made immutable by this DTO.
    """

    profile: BridgeProfile
    source: OperationSignature
    target: OperationSignature
    prefix_stages: tuple[UnaryTranslationStage, ...]
    expansion: FanoutTranslationStage | None
    suffix_stages: tuple[UnaryTranslationStage, ...]
    capability_closure: CapabilityClosure
    semantic_effects: tuple[SemanticEffect, ...]
    provenance: PlanProvenance
    _witness: _CompiledPlanWitness = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self._witness, _CompiledPlanWitness)
            or self._witness.seal is not _PLAN_SEAL
            or self._witness.payload != self._construction_payload()
        ):
            raise TypeError(
                "TranslationPlan must be created by compile_translation_plan()"
            )

    @property
    def stages(self) -> tuple[TranslationStage, ...]:
        expansion = () if self.expansion is None else (self.expansion,)
        return self.prefix_stages + expansion + self.suffix_stages

    def require_current_stage_metadata(self) -> None:
        observed = tuple(_stage_fingerprint(stage) for stage in self.stages)
        if observed != self._witness.stage_fingerprints:
            raise PlanClosureError(
                "metadata",
                "stage metadata changed after plan compilation",
            )

    def _construction_payload(self) -> tuple[object, ...]:
        return (
            self.profile,
            self.source,
            self.target,
            self.prefix_stages,
            self.expansion,
            self.suffix_stages,
            self.capability_closure,
            self.semantic_effects,
            self.provenance,
        )


def compile_translation_plan(
    profile: BridgeProfile,
    *,
    prefix_stages: tuple[UnaryTranslationStage, ...] = (),
    expansion: FanoutTranslationStage | None = None,
    suffix_stages: tuple[UnaryTranslationStage, ...] = (),
) -> TranslationPlan:
    """Validate signatures, both capability directions, and semantic loss."""

    if not isinstance(profile, BridgeProfile):
        raise TypeError("translation plan requires a BridgeProfile")
    prefix_stages = tuple(prefix_stages)
    suffix_stages = tuple(suffix_stages)
    if any(not isinstance(stage, UnaryTranslationStage) for stage in prefix_stages):
        raise TypeError("translation prefix accepts unary stages only")
    if any(not isinstance(stage, UnaryTranslationStage) for stage in suffix_stages):
        raise TypeError("translation suffix accepts unary stages only")
    if expansion is not None and not isinstance(
        expansion, FanoutTranslationStage
    ):
        raise TypeError("translation expansion must be a fan-out stage")

    stages: tuple[TranslationStage, ...] = (
        prefix_stages
        + (() if expansion is None else (expansion,))
        + suffix_stages
    )
    _validate_supported_profile(profile)
    _validate_stage_metadata(stages)
    _validate_signatures(profile, stages)
    closure = _close_capabilities(profile, stages)
    effects = tuple(
        effect
        for stage in stages
        for effect in stage.contract.semantic_effects
    )
    _validate_semantic_loss(profile, stages)
    provenance = PlanProvenance(
        profile.provenance or profile.name,
        tuple(
            stage.contract.provenance or stage.name
            for stage in stages
        ),
    )
    payload = (
        profile,
        profile.source,
        profile.target,
        prefix_stages,
        expansion,
        suffix_stages,
        closure,
        effects,
        provenance,
    )
    witness = _CompiledPlanWitness(
        payload,
        tuple(_stage_fingerprint(stage) for stage in stages),
        _PLAN_SEAL,
    )
    return TranslationPlan(*payload, witness)


def _validate_supported_profile(profile: BridgeProfile) -> None:
    supported = (
        ("ordering", profile.ordering, ()),
        (
            "equivalence",
            profile.equivalence,
            EquivalenceLevel.OPERATION_EFFECT,
        ),
        (
            "unsupported_policy",
            profile.unsupported_policy,
            UnsupportedPolicy.REJECT,
        ),
        (
            "reset_cancel_policy",
            profile.reset_cancel_policy,
            ResetCancelPolicy.REPORT_FAULT,
        ),
        (
            "access_mode",
            profile.access_mode,
            TranslationAccessMode.STREAMING_SEQUENTIAL,
        ),
    )
    for property_name, observed, expected in supported:
        if observed != expected:
            raise PlanClosureError(
                "profile_policy",
                f"V1 compiler has no executable evidence for {property_name}",
                expected=expected,
                observed=observed,
                property_name=property_name,
            )


def _stage_fingerprint(stage: TranslationStage) -> _StageFingerprint:
    return _StageFingerprint(
        stage.name,
        stage.source,
        stage.target,
        stage.contract,
        stage.cardinality,
    )


def _validate_stage_metadata(stages: tuple[TranslationStage, ...]) -> None:
    names = []
    for index, stage in enumerate(stages):
        if not isinstance(stage.name, str) or not stage.name:
            raise PlanClosureError(
                "metadata",
                "stage requires a non-empty name",
                stage_index=index,
            )
        if not isinstance(stage.source, OperationSignature) or not isinstance(
            stage.target, OperationSignature
        ):
            raise PlanClosureError(
                "metadata",
                "stage requires source and target signatures",
                stage_index=index,
                stage_name=stage.name,
            )
        if not isinstance(stage.contract, StageContract):
            raise PlanClosureError(
                "metadata",
                "stage requires a StageContract",
                stage_index=index,
                stage_name=stage.name,
            )
        if stage.contract.preservation_obligations:
            raise PlanClosureError(
                "preservation_obligation",
                "V1 compiler does not yet close free-form preservation obligations",
                stage_index=index,
                stage_name=stage.name,
                expected=(),
                observed=stage.contract.preservation_obligations,
            )
        if isinstance(stage, FanoutTranslationStage):
            effect_kinds = {effect.kind for effect in stage.contract.semantic_effects}
            required = {
                SemanticEffectKind.SPLIT,
                SemanticEffectKind.AGGREGATE,
            }
            if not required.issubset(effect_kinds):
                raise PlanClosureError(
                    "semantic_effect",
                    "fan-out stage must declare split and aggregate effects",
                    stage_index=index,
                    stage_name=stage.name,
                    expected=required,
                    observed=effect_kinds,
                )
        names.append(stage.name)
    if len(set(names)) != len(names):
        duplicate = next(name for name in names if names.count(name) > 1)
        raise PlanClosureError(
            "metadata",
            f"stage name {duplicate!r} is not unique",
            stage_name=duplicate,
        )


def _validate_signatures(
    profile: BridgeProfile, stages: tuple[TranslationStage, ...]
) -> None:
    current = profile.source
    for index, stage in enumerate(stages):
        _require_boundary_signature(current, stage.source, index, stage.name)
        current = stage.target
    _require_boundary_signature(current, profile.target, None, "target")


def _require_boundary_signature(
    observed: OperationSignature,
    expected: OperationSignature,
    stage_index: int | None,
    stage_name: str,
) -> None:
    if observed.request_contract() != expected.request_contract():
        raise PlanClosureError(
            "request_signature",
            "operation request signatures do not match",
            stage_index=stage_index,
            stage_name=stage_name,
            expected=expected.request_contract(),
            observed=observed.request_contract(),
        )
    if observed.completion_contract() != expected.completion_contract():
        raise PlanClosureError(
            "completion_signature",
            "operation completion signatures do not match",
            stage_index=stage_index,
            stage_name=stage_name,
            expected=expected.completion_contract(),
            observed=observed.completion_contract(),
        )


def _close_capabilities(
    profile: BridgeProfile, stages: tuple[TranslationStage, ...]
) -> CapabilityClosure:
    request = profile.source_request_capabilities
    request_path = [CapabilitySnapshot("source", request)]
    for index, stage in enumerate(stages):
        projection = stage.contract.capabilities.request.apply(request)
        if not projection.ok:
            _raise_capability_gap(
                "request_capability", index, stage.name, projection.gaps[0]
            )
        assert projection.capabilities is not None
        request = projection.capabilities
        request_path.append(CapabilitySnapshot(f"after:{stage.name}", request))
    target_gaps = request.missing(profile.target_request_requirements)
    if target_gaps:
        _raise_capability_gap(
            "request_capability", None, "target", target_gaps[0]
        )

    completion = profile.target_completion_capabilities
    completion_path = [CapabilitySnapshot("target", completion)]
    indexed_stages = tuple(enumerate(stages))
    for index, stage in reversed(indexed_stages):
        projection = stage.contract.capabilities.completion.apply(completion)
        if not projection.ok:
            _raise_capability_gap(
                "completion_capability", index, stage.name, projection.gaps[0]
            )
        assert projection.capabilities is not None
        completion = projection.capabilities
        completion_path.append(
            CapabilitySnapshot(f"before:{stage.name}", completion)
        )
    source_gaps = completion.missing(profile.source_completion_requirements)
    if source_gaps:
        _raise_capability_gap(
            "completion_capability", None, "source", source_gaps[0]
        )
    return CapabilityClosure(tuple(request_path), tuple(completion_path))


def _raise_capability_gap(
    direction: str,
    stage_index: int | None,
    stage_name: str,
    gap: CapabilityGap,
) -> None:
    raise PlanClosureError(
        direction,
        gap.describe(),
        stage_index=stage_index,
        stage_name=stage_name,
        expected=gap.expected,
        observed=gap.observed,
        property_name=gap.name,
    )


def _validate_semantic_loss(
    profile: BridgeProfile, stages: tuple[TranslationStage, ...]
) -> None:
    lossy = {SemanticEffectKind.WEAKEN, SemanticEffectKind.DROP}
    for index, stage in enumerate(stages):
        for effect in stage.contract.semantic_effects:
            if (
                effect.kind in lossy
                and effect.property_name not in profile.allowed_weakening
            ):
                raise PlanClosureError(
                    "semantic_effect",
                    f"{effect.kind.value} of {effect.property_name!r} is not allowed",
                    stage_index=index,
                    stage_name=stage.name,
                    expected="explicit allowed_weakening entry",
                    observed=effect.kind.value,
                    property_name=effect.property_name,
                )
