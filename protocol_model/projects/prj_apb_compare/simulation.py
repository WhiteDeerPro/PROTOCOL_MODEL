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

from .evidence import report_html, topology_dot, trace_dot
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
        case_name = f"legal_apb{version}"
        bundle.render_wave(
            "waveform",
            apb_to_wavejson(project.configs[version], trace),
            kind="waveform",
            case=case_name,
        )
        bundle.render_dot(
            "causality",
            trace_dot(trace, title=f"APB{version} legal sample flow"),
            kind="causality",
            case=case_name,
        )
        bundle.write_json(
            "trace.json",
            {
                "cycles": len(trace.samples),
                "samples": trace.samples,
                "transfers": trace.transfers,
            },
            kind="trace",
            case=case_name,
        )
    negative_case = "request_stability_mutation"
    bundle.render_wave(
        "waveform",
        apb_to_wavejson(
            project.configs[4],
            run.mutation_trace,
            title="APB4 negative: PADDR changes during ACCESS",
        ),
        kind="waveform",
        case=negative_case,
    )
    bundle.render_dot(
        "causality",
        trace_dot(
            run.mutation_trace,
            title="APB4 request-stability violation",
            fault_rule=run.mutation_rule,
        ),
        kind="causality",
        case=negative_case,
    )
    bundle.write_json(
        "trace.json",
        {
            "cycles": len(run.mutation_trace.samples),
            "samples": run.mutation_trace.samples,
            "transfers": run.mutation_trace.transfers,
            "fault": run.mutation_rule,
        },
        kind="trace",
        case=negative_case,
    )
    bundle.render_dot("state", apb_state_dot(), kind="state")
    network_svg = bundle.render_dot(
        "network", topology_dot(project.snapshot()), kind="network"
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
            {"name": "legal_apb3", "expected": "PASS", "observed": "PASS"},
            {"name": "legal_apb4", "expected": "PASS", "observed": "PASS"},
            {
                "name": "request_stability_mutation",
                "expected": "FAIL",
                "observed": "FAIL" if run.mutation_rule != "NO VIOLATION" else "PASS",
            },
        ),
        state=project.snapshot().state,
    )
    return ApbComparisonSimulation(target, report, network_svg, run, project)
