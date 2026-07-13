"""Executable AXI4 cross-ID read-interleaving verification Project."""

from __future__ import annotations

from dataclasses import dataclass, replace
from random import Random

from protocol_model.core import CanonicalEvent, SemanticFault, Verdict
from protocol_model.engine import ExecutionTrace
from protocol_model.patterns import ReadyValidSample, ResetSample
from protocol_model.protocols.spec import ProtocolInstance
from protocol_model.protocols.axi4 import (
    Axi4Config,
    Axi4Cycle,
    Axi4SignalSession,
    build_axi4_spec,
)
from protocol_model.virtual_dut import EmitNext

from ..lifecycle import ComponentUse, ProjectPhase, VerificationProject
from .constraints import ReadInterleaveConstraints, derive_constrained_axi4
from .virtual_dut import InterleavingReadResponder, build_read_initiator


@dataclass(frozen=True)
class ConstraintCheck:
    name: str
    expected: Verdict
    observed: Verdict
    rule: str
    detail: str
    events: tuple[CanonicalEvent, ...] = ()
    cycles: tuple[Axi4Cycle, ...] = ()

    @property
    def matched(self) -> bool:
        return self.expected is self.observed


@dataclass(frozen=True)
class AxiReadInterleaveRun:
    verdict: Verdict
    trace: ExecutionTrace[CanonicalEvent]
    checks: tuple[ConstraintCheck, ...]
    source_emitted: int
    responder_emitted: int
    fault: SemanticFault | None = None


def _check(
    name: str,
    expected: Verdict,
    run,
    *,
    events: tuple[CanonicalEvent, ...] = (),
    cycles: tuple[Axi4Cycle, ...] = (),
) -> ConstraintCheck:
    violation = run.violations[0] if run.violations else None
    return ConstraintCheck(
        name,
        expected,
        run.verdict,
        "-" if violation is None else str(violation.rule),
        "legal trace completed" if violation is None else violation.reason,
        events,
        cycles,
    )


