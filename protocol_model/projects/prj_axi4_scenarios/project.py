"""Batch AXI4 scenarios using one manager source and one responder VirtualDut."""

from __future__ import annotations

from dataclasses import dataclass, replace
from random import Random

from protocol_model.core import CanonicalEvent, SemanticFault, Verdict
from protocol_model.patterns import ReadyValidSample, ResetSample
from protocol_model.protocols.axi4 import Axi4Config, Axi4Cycle, Axi4SignalSession, build_axi4_spec
from protocol_model.protocols.spec import ProtocolInstance, ProtocolSpec
from protocol_model.virtual_dut import EmitNext

from ..lifecycle import ComponentUse, ProjectPhase, VerificationProject
from .virtual_dut import AxiManagerSource, AxiSubordinateResponder


MANAGER_CHANNELS = frozenset({"AW", "W", "AR"})
RESPONDER_CHANNELS = frozenset({"B", "R"})


@dataclass(frozen=True)
class AxiScenarioCase:
    name: str
    category: str
    description: str
    expected: Verdict
    cycles: tuple[Axi4Cycle, ...]
    expected_rule: str | None = None


@dataclass(frozen=True)
class AxiScenarioResult:
    case: AxiScenarioCase
    observed: Verdict
    matched: bool
    fault: SemanticFault | None
    emissions: tuple[CanonicalEvent, ...]
    steps: tuple[tuple[int, ...], ...]
    causal_edges: tuple[tuple[int, int], ...]
    quiescent: bool


@dataclass(frozen=True)
class AxiScenarioRun:
    verdict: Verdict
    results: tuple[AxiScenarioResult, ...]


def _event(
    spec: ProtocolSpec,
    channel: str,
    seed: int,
    *,
    key=None,
    payload=None,
) -> CanonicalEvent:
    return spec.channel(channel).transfer.sample_constrained(
        Random(seed), key=key, payload=payload or {}
    )


def _address(
    spec: ProtocolSpec,
    channel: str,
    seed: int,
    *,
    key: int,
    address: int,
    beats: int,
    burst: str = "INCR",
) -> CanonicalEvent:
    size = int(spec.parameters["data_width"]).bit_length() - 4
    return _event(
        spec,
        channel,
        seed,
        key=key,
        payload={
            "addr": address,
            "len": beats - 1,
            "size": size,
            "burst": burst,
            "lock": 0,
            "cache": 0,
            "prot": 0,
            "qos": 0,
            "region": 0,
        },
    )


def _r(spec: ProtocolSpec, seed: int, key: int, beat: int, total: int, resp="OKAY"):
    return _event(
        spec,
        "R",
        seed,
        key=key,
        payload={"data": (key << 16) | beat, "resp": resp, "last": beat == total - 1},
    )


