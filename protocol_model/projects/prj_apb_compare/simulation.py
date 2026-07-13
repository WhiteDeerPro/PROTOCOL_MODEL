"""APB Project artifact publication."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protocol_model.evidence import (
    ArtifactBundle,
    ConstraintEvidence,
    constraints_from_instances,
    default_run_directory,
)
from protocol_model.protocols.apb import apb_state_dot, apb_to_wavejson

from .evidence import report_html, topology_dot
from .project import ApbComparisonProject, ApbComparisonRun


DEFAULT_SIM_DIR = default_run_directory("prj_apb_compare")


@dataclass(frozen=True)
class ApbComparisonSimulation:
    directory: Path
    report: Path
    network: Path
    run: ApbComparisonRun
    project: ApbComparisonProject


def build_simulation(
    directory: str | Path | None = None,
    *,
    transactions: int = 4,
    seed: int = 41,
) -> ApbComparisonSimulation:
    target = DEFAULT_SIM_DIR if directory is None else Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    project = ApbComparisonProject()
    run = project.run(transactions=transactions, seed=seed)
    bundle = ArtifactBundle(project.name, target)
    for version, trace in run.traces.items():
        bundle.render_wave(
            f"waveform.apb{version}",
            apb_to_wavejson(project.configs[version], trace),
            kind=f"waveform_apb{version}",
        )
    bundle.render_dot("state", apb_state_dot(), kind="state")
    network_svg = bundle.render_dot(
        "network", topology_dot(project.snapshot()), kind="network"
    )
    bundle.write_json(
        "trace.json",
        {
            f"apb{version}": {
                "cycles": len(trace.samples),
                "transfers": [
                    {
                        "kind": event.kind,
                        "key": event.key,
                        "payload": dict(event.payload),
                    }
                    for event in trace.transfers
                ],
            }
            for version, trace in run.traces.items()
        },
        kind="trace",
    )
    mutation = ConstraintEvidence(
        id="mutation_request_stability",
        source="TEST",
        target="APB4.PADDR",
        rule="change PADDR during ACCESS",
        foundation=run.mutation_rule,
        status="verified" if run.verdict.value == "PASS" else "mismatch",
        instances=(project.protocols[4].qualified_name,),
        witness=run.mutation_rule,
    )
    constraints = constraints_from_instances(
        tuple(project.protocols.values()), extra=(mutation,)
    )
    bundle.write_constraints(constraints)
    report = bundle.write_text(
        "report.html",
        report_html(run, project, transactions),
        kind="html_report",
        media_type="text/html",
    )
    project.publish(*(str(path) for path in bundle.artifact_paths))
    bundle.finalize(
        verdict=run.verdict.value,
        protocol_instances=tuple(project.protocols.values()),
        cases=(
            {"name": "generated_legal", "expected": "PASS", "observed": "PASS"},
            {
                "name": "request_stability_mutation",
                "expected": "FAIL",
                "observed": "FAIL" if run.mutation_rule != "NO VIOLATION" else "PASS",
            },
        ),
        state=project.snapshot().state,
    )
    return ApbComparisonSimulation(target, report, network_svg, run, project)
