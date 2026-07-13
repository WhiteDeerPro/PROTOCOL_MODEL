"""Project-owned simulation plan and output construction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protocol_model.evidence import (
    ArtifactBundle,
    ConstraintEvidence,
    constraints_from_instances,
    default_run_directory,
)

from .evidence import (
    ready_valid_event_dot,
    ready_valid_sink_report_html,
    ready_valid_topology_dot,
    ready_valid_wavejson,
)
from .project import ReadyValidSinkCase, ReadyValidSinkProject, ReadyValidSinkRun


DEFAULT_SIM_DIR = default_run_directory("prj_ready_valid_sink")


@dataclass(frozen=True)
class ReadyValidSinkSimulation:
    directory: Path
    report: Path
    legal: ReadyValidSinkRun
    mutation: ReadyValidSinkRun
    legal_phase: str
    mutation_phase: str
    files: tuple[Path, ...]


def build_simulation(
    directory: str | Path | None = None,
) -> ReadyValidSinkSimulation:
    """Run the Project's default plan and publish every simulation artifact."""

    target = DEFAULT_SIM_DIR if directory is None else Path(directory)
    legal_project = ReadyValidSinkProject()
    legal = legal_project.run_case(
        ReadyValidSinkCase("legal_stall", (0x12, 0x34))
    )
    mutation_project = ReadyValidSinkProject()
    mutation = mutation_project.run_case(
        ReadyValidSinkCase(
            "changed_while_stalled",
            (0x12,),
            mutate_stalled_payload=True,
            expect_violation=True,
        )
    )

    bundle = ArtifactBundle(legal_project.name, target)
    for case_name, run, title in (
        ("legal_stall", legal, "Legal ready-valid stall and transfers"),
        ("changed_while_stalled", mutation, "Payload mutation while stalled"),
    ):
        bundle.render_wave(
            "waveform",
            ready_valid_wavejson(run, title=title),
            kind="waveform",
            case=case_name,
        )
        bundle.render_dot(
            "causality",
            ready_valid_event_dot(run, title=title),
            kind="causality",
            case=case_name,
        )
        bundle.write_json(
            "trace.json",
            {
                "verdict": run.verdict.value,
                "samples": [
                    {
                        "reset": item.asserted,
                        "cycle": item.observation.cycle,
                        "valid": item.observation.valid,
                        "ready": item.observation.ready,
                        "event": (
                            None
                            if item.observation.event is None
                            else {
                                "kind": item.observation.event.kind,
                                "key": item.observation.event.key,
                                "payload": dict(item.observation.event.payload),
                            }
                        ),
                    }
                    for item in run.observations
                ],
                "transfers": [
                    {
                        "kind": event.kind,
                        "key": event.key,
                        "payload": dict(event.payload),
                    }
                    for event in run.transfers
                ],
                "fault": run.fault.rule if run.fault else None,
            },
            kind="trace",
            case=case_name,
        )
    bundle.render_dot(
        "network",
        ready_valid_topology_dot(legal_project.snapshot()),
        kind="network",
    )
    assert legal_project.protocol_instance is not None
    constraints = constraints_from_instances(
        (legal_project.protocol_instance,),
        extra=(
            ConstraintEvidence(
                id="legal_handshake_witness",
                source="TEST",
                target="DATA.VALID, DATA.READY",
                rule="a transfer occurs only when VALID and READY are both asserted",
                foundation="legal_stall",
                status="verified" if legal.verdict.value == "PASS" else "mismatch",
                instances=(legal_project.protocol_instance.qualified_name,),
                witness=f"accepted_transfers={len(legal.transfers)}",
            ),
            ConstraintEvidence(
                id="stall_payload_mutation",
                source="TEST",
                target="DATA.payload",
                rule="change payload while VALID=1 and READY=0",
                foundation="negative mutation",
                status="verified" if mutation.fault is not None else "mismatch",
                instances=(legal_project.protocol_instance.qualified_name,),
                witness=mutation.fault.rule if mutation.fault else "NO FAULT",
            ),
        ),
    )
    bundle.write_constraints(constraints)
    report = bundle.write_text(
        "report.html",
        ready_valid_sink_report_html(
            legal,
            legal_project.snapshot(),
            mutation,
            mutation_project.snapshot(),
        ),
        kind="html_report",
        media_type="text/html",
    )
    legal_project.publish(*(str(path) for path in bundle.artifact_paths))
    bundle.finalize(
        verdict=(
            "PASS"
            if legal.verdict.value == "PASS" and mutation.fault is not None
            else "FAIL"
        ),
        protocol_instances=(legal_project.protocol_instance,),
        cases=(
            {
                "name": "legal_stall",
                "expected": "PASS",
                "observed": legal.verdict.value,
            },
            {
                "name": "changed_while_stalled",
                "expected": "FAIL",
                "observed": mutation.verdict.value,
            },
        ),
        state=legal_project.snapshot().state,
    )
    return ReadyValidSinkSimulation(
        target,
        report,
        legal,
        mutation,
        legal_project.phase.value,
        mutation_project.phase.value,
        bundle.artifact_paths,
    )