class AxiReadInterleaveProject(VerificationProject):
    """Own the constrained AXI4 instance, two VirtualDuts, plan and evidence."""

    def __init__(
        self,
        config: Axi4Config | None = None,
        constraints: ReadInterleaveConstraints | None = None,
        *,
        beats_per_request: int = 2,
    ):
        if not 1 <= beats_per_request <= 256:
            raise ValueError("beats_per_request must be in the AXI4 range [1, 256]")
        self.config = config or Axi4Config()
        self.constraints = constraints or ReadInterleaveConstraints()
        self.beats_per_request = beats_per_request
        self.base_spec = None
        self.spec = None
        self.protocol = None
        self.source = None
        self.responder = None
        super().__init__(
            "prj_axi4_read_interleave",
            (
                ComponentUse(
                    "input_dut",
                    "virtual_dut",
                    "ScriptedSource[AR]",
                    "issue two distinct-ID read requests",
                ),
                ComponentUse(
                    "AXI4",
                    "protocol",
                    "derived ProtocolSpec[AXI4]",
                    "apply protocol and project constraints",
                ),
                ComponentUse(
                    "read_profile",
                    "constraint_profile",
                    "ProtocolDerivation + ConstraintRecord",
                    "bind active IDs and quiet unused signals",
                ),
                ComponentUse(
                    "output_dut",
                    "virtual_dut",
                    "InterleavingReadResponder",
                    "return alternating R beats for both IDs",
                ),
            ),
        )

    def elaborate(self) -> None:
        self.base_spec = build_axi4_spec(self.config)
        self.spec = derive_constrained_axi4(self.base_spec, self.constraints)
        self.protocol = ProtocolInstance.bind(
            "AXI-RI",
            self.base_spec,
            owner=self.name,
            constrained_spec=self.spec,
        )
        self.source = build_read_initiator(
            self.spec, beats_per_request=self.beats_per_request
        )
        self.responder = InterleavingReadResponder(self.spec)
        self.state.update(
            {
                "base_protocol": self.base_spec.name,
                "derived_protocol": self.spec.name,
                "active_ids": self.constraints.active_ids,
                "quiet_channels": self.constraints.quiet_channels,
                "quiet_ar_fields": self.constraints.quiet_ar_fields,
                "derivation_constraints": self.spec.parameters[
                    "derivation_constraints"
                ],
                "virtual_duts": 2,
                "beats_per_request": self.beats_per_request,
                "protocol_instances": (self.protocol.qualified_name,),
            }
        )
        self.transition(
            ProjectPhase.ELABORATED,
            "derived experiment constraints from AXI4 and created two VirtualDuts",
        )

    def _constraint_checks(self) -> tuple[ConstraintCheck, ...]:
        assert self.spec is not None and self.protocol is not None
        rng = Random(83)
        ids = self.constraints.active_ids
        ar_space = self.spec.channel("AR").transfer
        r_space = self.spec.channel("R").transfer

        def ar(key: int, beats: int):
            return ar_space.sample_constrained(
                rng,
                key=key,
                payload={
                    "addr": 0x2000 + key * 0x100,
                    "len": beats - 1,
                    "size": 2,
                    "burst": "INCR",
                },
            )

        def r(key: int, last: bool):
            return r_space.sample_constrained(
                rng,
                key=key,
                payload={"data": 0, "resp": "OKAY", "last": last},
            )

        same_id_events = (ar(ids[0], 2), ar(ids[0], 1), r(ids[0], True))
        same_id = self.protocol.open_session().run(same_id_events)
        unused_id = next(
            (
                item
                for item in range(1 << self.config.id_width)
                if item not in self.constraints.active_ids
            ),
            1 << self.config.id_width,
        )
        valid_ar = ar(ids[0], 2)
        undeclared_rid_events = (
            valid_ar,
            replace(r(ids[0], False), key=unused_id),
        )
        undeclared_rid = self.protocol.open_session().run(undeclared_rid_events)
        cache_active_events = (
            replace(valid_ar, payload={**valid_ar.payload, "cache": 1}),
        )
        cache_active = self.protocol.open_session().run(cache_active_events)
        aw = self.spec.channel("AW").transfer.sample_constrained(
            rng, payload={"len": 0, "size": 2, "burst": "INCR"}
        )
        quiet_cycle = Axi4Cycle(
            {
                name: ResetSample(
                    False,
                    ReadyValidSample(
                        0,
                        name == "AW",
                        False,
                        aw if name == "AW" else None,
                        "aclk",
                        "read_interleave_project",
                    ),
                )
                for name in self.spec.channels
            }
        )
        write_active = Axi4SignalSession(spec=self.spec).run((quiet_cycle,))
        return (
            _check(
                "same_id_cannot_overtake",
                Verdict.FAIL,
                same_id,
                events=same_id_events,
            ),
            _check(
                "rid_must_be_active",
                Verdict.FAIL,
                undeclared_rid,
                events=undeclared_rid_events,
            ),
            _check(
                "arcache_tied_zero",
                Verdict.FAIL,
                cache_active,
                events=cache_active_events,
            ),
            _check(
                "write_valid_tied_low",
                Verdict.FAIL,
                write_active,
                cycles=(quiet_cycle,),
            ),
        )

    def run(self) -> AxiReadInterleaveRun:
        if self.phase is ProjectPhase.CREATED:
            self.elaborate()
        if self.phase is not ProjectPhase.ELABORATED:
            raise RuntimeError(f"project must be ELABORATED, got {self.phase.value}")
        assert (
            self.spec is not None
            and self.protocol is not None
            and self.source is not None
            and self.responder is not None
        )

        session = self.protocol.open_session()
        protocol_state = session.initial_state()
        source_state = self.source.initial_state()
        responder_state = self.responder.initial_state()
        events = []

        while self.source.offers(source_state):
            source_step = self.source.step(source_state, EmitNext())
            if source_step.fault is not None:
                return self._finish(
                    events,
                    protocol_state,
                    (),
                    source_state.emitted,
                    responder_state.responses,
                    source_step.fault,
                )
            source_state = source_step.state
            request_step = session.step(protocol_state, source_step.emissions[0])
            if request_step.fault is not None:
                return self._finish(
                    events,
                    protocol_state,
                    (),
                    source_state.emitted,
                    responder_state.responses,
                    request_step.fault,
                )
            protocol_state = request_step.state
            request = request_step.emissions[0]
            events.append(request)

            response_step = self.responder.step(responder_state, request)
            if response_step.fault is not None:
                return self._finish(
                    events,
                    protocol_state,
                    (),
                    source_state.emitted,
                    responder_state.responses,
                    response_step.fault,
                )
            responder_state = response_step.state
            for response in response_step.emissions:
                accepted = session.step(protocol_state, response)
                if accepted.fault is not None:
                    return self._finish(
                        events,
                        protocol_state,
                        (),
                        source_state.emitted,
                        responder_state.responses,
                        accepted.fault,
                    )
                protocol_state = accepted.state
                events.append(accepted.emissions[0])

        checks = self._constraint_checks()
        quiescent = (
            self.source.is_quiescent(source_state)
            and self.responder.is_quiescent(responder_state)
            and session.is_quiescent(protocol_state)
        )
        verdict = (
            Verdict.PASS
            if quiescent and all(item.matched for item in checks)
            else Verdict.FAIL
        )
        return self._finish(
            events,
            protocol_state,
            checks,
            source_state.emitted,
            responder_state.responses,
            None,
            verdict,
        )

    def _finish(
        self,
        events,
        protocol_state,
        checks,
        source_emitted,
        responder_emitted,
        fault=None,
        verdict=Verdict.FAIL,
    ) -> AxiReadInterleaveRun:
        assert self.spec is not None
        trace = self.spec.open_session().execution_trace(
            protocol_state,
            tuple(events),
            tuple((index,) for index in range(len(events))),
        )
        run = AxiReadInterleaveRun(
            verdict,
            trace,
            tuple(checks),
            source_emitted,
            responder_emitted,
            fault,
        )
        self.state.update(
            {
                "verdict": verdict.value,
                "events": len(events),
                "source_emitted": source_emitted,
                "responder_emitted": responder_emitted,
                "constraint_checks": len(checks),
                "fault": None if fault is None else fault.rule,
            }
        )
        self.transition(
            ProjectPhase.EXECUTED, "executed two-VirtualDut read interleave plan"
        )
        if verdict is Verdict.PASS:
            self.transition(
                ProjectPhase.CHECKED,
                "legal flow and all constraint mutations matched",
            )
        else:
            self.transition(ProjectPhase.FAILED, "experiment result did not match its contract")
        return run
