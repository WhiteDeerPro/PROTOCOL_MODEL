"""Artifact publication for the two-link AXI4 bridge Project."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from protocol_model.evidence import (
    ArtifactBundle,
    ConstraintEvidence,
    constraints_from_instances,
    default_run_directory,
    synthesize_axi_network_timeline,
    synthesize_axi_attempt_waveform,
    to_wavejson,
)

from .evidence import (
    axi_read_chain_dot,
    axi_fault_dot,
    axi_read_chain_report_html,
    axi_read_network_dot,
)
from .project import AxiReadCase, AxiReadNetworkProject, AxiReadNetworkRun


DEFAULT_SIM_DIR = default_run_directory("prj_axi4_read_bridge")


@dataclass(frozen=True)
class AxiReadBridgeSimulation:
    directory: Path
    report: Path
    legal: AxiReadNetworkRun
    rejected: AxiReadNetworkRun
    legal_project: AxiReadNetworkProject
    rejected_project: AxiReadNetworkProject


def build_simulation(
    directory: str | Path | None = None,
) -> AxiReadBridgeSimulation:
    target = DEFAULT_SIM_DIR if directory is None else Path(directory)
    project = AxiReadNetworkProject()
    legal = project.run_case(AxiReadCase())
    rejected_project = AxiReadNetworkProject()
    rejected = rejected_project.run_case(
        AxiReadCase(
            name="crossing_4kb",
            address=0xFF4,
            expect_violation=True,
        )
    )

    bundle = ArtifactBundle(project.name, target)
    bundle.render_dot(
        "causality",
        axi_read_chain_dot(legal),
        kind="causality",
        case="legal_4kb_edge",
    )
    bundle.render_dot(
        "network", axi_read_network_dot(project.snapshot()), kind="network"
    )
    for stem, location, instance in (
        ("axi-a", "AXI-A", project.link_a_protocol),
        ("axi-b", "AXI-B", project.link_b_protocol),
    ):
        assert instance is not None
        waveform = synthesize_axi_network_timeline(
            instance.spec, legal.trace.events, location=location
        )
        bundle.render_wave(
            f"waveform.{stem}",
            to_wavejson(
                waveform,
                title=f"{location} shared network timeline",
                hide_inactive_channels=True,
            ),
            kind=f"waveform_{stem}",
            case="legal_4kb_edge",
        )
    if rejected.attempted_event is None or rejected.fault is None:
        raise RuntimeError("crossing_4kb did not retain its rejected input")
    rejected_waveform = synthesize_axi_attempt_waveform(
        project.spec_a, rejected.attempted_event
    )
    bundle.render_wave(
        "waveform",
        to_wavejson(
            rejected_waveform,
            title="Negative AXI4 AR burst crossing 4KB",
            hide_inactive_channels=True,
        ),
        kind="waveform",
        case="crossing_4kb",
    )
    bundle.render_dot(
        "causality",
        axi_fault_dot(rejected, title="4KB boundary violation"),
        kind="causality",
        case="crossing_4kb",
    )
    bundle.write_json(
        "trace.json",
        {
            "events": [
                {
                    "index": index,
                    "location": located.location,
                    "kind": located.event.kind,
                    "key": located.event.key,
                    "payload": dict(located.event.payload),
                }
                for index, located in enumerate(legal.trace.events)
            ],
            "causal_edges": sorted(legal.trace.causal_graph.edges),
            "milestones": [
                {
                    "name": item.name,
                    "link_a_pending": item.link_a_pending,
                    "bridge_pending": item.bridge_pending,
                    "link_b_pending": item.link_b_pending,
                }
                for item in legal.milestones
            ],
        },
        kind="trace",
        case="legal_4kb_edge",
    )
    bundle.write_json(
        "trace.json",
        {
            "attempted_event": rejected.attempted_event,
            "fault": rejected.fault,
            "milestones": rejected.milestones,
        },
        kind="trace",
        case="crossing_4kb",
    )
    assert project.link_a_protocol is not None
    assert project.link_b_protocol is not None
    constraints = constraints_from_instances(
        (project.link_a_protocol, project.link_b_protocol),
        extra=(
            ConstraintEvidence(
                id="crossing_4kb_mutation",
                source="TEST",
                target="AXI-A.AR.addr/len/size",
                rule="configure a burst that crosses a 4KB boundary",
                foundation="EventConstraint",
                status="verified" if rejected.fault is not None else "mismatch",
                instances=(project.link_a_protocol.qualified_name,),
                witness=rejected.fault.rule if rejected.fault else "NO FAULT",
            ),
        ),
    )
    bundle.write_constraints(constraints)
    report_path = bundle.write_text(
        "report.html",
        axi_read_chain_report_html(legal, project.snapshot(), rejected),
        kind="html_report",
        media_type="text/html",
    )
    project.publish(*(str(path) for path in bundle.artifact_paths))
    bundle.finalize(
        verdict=(
            "PASS"
            if legal.verdict.value == "PASS" and rejected.fault is not None
            else "FAIL"
        ),
        protocol_instances=(project.link_a_protocol, project.link_b_protocol),
        cases=(
            {
                "name": "legal_4kb_edge",
                "expected": "PASS",
                "observed": legal.verdict.value,
            },
            {
                "name": "crossing_4kb",
                "expected": "FAIL",
                "observed": rejected.verdict.value,
            },
        ),
        state=project.snapshot().state,
    )
    return AxiReadBridgeSimulation(
        target,
        report_path,
        legal,
        rejected,
        project,
        rejected_project,
    )
