"""Smallest end-to-end Project using Source → Protocol → Sink."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model.core import CanonicalEvent, SemanticFault, Verdict
from protocol_model.patterns import ReadyValidSample, ResetSample
from protocol_model.protocols.ready_valid import (
    ReadyValidConfig,
    build_ready_valid_spec,
)
from protocol_model.virtual_dut import (
    EmitNext,
    ScriptedSource,
    Sink,
    SinkState,
    VirtualDutRegistry,
)

from ..base import ComponentUse, ProjectPhase, VerificationProject


@dataclass(frozen=True)
class ReadyValidSinkCase:
    name: str
    payloads: tuple[int, ...]
    stall_first: bool = True
    mutate_stalled_payload: bool = False
    expect_violation: bool = False


@dataclass(frozen=True)
class ReadyValidSinkRun:
    verdict: Verdict
    samples: int
    observations: tuple[ResetSample[ReadyValidSample], ...]
    transfers: tuple[CanonicalEvent, ...]
    sink_state: SinkState[CanonicalEvent]
    fault: SemanticFault | None = None
    fault_cycle: int | None = None


class ReadyValidSinkProject(VerificationProject):
    def __init__(self, config: ReadyValidConfig | None = None):
        self.config = config or ReadyValidConfig()
        super().__init__(
            "prj_ready_valid_sink",
            (
                ComponentUse(
                    "source",
                    "virtual_dut",
                    "ScriptedSource",
                    "emit configured pin samples",
                ),
                ComponentUse(
                    "DATA",
                    "protocol",
                    "ReadyValid ProtocolSpec",
                    "lower VALID/READY samples into accepted transfers",
                ),
                ComponentUse(
                    "sink",
                    "virtual_dut",
                    "Sink[capture=True]",
                    "consume only protocol-accepted transfers",
                ),
            ),
        )
        self.spec = None

    def elaborate(self) -> None:
        self.spec = build_ready_valid_spec(self.config)
        self.state.update({"case": None, "samples": 0, "transfers": 0})
        self.transition(
            ProjectPhase.ELABORATED,
            "instantiated source, ready-valid protocol, and capturing sink",
        )

    def _samples(self, case: ReadyValidSinkCase):
        assert self.spec is not None
        space = self.spec.channel("DATA").transfer
        samples = [
            ResetSample(
                True,
                ReadyValidSample(0, False, False, clock=self.config.clock),
            )
        ]
        cycle = 1
        for index, payload in enumerate(case.payloads):
            event = CanonicalEvent("DATA_TRANSFER", None, {"data": payload})
            if index == 0 and case.stall_first:
                samples.append(
                    ResetSample(
                        False,
                        ReadyValidSample(
                            cycle, True, False, event, self.config.clock, "source"
                        ),
                    )
                )
                cycle += 1
                if case.mutate_stalled_payload:
                    changed = (payload + 1) % (1 << self.config.data_width)
                    event = CanonicalEvent(
                        "DATA_TRANSFER", None, {"data": changed}
                    )
            if not space.contains(event):
                raise ValueError(f"case payload is outside EventSpace: {space.explain(event)}")
            samples.append(
                ResetSample(
                    False,
                    ReadyValidSample(
                        cycle, True, True, event, self.config.clock, "source"
                    ),
                )
            )
            cycle += 1
        return tuple(samples)

    def run_case(self, case: ReadyValidSinkCase) -> ReadyValidSinkRun:
        if self.phase is ProjectPhase.CREATED:
            self.elaborate()
        if self.phase is not ProjectPhase.ELABORATED:
            raise RuntimeError(f"project must be ELABORATED, got {self.phase.value}")
        assert self.spec is not None

        registry = VirtualDutRegistry.standard()
        source: ScriptedSource = registry.create(
            "scripted_source", sequence=self._samples(case), name="source"
        )
        sink: Sink = registry.create(
            "sink", name="sink", capture=True
        )
        protocol = self.spec.channel("DATA").observation_model
        assert protocol is not None
        source_state = source.initial_state()
        protocol_state = protocol.initial_state()
        sink_state = sink.initial_state()
        transfers = []
        observations = []
        fault = None
        fault_cycle = None
        samples = 0

        while source.offers(source_state):
            source_step = source.step(source_state, EmitNext())
            source_state = source_step.state
            sample = source_step.emissions[0]
            observations.append(sample)
            samples += 1
            protocol_step = protocol.step(protocol_state, sample)
            if protocol_step.fault is not None:
                fault = protocol_step.fault
                fault_cycle = sample.observation.cycle
                break
            protocol_state = protocol_step.state
            for transfer in protocol_step.emissions:
                sink_step = sink.step(sink_state, transfer)
                if sink_step.fault is not None:
                    fault = sink_step.fault
                    break
                sink_state = sink_step.state
                transfers.append(transfer)
            if fault is not None:
                break

        verdict = Verdict.FAIL if fault else (
            Verdict.PASS
            if source.is_quiescent(source_state)
            and protocol.is_quiescent(protocol_state)
            else Verdict.INCONCLUSIVE
        )
        run = ReadyValidSinkRun(
            verdict,
            samples,
            tuple(observations),
            tuple(transfers),
            sink_state,
            fault,
            fault_cycle,
        )
        self.state.update(
            {
                "case": case.name,
                "samples": samples,
                "transfers": len(transfers),
                "sink_received": sink_state.received,
                "fault": fault.rule if fault else None,
            }
        )
        self.transition(ProjectPhase.EXECUTED, f"executed case {case.name}")
        matched = (fault is not None) if case.expect_violation else verdict is Verdict.PASS
        self.transition(
            ProjectPhase.CHECKED if matched else ProjectPhase.FAILED,
            "observed result matched case expectation"
            if matched
            else "observed result did not match case expectation",
        )
        return run
