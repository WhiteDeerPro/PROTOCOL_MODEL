"""Small executable views for inspecting protocol-model behavior."""

from __future__ import annotations

import argparse
from dataclasses import replace
from random import Random
from typing import Sequence

from protocol_model import __version__
from protocol_model.patterns import ReadyValidSample, ResetSample
from protocol_model.evidence import (
    format_cardinality_run,
    format_correlated_run,
    format_ready_valid_run,
)
from protocol_model.projects.prj_axi4_read_bridge import (
    DEFAULT_SIM_DIR as AXI_READ_BRIDGE_SIM_DIR,
    build_simulation as build_axi_read_bridge_simulation,
)
from protocol_model.projects.prj_ready_valid_sink import (
    DEFAULT_SIM_DIR as READY_VALID_SINK_SIM_DIR,
    build_simulation as build_ready_valid_sink_simulation,
)
from protocol_model.projects.prj_axi4_read_interleave import (
    DEFAULT_SIM_DIR as AXI_READ_INTERLEAVE_SIM_DIR,
    build_simulation as build_axi_read_interleave_simulation,
    format_run as format_axi_read_interleave_run,
)
from protocol_model.projects.prj_apb_compare import (
    DEFAULT_SIM_DIR as APB_COMPARE_SIM_DIR,
    build_simulation as build_apb_comparison_simulation,
)
from protocol_model.protocols.axi4 import (
    Axi4Cycle,
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="protocol_model")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
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
    constraints = subparsers.add_parser(
        "constraint-witness", help="show minimal witnesses for newly modeled AXI rules"
    )
    constraints.add_argument("--seed", type=int, default=31)
    interleave = subparsers.add_parser(
        "axi-read-interleave",
        help="run the two-VirtualDut AXI4 read-interleaving Project",
    )
    interleave.add_argument("--sim-dir", default=str(AXI_READ_INTERLEAVE_SIM_DIR))
    apb = subparsers.add_parser(
        "apb", help="generate APB3/APB4 two-phase waveforms and comparison report"
    )
    apb.add_argument("--transactions", type=int, default=4)
    apb.add_argument("--seed", type=int, default=41)
    apb.add_argument(
        "--sim-dir",
        default=str(APB_COMPARE_SIM_DIR),
        help="run bundle directory",
    )
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
        return 1 if result.violations else 0
    if args.command == "constraint-witness":
        print(_constraint_witness(args.seed))
        return 0
    if args.command == "axi-read-interleave":
        simulation = build_axi_read_interleave_simulation(args.sim_dir)
        print(format_axi_read_interleave_run(simulation.run))
        print(
            f"\nARTIFACTS\n  html={simulation.report}\n  text={simulation.text_report}"
            f"\n  waveform={simulation.waveform}\n  network={simulation.network}"
            f"\n  causality={simulation.causality}"
        )
        return 0 if simulation.run.verdict.value == "PASS" else 1
    if args.command == "apb":
        simulation = build_apb_comparison_simulation(
            args.sim_dir,
            transactions=args.transactions,
            seed=args.seed,
        )
        run = simulation.run
        print("APB3 / APB4 PROTOCOL-INSTANCE PROJECT")
        for version in (3, 4):
            print(
                f"  APB{version}: cycles={len(run.traces[version].samples)} "
                f"transfers={len(run.traces[version].transfers)}"
            )
        print(f"  mutation=request address changes in ACCESS")
        print(f"  observed={run.mutation_rule}")
        print(f"  network={simulation.network}")
        print(f"  report={simulation.report}")
        return 0 if run.verdict.value == "PASS" else 1
    if args.command == "axi-read-network":
        simulation = build_axi_read_bridge_simulation(args.sim_dir)
        run = simulation.legal
        rejected = simulation.rejected
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
        print(f"  report={simulation.report}")
        print(f"  project_phase={simulation.legal_project.phase.value}")
        print(f"  rejected_case_phase={simulation.rejected_project.phase.value}")
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
