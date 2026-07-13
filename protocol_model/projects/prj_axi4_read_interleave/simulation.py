"""Run the project and publish its report artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protocol_model.evidence import (
    ArtifactBundle,
    ConstraintEvidence,
    constraints_from_instances,
    default_run_directory,
    format_execution_dot,
    synthesize_axi_waveform,
    to_wavejson,
)

from .evidence import format_run, report_html, topology_dot
from .project import AxiReadInterleaveProject, AxiReadInterleaveRun


DEFAULT_SIM_DIR = default_run_directory("prj_axi4_read_interleave")


@dataclass(frozen=True)
class AxiReadInterleaveSimulation:
    directory: Path
    report: Path
    text_report: Path
    waveform: Path
    network: Path
    causality: Path
    run: AxiReadInterleaveRun
    project: AxiReadInterleaveProject


def build_simulation(directory: str | Path | None = None) -> AxiReadInterleaveSimulation:
    target = DEFAULT_SIM_DIR if directory is None else Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    project = AxiReadInterleaveProject()
    run = project.run()
    assert project.spec is not None and project.protocol is not None
    bundle = ArtifactBundle(project.name, target)

    waveform = synthesize_axi_waveform(
        project.spec, run.trace, seed=97, stall_probability=0.25
    )
    wave_svg_path = bundle.render_wave(
        "waveform",
        to_wavejson(
            waveform,
            title="AXI4 cross-ID read interleaving",
            hide_inactive_channels=True,
        ),
        kind="waveform",
    )
    network_svg_path = bundle.render_dot(
        "network", topology_dot(project.snapshot()), kind="network"
    )
    causality_svg_path = bundle.render_dot(
        "causality",
        format_execution_dot(
            run.trace,
            title="AXI4 read interleaving causal chain",
            address_width=int(project.spec.parameters["address_width"]),
            data_width=int(project.spec.parameters["data_width"]),
        ),
        kind="causality",
    )
    bundle.write_json(
        "trace.json",
        {
            "events": [
                {
                    "index": index,
                    "kind": event.kind,
                    "key": event.key,
                    "payload": dict(event.payload),
                }
                for index, event in enumerate(run.trace.events)
            ],
            "causal_edges": sorted(run.trace.causal_graph.edges),
        },
        kind="trace",
    )
    extra = tuple(
        ConstraintEvidence(
            id=item.name,
            source="TEST",
            target="mutation",
            rule=item.detail,
            foundation=item.rule,
            status="verified" if item.matched else "mismatch",
            instances=(project.protocol.qualified_name,),
            witness=f"expected={item.expected.value}, observed={item.observed.value}",
        )
        for item in run.checks
    )
    constraints = constraints_from_instances((project.protocol,), extra=extra)
    _, markdown_path = bundle.write_constraints(constraints)
    text_path = bundle.write_text(
        "run.txt", format_run(run) + "\n", kind="text_report"
    )
    html_path = bundle.write_text(
        "report.html",
        report_html(run, project.snapshot()),
        kind="html_report",
        media_type="text/html",
    )
    cases = (
        {"name": "cross_id_out_of_order", "expected": "PASS", "observed": run.verdict.value},
        *(
            {
                "name": item.name,
                "expected": item.expected.value,
                "observed": item.observed.value,
            }
            for item in run.checks
        ),
    )
    project.publish(*(str(path) for path in bundle.artifact_paths))
    bundle.finalize(
        verdict=run.verdict.value,
        protocol_instances=(project.protocol,),
        cases=cases,
        state=project.snapshot().state,
    )
    return AxiReadInterleaveSimulation(
        target,
        html_path,
        markdown_path,
        wave_svg_path,
        network_svg_path,
        causality_svg_path,
        run,
        project,
    )
