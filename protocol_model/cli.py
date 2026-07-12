"""Small executable views for inspecting protocol-model behavior."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
from random import Random
import subprocess
from typing import Sequence

from protocol_model.patterns import ReadyValidSample, ResetSample
from protocol_model.evidence import (
    format_cardinality_run,
    format_correlated_dot,
    format_correlated_run,
    format_execution_dot,
    format_ready_valid_run,
    session_report_html,
    synthesize_axi_network_timeline,
    synthesize_axi_waveform,
    to_wavejson,
)
from protocol_model.projects.prj_axi4_read_bridge import (
    AxiReadCase,
    AxiReadNetworkProject,
    axi_read_chain_dot,
    axi_read_chain_report_html,
    DEFAULT_SIM_DIR as AXI_READ_BRIDGE_SIM_DIR,
)
from protocol_model.projects.prj_ready_valid_sink import (
    DEFAULT_SIM_DIR as READY_VALID_SINK_SIM_DIR,
    build_simulation as build_ready_valid_sink_simulation,
)
from protocol_model.protocols.apb import (
    ApbConfig,
    apb_report_html,
    apb_state_dot,
    apb_to_wavejson,
    build_apb4_spec,
    generate_apb_trace,
)
from protocol_model.protocols.axi4 import (
    Axi4Cycle,
    Axi4RandomScheduler,
    Axi4SignalSession,
    byte_lane_mask,
    build_axi4_spec,
)


def _different_event(space, original, rng):
    for _ in range(10_000):
        candidate = space.sample(rng)
        if (
            candidate.key != original.key
            or dict(candidate.payload) != dict(original.payload)
        ):
            return candidate
    raise RuntimeError("could not sample a distinct event for mutation")


def _waveform(channel_name: str, violation: str, seed: int):
    spec = build_axi4_spec()
    channel = spec.channel(channel_name)
    rng = Random(seed)
    event = channel.transfer.sample(rng)
    samples = [
        ResetSample(
            True,
            ReadyValidSample(0, False, False, clock="aclk", source="virtual_axi"),
        ),
        ResetSample(
            False,
            ReadyValidSample(1, False, True, clock="aclk", source="virtual_axi"),
        ),
        ResetSample(
            False,
            ReadyValidSample(2, True, False, event, "aclk", "virtual_axi"),
        ),
    ]
    if violation == "valid":
        final = ReadyValidSample(3, False, True, clock="aclk", source="virtual_axi")
    elif violation == "payload":
        changed = _different_event(channel.transfer, event, rng)
        final = ReadyValidSample(3, True, True, changed, "aclk", "virtual_axi")
    elif violation == "reset":
        samples = []
        final = ReadyValidSample(0, True, True, event, "aclk", "virtual_axi")
    else:
        final = ReadyValidSample(3, True, True, event, "aclk", "virtual_axi")
    samples.append(ResetSample(violation == "reset", final))
    result = channel.observation_model.run(samples)
    return samples, result


def _read_transaction(violation: str, seed: int):
    spec = build_axi4_spec()
    monitor = spec.transaction_models["read"]
    rng = Random(seed)
    ar = spec.channel("AR").transfer.sample_constrained(
        rng,
        payload={"len": 3, "size": 2, "burst": "INCR"},
    )
    events = [ar]
    state = monitor.step(monitor.initial_state(), ar).state
    while state.pending:
        event = monitor.sample_legal(state, rng, allow_begin=False)
        events.append(event)
        state = monitor.step(state, event).state

    if violation == "early-last":
        events[1] = replace(events[1], payload={**events[1].payload, "last": True})
    elif violation == "missing-last":
        events[-1] = replace(events[-1], payload={**events[-1].payload, "last": False})
    elif violation == "orphan":
        events = [events[1]]
    return events, monitor.run(events), monitor


def _write_transaction(violation: str, seed: int):
    spec = build_axi4_spec()
    monitor = spec.transaction_models["write"]
    rng = Random(seed)
    aw = spec.channel("AW").transfer.sample_constrained(
        rng, payload={"len": 3, "size": 2, "burst": "INCR"}
    )
    events = [aw]
    state = monitor.step(monitor.initial_state(), aw).state
    for _ in range(4):
        event = monitor.sample_data(state, rng)
        events.append(event)
        state = monitor.step(state, event).state
    response = monitor.sample_completion(state, rng)
    events.append(response)
    if violation == "early-wlast":
        events[1] = replace(events[1], payload={**events[1].payload, "last": True})
    elif violation == "b-before-data":
        events = [events[0], events[-1], *events[1:-1]]
    return events, monitor.run(events), monitor


def _write_graph(directory: str, events, monitor) -> tuple[Path, Path]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    dot_path = target / "axi4_write.dot"
    svg_path = target / "axi4_write.svg"
    dot_path.write_text(
        format_correlated_dot(
            events,
            descriptor_kind=monitor.descriptor.kind,
            data_kind=monitor.data.kind,
            completion_kind=monitor.completion.kind,
            title="AXI4 write causality",
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ("dot", "-Tsvg", str(dot_path), "-o", str(svg_path)), check=True
    )
    return dot_path, svg_path


def _session_summary(trace, verdict: str, cycles: int) -> str:
    incoming = {index: [] for index in range(len(trace.events))}
    for before, after in trace.causal_graph.edges:
        incoming[after].append(before)
    step_of = {
        event_index: step_index
        for step_index, step in enumerate(trace.steps)
        for event_index in step
    }
    lines = [
        "UNIFIED AXI4 SESSION",
        f"  events={len(trace.events)} steps={len(trace.steps)} "
        f"max_parallel={max(map(len, trace.steps), default=0)} "
        f"causal_edges={len(trace.causal_graph.edges)} cycles={cycles}",
        f"  waveform_replay={verdict}",
        "",
        "EVENT / DIRECT PREDECESSORS",
    ]
    for index, event in enumerate(trace.events):
        predecessors = ",".join(str(item) for item in sorted(incoming[index])) or "-"
        lines.append(
            f"  [{index:02d}] step={step_of[index]:02d} pred={predecessors:<7} {event.short()}"
        )
    return "\n".join(lines)


def _write_session_artifacts(
    directory: str, trace, wavejson, spec, replay_verdict: str, cycle_count: int
) -> tuple[Path, ...]:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    wavejson_path = target / "axi4_session.wave.json"
    wave_svg_path = target / "axi4_session.wave.svg"
    graph_dot_path = target / "axi4_session.causality.dot"
    graph_svg_path = target / "axi4_session.causality.svg"
    report_path = target / "index.html"
    wavejson_path.write_text(json.dumps(wavejson, indent=2), encoding="utf-8")
    rendered = subprocess.run(
        ("node_modules/.bin/wavedrom", "--input", str(wavejson_path)),
        check=True,
        capture_output=True,
        text=True,
    )
    wave_svg_path.write_text(rendered.stdout, encoding="utf-8")
    graph_dot_path.write_text(
        format_execution_dot(
            trace,
            title="AXI4 unified session causality",
            address_width=int(spec.parameters["address_width"]),
            data_width=int(spec.parameters["data_width"]),
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ("dot", "-Tsvg", str(graph_dot_path), "-o", str(graph_svg_path)),
        check=True,
    )
    report_path.write_text(
        session_report_html(
            spec,
            event_count=len(trace.events),
            edge_count=len(trace.causal_graph.edges),
            cycle_count=cycle_count,
            step_count=len(trace.steps),
            max_parallel=max(map(len, trace.steps), default=0),
            replay_verdict=replay_verdict,
        ),
        encoding="utf-8",
    )
    return wavejson_path, wave_svg_path, graph_dot_path, graph_svg_path, report_path


def _axi_cycle(spec, cycle, *, active=None, reset=False):
    active = active or {}
    return Axi4Cycle(
        {
            name: ResetSample(
                reset,
                ReadyValidSample(
                    cycle,
                    name in active,
                    name in active,
                    active.get(name),
                    "aclk",
                    "constraint_witness",
                ),
            )
            for name in spec.channels
        }
    )


def _constraint_witness(seed: int) -> str:
    spec = build_axi4_spec()
    rng = Random(seed)
    signal = Axi4SignalSession(spec=spec)

    b_event = spec.channel("B").transfer.sample(rng)
    premature_b = signal.step(
        signal.initial_state(), _axi_cycle(spec, 0, active={"B": b_event})
    )

    aw = spec.channel("AW").transfer.sample_constrained(
        rng,
        payload={"addr": 1, "len": 0, "size": 2, "burst": "INCR"},
    )
    write = spec.transaction_models["write"]
    write_state = write.step(write.initial_state(), aw).state
    illegal_w = spec.channel("W").transfer.sample_constrained(
        rng, payload={"strb": 0x10, "last": True}
    )
    illegal_strobe = write.step(write_state, illegal_w)
    allowed = byte_lane_mask(aw, 0, bus_bytes=8)

    ar = spec.channel("AR").transfer.sample_constrained(
        rng, payload={"len": 0, "size": 2, "burst": "INCR"}
    )
    before_reset = signal.step(
        signal.initial_state(), _axi_cycle(spec, 0, active={"AR": ar})
    )
    pending_before = len(before_reset.state.protocol_state.state_of("read").pending)
    after_reset = signal.step(before_reset.state, _axi_cycle(spec, 1, reset=True))
    pending_after = len(after_reset.state.protocol_state.state_of("read").pending)

    return "\n".join(
        (
            "AXI4 CONSTRAINT WITNESSES",
            "",
            "[1] Requirement: BVALID requires a previously joined AW/W completion",
            "    Mutation: assert BVALID in the initial state",
            f"    Observed: {premature_b.fault.rule if premature_b.fault else 'NO FAULT'}",
            "",
            "[2] Requirement: WSTRB is a subset of the beat byte-lane mask",
            "    Context: ADDR=1 SIZE=2 bus=8 bytes, first beat",
            f"    Allowed mask: 0x{allowed:x}; mutation WSTRB: 0x10",
            f"    Observed: {illegal_strobe.fault.rule if illegal_strobe.fault else 'NO FAULT'}",
            "",
            "[3] Requirement: asserted ARESETn clears the transaction epoch",
            f"    Pending reads: {pending_before} before reset -> {pending_after} after reset",
        )
    )


def _render_wavedrom(source_path: Path, target_path: Path) -> None:
    rendered = subprocess.run(
        ("node_modules/.bin/wavedrom", "--input", str(source_path)),
        check=True,
        capture_output=True,
        text=True,
    )
    target_path.write_text(rendered.stdout, encoding="utf-8")


def _write_axi_read_network(directory: str, *, crossing: bool = False):
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    project = AxiReadNetworkProject()
    run = project.run_case(
        AxiReadCase(
            name="crossing_4kb" if crossing else "legal_4kb_edge",
            address=0xFF4 if crossing else 0xFF0,
            expect_violation=crossing,
        )
    )
    if crossing:
        return run, None, project.snapshot()
    dot_path = target / "axi_read_chain.dot"
    svg_path = target / "axi_read_chain.svg"
    report_path = target / "index.html"
    dot_path.write_text(axi_read_chain_dot(run), encoding="utf-8")
    subprocess.run(("dot", "-Tsvg", str(dot_path), "-o", str(svg_path)), check=True)
    for stem, location, spec in (
        ("axi_a", "AXI-A", project.spec_a),
        ("axi_b", "AXI-B", project.spec_b),
    ):
        waveform = synthesize_axi_network_timeline(
            spec, run.trace.events, location=location
        )
        json_path = target / f"{stem}.wave.json"
        wave_svg = target / f"{stem}.wave.svg"
        json_path.write_text(
            json.dumps(
                to_wavejson(
                    waveform,
                    title=f"{location} shared network timeline",
                    hide_inactive_channels=True,
                ),
                indent=2,
            ),
            encoding="utf-8",
        )
        _render_wavedrom(json_path, wave_svg)
    project.publish(
        str(dot_path),
        str(svg_path),
        str(target / "axi_a.wave.svg"),
        str(target / "axi_b.wave.svg"),
        str(report_path),
    )
    report_path.write_text(
        axi_read_chain_report_html(run, project.snapshot()), encoding="utf-8"
    )
    return run, report_path, project.snapshot()


def _write_apb_artifacts(directory: str, *, transactions: int, seed: int):
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    traces = {}
    for version in (3, 4):
        config = ApbConfig(version)
        trace = generate_apb_trace(
            config, transactions=transactions, seed=seed + version
        )
        traces[version] = trace
        json_path = target / f"apb{version}.wave.json"
        svg_path = target / f"apb{version}.wave.svg"
        json_path.write_text(
            json.dumps(apb_to_wavejson(config, trace), indent=2), encoding="utf-8"
        )
        _render_wavedrom(json_path, svg_path)

    spec4 = build_apb4_spec()
    mutated = list(traces[4].samples)
    setup_index = next(
        index
        for index, sample in enumerate(mutated)
        if sample.psel and not sample.penable
    )
    access = mutated[setup_index + 1]
    mutated[setup_index + 1] = replace(
        access, paddr=access.paddr ^ 1
    )
    violation_result = spec4.channel("APB").observation_model.run(mutated)
    violation = (
        violation_result.violations[0].rule
        if violation_result.violations
        else "NO VIOLATION"
    )

    dot_path = target / "apb.state.dot"
    state_svg = target / "apb.state.svg"
    dot_path.write_text(apb_state_dot(), encoding="utf-8")
    subprocess.run(("dot", "-Tsvg", str(dot_path), "-o", str(state_svg)), check=True)
    report = target / "index.html"
    report.write_text(
        apb_report_html(
            apb3_cycles=len(traces[3].samples),
            apb4_cycles=len(traces[4].samples),
            transactions=transactions,
            violation=violation,
        ),
        encoding="utf-8",
    )
    return traces, violation, report

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="protocol_model")
    subparsers = parser.add_subparsers(dest="command", required=True)
    waveform = subparsers.add_parser(
        "waveform", help="print a virtual AXI4 ready/valid waveform and validation"
    )
    waveform.add_argument("--channel", choices=("AW", "W", "B", "AR", "R"), default="AW")
    waveform.add_argument(
        "--violation", choices=("none", "valid", "payload", "reset"), default="none"
    )
    waveform.add_argument("--seed", type=int, default=7)
    read = subparsers.add_parser(
        "read-transaction", help="print AXI4 AR/R cardinality validation"
    )
    read.add_argument(
        "--violation",
        choices=("none", "early-last", "missing-last", "orphan"),
        default="none",
    )
    read.add_argument("--seed", type=int, default=7)
    write = subparsers.add_parser(
        "write-transaction", help="print AXI4 AW/W/B correlation semantics"
    )
    write.add_argument(
        "--violation", choices=("none", "early-wlast", "b-before-data"), default="none"
    )
    write.add_argument("--seed", type=int, default=7)
    write.add_argument(
        "--graph-dir", help="write an organized Graphviz DOT and SVG pair"
    )
    session = subparsers.add_parser(
        "session", help="generate, lower, replay, and visualize one unified AXI4 session"
    )
    session.add_argument("--reads", type=int, default=2)
    session.add_argument("--writes", type=int, default=2)
    session.add_argument("--max-beats", type=int, default=4)
    session.add_argument("--seed", type=int, default=19)
    session.add_argument(
        "--artifacts-dir", default="artifacts/axi4_session"
    )
    constraints = subparsers.add_parser(
        "constraint-witness", help="show minimal witnesses for newly modeled AXI rules"
    )
    constraints.add_argument("--seed", type=int, default=31)
    apb = subparsers.add_parser(
        "apb", help="generate APB3/APB4 two-phase waveforms and comparison report"
    )
    apb.add_argument("--transactions", type=int, default=4)
    apb.add_argument("--seed", type=int, default=41)
    apb.add_argument("--artifacts-dir", default="artifacts/apb")
    network = subparsers.add_parser(
        "axi-read-network", help="run the two-link AXI read bridge experiment"
    )
    network.add_argument("--sim-dir", default=str(AXI_READ_BRIDGE_SIM_DIR))
    ready_valid_sink = subparsers.add_parser(
        "ready-valid-sink",
        help="run Source → ready-valid protocol → Sink project cases",
    )
    ready_valid_sink.add_argument(
        "--sim-dir", default=str(READY_VALID_SINK_SIM_DIR)
    )
    args = parser.parse_args(argv)

    if args.command == "waveform":
        samples, result = _waveform(args.channel, args.violation, args.seed)
        print(format_ready_valid_run(samples, result))
        return 1 if result.violations else 0
    if args.command == "read-transaction":
        events, result, monitor = _read_transaction(args.violation, args.seed)
        print(
            format_cardinality_run(
                events,
                result,
                begin_kind=monitor.begin.kind,
                beat_kind=monitor.beat.kind,
            )
        )
        return 1 if result.violations else 0
    if args.command == "write-transaction":
        events, result, monitor = _write_transaction(args.violation, args.seed)
        print(
            format_correlated_run(
                events,
                result,
                descriptor_kind=monitor.descriptor.kind,
                data_kind=monitor.data.kind,
                completion_kind=monitor.completion.kind,
            )
        )
        if args.graph_dir:
            dot_path, svg_path = _write_graph(args.graph_dir, events, monitor)
            print(f"\nGRAPHVIZ\n  dot={dot_path}\n  svg={svg_path}")
        return 1 if result.violations else 0
    if args.command == "session":
        scheduler = Axi4RandomScheduler(
            seed=args.seed, max_beats=args.max_beats
        )
        trace = scheduler.generate(reads=args.reads, writes=args.writes)
        waveform = synthesize_axi_waveform(
            scheduler.spec, trace, seed=args.seed + 1
        )
        replay = scheduler.spec.open_session().run(waveform.transfers)
        cycles = len(next(iter(waveform.samples.values())))
        print(_session_summary(trace, replay.verdict.value, cycles))
        paths = _write_session_artifacts(
            args.artifacts_dir,
            trace,
            to_wavejson(waveform, title="AXI4 unified random session"),
            scheduler.spec,
            replay.verdict.value,
            cycles,
        )
        print("\nARTIFACTS")
        for path in paths:
            print(f"  {path}")
        return 0 if replay.verdict.value == "PASS" else 1
    if args.command == "constraint-witness":
        print(_constraint_witness(args.seed))
        return 0
    if args.command == "apb":
        traces, violation, report = _write_apb_artifacts(
            args.artifacts_dir,
            transactions=args.transactions,
            seed=args.seed,
        )
        print("APB3 / APB4 SEMANTIC WITNESS")
        for version in (3, 4):
            print(
                f"  APB{version}: cycles={len(traces[version].samples)} "
                f"transfers={len(traces[version].transfers)}"
            )
        print(f"  mutation=request address changes in ACCESS")
        print(f"  observed={violation}")
        print(f"  report={report}")
        return 0 if violation.endswith("request_stability") else 1
    if args.command == "axi-read-network":
        run, report, project = _write_axi_read_network(args.sim_dir)
        rejected, _, rejected_project = _write_axi_read_network(
            args.sim_dir, crossing=True
        )
        print("TWO-LINK AXI READ NETWORK")
        print(f"  legal_verdict={run.verdict.value} events={len(run.trace.events)}")
        for item in run.milestones:
            print(
                f"  {item.name}: A={item.link_a_pending} "
                f"bridge={item.bridge_pending} B={item.link_b_pending}"
            )
        print(
            "  crossing_4k="
            f"{rejected.fault.rule if rejected.fault else rejected.verdict.value}"
        )
        print(f"  report={report}")
        print(f"  project_phase={project.phase.value}")
        print(f"  rejected_case_phase={rejected_project.phase.value}")
        return 0 if run.verdict.value == "PASS" and rejected.fault else 1
    if args.command == "ready-valid-sink":
        simulation = build_ready_valid_sink_simulation(args.sim_dir)
        legal = simulation.legal
        mutation = simulation.mutation
        print("READY-VALID SOURCE → PROTOCOL → SINK PROJECT")
        print(
            f"  legal: verdict={legal.verdict.value} samples={legal.samples} "
            f"transfers={len(legal.transfers)} sink={legal.sink_state.received} "
            f"phase={simulation.legal_phase}"
        )
        print(f"  report={simulation.report}")
        print(
            "  mutation: "
            f"{mutation.fault.rule if mutation.fault else mutation.verdict.value} "
            f"sink={mutation.sink_state.received} "
            f"phase={simulation.mutation_phase}"
        )
        return 0 if (
            legal.verdict.value == "PASS"
            and legal.sink_state.received == 2
            and mutation.fault is not None
            and mutation.sink_state.received == 0
        ) else 1
    return 2