def _w(spec: ProtocolSpec, seed: int, beat: int, total: int):
    mask = (1 << (int(spec.parameters["data_width"]) // 8)) - 1
    return _event(
        spec,
        "W",
        seed,
        payload={"data": 0x100 + beat, "strb": mask, "last": beat == total - 1},
    )


def _b(spec: ProtocolSpec, seed: int, key: int, resp="OKAY"):
    return _event(spec, "B", seed, key=key, payload={"resp": resp})


def _cycle(
    spec: ProtocolSpec,
    number: int,
    *,
    active: dict[str, CanonicalEvent] | None = None,
    ready: bool | dict[str, bool] = True,
    reset: bool = False,
    reset_by_channel: dict[str, bool] | None = None,
) -> Axi4Cycle:
    active = active or {}
    ready_by_channel = ready if isinstance(ready, dict) else {}
    channels = {}
    for name in spec.channels:
        valid = name in active
        is_ready = ready_by_channel.get(name, bool(ready) if valid else False)
        channels[name] = ResetSample(
            (reset_by_channel or {}).get(name, reset),
            ReadyValidSample(
                number,
                valid,
                is_ready,
                active.get(name),
                "aclk",
                "manager_source" if name in MANAGER_CHANNELS else "subordinate_responder",
            ),
        )
    return Axi4Cycle(channels)


def _cycles(spec: ProtocolSpec, steps) -> tuple[Axi4Cycle, ...]:
    result = [_cycle(spec, 0, reset=True)]
    for number, events in enumerate(steps, start=1):
        active = {}
        for event in events:
            channel = next(
                name
                for name, item in spec.channels.items()
                if item.transfer.kind == event.kind
            )
            if channel in active:
                raise ValueError(f"two {channel} transfers cannot share one cycle")
            active[channel] = event
        result.append(_cycle(spec, number, active=active))
    return tuple(result)


def _read_steps(request, responses):
    return ((request,), *((item,) for item in responses))


def build_cases(spec: ProtocolSpec) -> tuple[AxiScenarioCase, ...]:
    cases = []

    def add(name, category, description, expected, steps, rule=None):
        cases.append(
            AxiScenarioCase(
                name,
                category,
                description,
                expected,
                _cycles(spec, steps),
                rule,
            )
        )

    # Read geometry, completion, and response behavior.
    for name, beats, burst, address in (
        ("read_single_incr", 1, "INCR", 0x1000),
        ("read_16_incr", 16, "INCR", 0x2000),
        ("read_fixed_16", 16, "FIXED", 0x3000),
        ("read_wrap_4", 4, "WRAP", 0x4020),
    ):
        ar = _address(spec, "AR", 10 + beats, key=1, address=address, beats=beats, burst=burst)
        responses = tuple(_r(spec, 100 + index, 1, index, beats) for index in range(beats))
        add(name, "read", f"legal {beats}-beat {burst} read", Verdict.PASS, _read_steps(ar, responses))

    legal_fixed = _address(
        spec, "AR", 31, key=1, address=0x5000, beats=16, burst="FIXED"
    )
    bad_fixed = replace(legal_fixed, payload={**legal_fixed.payload, "len": 16})
    add("read_fixed_17_rejected", "read", "FIXED exceeds 16 beats", Verdict.FAIL, ((bad_fixed,),), "event_space")
    legal_wrap = _address(spec, "AR", 32, key=1, address=0x6000, beats=4, burst="WRAP")
    bad_wrap = replace(legal_wrap, payload={**legal_wrap.payload, "len": 2})
    add("read_wrap_3_rejected", "read", "WRAP uses an illegal three-beat length", Verdict.FAIL, ((bad_wrap,),), "event_space")

    edge = _address(spec, "AR", 33, key=1, address=0xFF8, beats=1)
    add("read_4kb_edge", "read", "burst ends at 0x0FFF immediately before the 0x1000 boundary", Verdict.PASS, _read_steps(edge, (_r(spec, 133, 1, 0, 1),)))
    crossing_base = _address(spec, "AR", 34, key=1, address=0xFE0, beats=2)
    crossing = replace(crossing_base, payload={**crossing_base.payload, "addr": 0xFF8})
    add("read_cross_4kb", "read", "full-width INCR burst crosses 4KB", Verdict.FAIL, ((crossing,),), "event_space")

    ar2 = _address(spec, "AR", 35, key=1, address=0x7000, beats=2)
    early = replace(_r(spec, 135, 1, 0, 2), payload={"data": 0, "resp": "OKAY", "last": True})
    add("read_early_rlast", "read", "RLAST asserted on the first of two beats", Verdict.FAIL, ((ar2,), (early,)), "final_marker")
    missing = replace(_r(spec, 136, 1, 1, 2), payload={"data": 1, "resp": "OKAY", "last": False})
    add("read_missing_rlast", "read", "final beat omits RLAST", Verdict.FAIL, ((ar2,), (_r(spec, 137, 1, 0, 2),), (missing,)), "final_marker")
    one = _address(spec, "AR", 38, key=1, address=0x7100, beats=1)
    add("read_extra_beat", "read", "R beat follows a completed burst", Verdict.FAIL, ((one,), (_r(spec, 138, 1, 0, 1),), (_r(spec, 139, 1, 0, 1),)), "rvalid_dependency")
    add("read_orphan_r", "read", "R arrives without an AR obligation", Verdict.FAIL, ((_r(spec, 140, 1, 0, 1),),), "rvalid_dependency")
    add("read_unknown_rid", "read", "R uses a different ID from the pending AR", Verdict.FAIL, ((one,), (_r(spec, 141, 2, 0, 1),)), "orphan_beat")
    add("read_slverr", "read", "SLVERR completes an ordinary read", Verdict.PASS, ((one,), (_r(spec, 142, 1, 0, 1, "SLVERR"),)))
    add("read_decerr", "read", "DECERR completes an ordinary read", Verdict.PASS, ((one,), (_r(spec, 143, 1, 0, 1, "DECERR"),)))

    # Write channel independence, join, completion, and error responses.
    aw1 = _address(spec, "AW", 50, key=1, address=0x8000, beats=1)
    w1 = _w(spec, 150, 0, 1)
    b1 = _b(spec, 250, 1)
    add("write_single", "write", "ordinary single-beat write", Verdict.PASS, ((aw1,), (w1,), (b1,)))
    add("write_data_before_address", "write", "complete W burst precedes AW", Verdict.PASS, ((w1,), (aw1,), (b1,)))
    add("write_aw_w_same_cycle", "write", "AW and W handshake together", Verdict.PASS, ((aw1, w1), (b1,)))

    aw2a = _address(spec, "AW", 51, key=1, address=0x8100, beats=1)
    aw2b = _address(spec, "AW", 52, key=2, address=0x8200, beats=1)
    add("write_two_outstanding", "write", "two AW descriptors join two FIFO W bursts", Verdict.PASS, ((aw2a,), (aw2b,), (_w(spec, 151, 0, 1),), (_w(spec, 152, 0, 1),), (_b(spec, 251, 1),), (_b(spec, 252, 2),)))

    aw_two = _address(spec, "AW", 53, key=1, address=0x8300, beats=2)
    add("write_early_wlast", "write", "WLAST asserted before AWLEN beats", Verdict.FAIL, ((aw_two,), (_w(spec, 153, 0, 1),)), "beat_count")
    missing_wlast = replace(_w(spec, 154, 1, 2), payload={"data": 1, "strb": 0xFF, "last": False})
    add("write_missing_wlast", "write", "final W beat omits WLAST", Verdict.FAIL, ((aw_two,), (_w(spec, 155, 0, 2),), (missing_wlast,)), "missing_final")
    add("write_wrong_bid", "write", "BID does not name a completed write", Verdict.FAIL, ((aw1,), (w1,), (_b(spec, 253, 2),)), "orphan_completion")
    add("write_b_before_join", "write", "B arrives before AW/W join", Verdict.FAIL, ((aw1,), (b1,)), "bvalid_dependency")
    add("write_slverr", "write", "SLVERR completes an ordinary write", Verdict.PASS, ((aw1,), (w1,), (_b(spec, 254, 1, "SLVERR"),)))
    add("write_decerr", "write", "DECERR completes an ordinary write", Verdict.PASS, ((aw1,), (w1,), (_b(spec, 255, 1, "DECERR"),)))

    # Same-ID FIFO and cross-ID freedom.
    ar_a = _address(spec, "AR", 60, key=1, address=0x9000, beats=2)
    ar_b = _address(spec, "AR", 61, key=2, address=0x9100, beats=2)
    add("read_cross_id_later_first", "ordering", "later ID2 request completes before ID1", Verdict.PASS, ((ar_a,), (ar_b,), (_r(spec, 160, 2, 0, 2),), (_r(spec, 161, 2, 1, 2),), (_r(spec, 162, 1, 0, 2),), (_r(spec, 163, 1, 1, 2),)))
    add("read_cross_id_interleave", "ordering", "R beats alternate across two IDs", Verdict.PASS, ((ar_a,), (ar_b,), (_r(spec, 164, 2, 0, 2),), (_r(spec, 165, 1, 0, 2),), (_r(spec, 166, 2, 1, 2),), (_r(spec, 167, 1, 1, 2),)))
    same_long = _address(spec, "AR", 62, key=1, address=0x9200, beats=2)
    same_short = _address(spec, "AR", 63, key=1, address=0x9300, beats=1)
    add("read_same_id_overtake", "ordering", "second same-ID burst attempts to complete first", Verdict.FAIL, ((same_long,), (same_short,), (_r(spec, 168, 1, 0, 1),)), "final_marker")
    add("write_cross_id_b_reverse", "ordering", "different BID responses complete in reverse request order", Verdict.PASS, ((aw2a,), (aw2b,), (_w(spec, 169, 0, 1),), (_w(spec, 170, 0, 1),), (_b(spec, 269, 2),), (_b(spec, 270, 1),)))
    add("write_burst_fifo_mismatch", "ordering", "short W burst cannot skip the oldest longer AW", Verdict.FAIL, ((aw_two,), (aw2b,), (_w(spec, 171, 0, 1),)), "beat_count")

    # Cross-channel concurrency and reset/stall behavior.
    ar_c = _address(spec, "AR", 70, key=3, address=0xA000, beats=1)
    aw_c = _address(spec, "AW", 71, key=4, address=0xA100, beats=1)
    add("read_write_parallel", "concurrency", "read and write requests overlap and R/B complete together", Verdict.PASS, ((ar_c, aw_c), (_w(spec, 172, 0, 1),), (_r(spec, 173, 3, 0, 1), _b(spec, 273, 4))))

    old_ar = _address(spec, "AR", 72, key=1, address=0xA200, beats=1)
    old_aw = _address(spec, "AW", 73, key=1, address=0xA300, beats=1)
    new_ar = _address(spec, "AR", 74, key=2, address=0xA400, beats=1)
    new_aw = _address(spec, "AW", 75, key=2, address=0xA500, beats=1)
    add("five_channel_concurrency", "concurrency", "all five channels handshake in one cycle after obligations exist", Verdict.PASS, ((old_ar, old_aw), (_w(spec, 174, 0, 1),), (new_ar, new_aw, _w(spec, 175, 0, 1), _r(spec, 176, 1, 0, 1), _b(spec, 276, 1)), (_r(spec, 177, 2, 0, 1), _b(spec, 277, 2))))

    stall_aw = _address(spec, "AW", 76, key=1, address=0xA600, beats=1)
    changed_aw = replace(stall_aw, payload={**stall_aw.payload, "addr": 0xA608})
    cases.append(AxiScenarioCase("stall_aw_payload_mutation", "concurrency", "AW payload changes while VALID is stalled", Verdict.FAIL, (_cycle(spec, 0, reset=True), _cycle(spec, 1, active={"AW": stall_aw}, ready={"AW": False}), _cycle(spec, 2, active={"AW": changed_aw}, ready={"AW": False})), "payload_stability"))

    stalled_r = _r(spec, 178, 1, 0, 1)
    cases.append(AxiScenarioCase("stall_r_valid_drop", "concurrency", "RVALID drops before a stalled transfer is accepted", Verdict.FAIL, (_cycle(spec, 0, reset=True), _cycle(spec, 1, active={"AR": old_ar}), _cycle(spec, 2, active={"R": stalled_r}, ready={"R": False}), _cycle(spec, 3)), "valid_stability"))

    cases.append(AxiScenarioCase("reset_discards_outstanding_read", "reset", "response from the pre-reset epoch becomes orphaned", Verdict.FAIL, (_cycle(spec, 0, reset=True), _cycle(spec, 1, active={"AR": old_ar}), _cycle(spec, 2, reset=True), _cycle(spec, 3, active={"R": _r(spec, 179, 1, 0, 1)})), "rvalid_dependency"))

    reset_aw = _address(spec, "AW", 77, key=2, address=0xA700, beats=1)
    cases.append(AxiScenarioCase("reset_clears_stalled_valid", "reset", "reset cancels a stalled AW and a new write completes afterward", Verdict.PASS, (_cycle(spec, 0, reset=True), _cycle(spec, 1, active={"AW": stall_aw}, ready={"AW": False}), _cycle(spec, 2, reset=True), _cycle(spec, 3, active={"AW": reset_aw}), _cycle(spec, 4, active={"W": _w(spec, 180, 0, 1)}), _cycle(spec, 5, active={"B": _b(spec, 280, 2)}))))

    cases.append(AxiScenarioCase("inconsistent_channel_reset", "reset", "one AXI channel observes a different reset level", Verdict.FAIL, (_cycle(spec, 0, reset=True), _cycle(spec, 1, reset_by_channel={"AW": True})), "reset_consistency"))
    return tuple(cases)


class AxiScenarioProject(VerificationProject):
    def __init__(self, config: Axi4Config | None = None):
        self.config = config or Axi4Config()
        self.spec = None
        self.protocol = None
        super().__init__(
            "prj_axi4_scenarios",
            (
                ComponentUse("manager", "virtual_dut", "AxiManagerSource", "drive AW/W/AR"),
                ComponentUse("AXI4", "protocol", "ProtocolInstance[AXI4]", "check five-channel behavior"),
                ComponentUse("subordinate", "virtual_dut", "AxiSubordinateResponder", "drive B/R"),
            ),
        )

    def elaborate(self) -> None:
        base = build_axi4_spec(self.config)
        self.protocol = ProtocolInstance.bind("AXI", base, owner=self.name)
        self.spec = self.protocol.spec
        self.state.update(
            {
                "profile": "full-width aligned, AxLOCK=0, AxCACHE=0",
                "excluded": ("atomic/exclusive", "cache semantics", "narrow/unaligned"),
                "protocol_instances": (self.protocol.qualified_name,),
            }
        )
        self.transition(ProjectPhase.ELABORATED, "connected manager source and subordinate responder")

    def _run_case(self, case: AxiScenarioCase) -> AxiScenarioResult:
        assert self.spec is not None
        manager = AxiManagerSource(
            tuple(
                {name: cycle.channels[name] for name in MANAGER_CHANNELS}
                for cycle in case.cycles
            )
        )
        responder = AxiSubordinateResponder(
            tuple(
                {name: cycle.channels[name] for name in RESPONDER_CHANNELS}
                for cycle in case.cycles
            )
        )
        manager_state = manager.initial_state()
        responder_state = responder.initial_state()
        signal = Axi4SignalSession(spec=self.spec)
        state = signal.initial_state()
        emissions = []
        steps = []
        fault = None
        for _ in case.cycles:
            manager_step = manager.step(manager_state, EmitNext())
            responder_step = responder.step(responder_state, EmitNext())
            manager_state = manager_step.state
            responder_state = responder_step.state
            channels = {**manager_step.emissions[0], **responder_step.emissions[0]}
            transition = signal.step(state, Axi4Cycle(channels))
            if transition.fault is not None:
                fault = transition.fault
                break
            state = transition.state
            indices = tuple(range(len(emissions), len(emissions) + len(transition.emissions)))
            steps.append(indices)
            emissions.extend(transition.emissions)
        quiescent = fault is None and signal.is_quiescent(state)
        if fault is None and not quiescent:
            fault = SemanticFault(
                "axi4.scenario.not_quiescent",
                "scenario ended with outstanding protocol obligations",
            )
        observed = Verdict.FAIL if fault is not None else Verdict.PASS
        rule_matched = (
            case.expected_rule is None
            or (fault is not None and case.expected_rule in fault.rule)
        )
        return AxiScenarioResult(
            case,
            observed,
            observed is case.expected and rule_matched,
            fault,
            tuple(emissions),
            tuple(steps),
            state.protocol_state.causal_edges,
            quiescent,
        )

    def run(self) -> AxiScenarioRun:
        if self.phase is ProjectPhase.CREATED:
            self.elaborate()
        if self.phase is not ProjectPhase.ELABORATED:
            raise RuntimeError(f"project must be ELABORATED, got {self.phase.value}")
        assert self.spec is not None
        results = tuple(self._run_case(case) for case in build_cases(self.spec))
        verdict = Verdict.PASS if all(item.matched for item in results) else Verdict.FAIL
        self.state.update(
            {
                "cases": len(results),
                "legal_cases": sum(item.case.expected is Verdict.PASS for item in results),
                "negative_cases": sum(item.case.expected is Verdict.FAIL for item in results),
                "matched": sum(item.matched for item in results),
                "verdict": verdict.value,
            }
        )
        self.transition(ProjectPhase.EXECUTED, f"executed {len(results)} AXI scenarios")
        self.transition(
            ProjectPhase.CHECKED if verdict is Verdict.PASS else ProjectPhase.FAILED,
            "all cases matched" if verdict is Verdict.PASS else "one or more cases mismatched",
        )
        return AxiScenarioRun(verdict, results)
