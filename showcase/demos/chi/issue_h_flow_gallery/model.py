"""Execute and project the five selected CHI Issue H flow-gallery cases."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from showcase.demos.chi.issue_h_flow_gallery.coherence_cases import (
    ADDRESS,
    run_coherence_cases,
)
from showcase.demos.chi.issue_h_flow_gallery.progress_cases import (
    CONTENDER_NODE_ID,
    HOME_NODE_ID,
    LINE_ADDRESS,
    REQUESTER_NODE_ID,
    run_progress_cases,
)
from protocol_model.protocols.amba.chi.issue_h.observation import (
    ChiFlowParticipant,
    ChiOperationObservationStep,
    chi_network_flow_participants,
    chi_network_observation_steps,
    project_chi_transaction_flow,
)
from protocol_model.visualization import TransactionTimeSpaceView


GALLERY_SCHEMA = "protocol-model.showcase.chi-flow-gallery/v1"


@dataclass(frozen=True)
class FlowGalleryCase:
    """One executable scenario and its shared-reference visualization IR."""

    case_id: str
    title: str
    learning_goal: str
    model_boundary: str
    execution: object
    view: TransactionTimeSpaceView

    @property
    def passed(self) -> bool:
        return bool(getattr(self.execution, "passed", False))


_CASE_NARRATIVE = MappingProxyType(
    {
        "clean-read-unique-fanout": (
            "Fan one ReadUnique out to two clean peers, join both Snoop "
            "responses, then commit Unique authority.",
            "Clean MESI authority transfer over a resolved direct topology; "
            "no dirty-owner forwarding or performance claim.",
        ),
        "dirty-peer-clean-unique": (
            "Return shared-dirty peer data on DAT, update Home backing once, "
            "and complete CleanUnique with Comp/CompAck.",
            "Restricted shared-dirty CleanUnique path; not general Owned/SD "
            "or DCT behavior.",
        ),
        "make-unique-local-intent": (
            "Obtain Unique permission with a dataless network lifecycle and "
            "install the requester's local full-line write intent.",
            "MakeUnique plus one modeled local store intent; not partial "
            "write or arbitrary cache-pipeline behavior.",
        ),
        "clean-evict-retry": (
            "Observe RetryAck, Home P-Credit debt/grant, credited reissue, "
            "and the terminal clean Evict completion.",
            "One deterministic successful retry cycle; not general "
            "Retry/error composition, fairness, or liveness proof.",
        ),
        "writeback-snoop-cancel": (
            "Delay an emitted dirty WriteBackFull while a same-line "
            "invalidating Snoop transfers ownership, then close the late "
            "request with zero-byte cancellation data.",
            "Scenario-controlled participant interleaving. Every packet and "
            "state transition is model-produced, but transport hop timing is "
            "not simulated for this case.",
        ),
    }
)


def _network_view(case, *, address: int) -> TransactionTimeSpaceView:
    return project_chi_transaction_flow(
        name=case.title,
        operation_prefix=case.case_id,
        address=address,
        participants=chi_network_flow_participants(case.session),
        steps=chi_network_observation_steps(
            case.emissions,
            case.state_history,
        ),
    )


def _writeback_view(case) -> TransactionTimeSpaceView:
    participants = (
        ChiFlowParticipant(
            REQUESTER_NODE_ID,
            "rn0",
            "RN0 · old dirty owner",
            "requester",
            {"NodeID": f"0x{REQUESTER_NODE_ID:x}"},
        ),
        ChiFlowParticipant(
            HOME_NODE_ID,
            "hn0",
            "HN0 · Home",
            "home",
            {"NodeID": f"0x{HOME_NODE_ID:x}"},
        ),
        ChiFlowParticipant(
            CONTENDER_NODE_ID,
            "rn1",
            "RN1 · CleanUnique requester",
            "requester",
            {"NodeID": f"0x{CONTENDER_NODE_ID:x}"},
        ),
    )
    steps = tuple(
        ChiOperationObservationStep(
            model_step=index,
            label=step.label,
            before=step.before_state,
            after=step.after_state,
            accepted_packet=step.accepted_packet,
            produced=step.produced,
        )
        for index, step in enumerate(case.observation_steps)
    )
    return project_chi_transaction_flow(
        name=case.title,
        operation_prefix=case.case_id,
        address=LINE_ADDRESS,
        participants=participants,
        steps=steps,
    )


def execute_flow_gallery() -> Mapping[str, FlowGalleryCase]:
    """Run all selected cases and build their typed visualization views."""

    coherence = run_coherence_cases()
    progress = run_progress_cases()
    executions = (
        *coherence.values(),
        *progress.values(),
    )
    cases = []
    for execution in executions:
        learning_goal, model_boundary = _CASE_NARRATIVE[
            execution.case_id
        ]
        view = (
            _writeback_view(execution)
            if execution.case_id == "writeback-snoop-cancel"
            else _network_view(
                execution,
                address=(
                    LINE_ADDRESS
                    if execution.case_id == "clean-evict-retry"
                    else ADDRESS
                ),
            )
        )
        cases.append(
            FlowGalleryCase(
                execution.case_id,
                execution.title,
                learning_goal,
                model_boundary,
                execution,
                view,
            )
        )
    return MappingProxyType({case.case_id: case for case in cases})


def flow_gallery_result(
    cases: Mapping[str, FlowGalleryCase],
) -> dict[str, object]:
    """Return the stable, compact machine result for publication."""

    return {
        "schema": GALLERY_SCHEMA,
        "verdict": (
            "PASS" if cases and all(case.passed for case in cases.values())
            else "FAIL"
        ),
        "case_count": len(cases),
        "cases": {
            case_id: {
                "title": case.title,
                "verdict": case.execution.verdict.value,
                "assertions": dict(case.execution.assertions),
                "message_count": len(case.view.messages),
                "state_change_count": len(case.view.state_changes),
                "causal_edge_count": len(case.view.causal_edges),
                "operation_refs": sorted(
                    {
                        message.operation_ref
                        for message in case.view.messages
                    }
                ),
                "time_basis": case.view.time_basis.value,
                "learning_goal": case.learning_goal,
                "model_boundary": case.model_boundary,
            }
            for case_id, case in cases.items()
        },
    }


__all__ = [
    "FlowGalleryCase",
    "GALLERY_SCHEMA",
    "execute_flow_gallery",
    "flow_gallery_result",
]
