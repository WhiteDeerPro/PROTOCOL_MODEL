"""APB3/APB4 comparison as a proper protocol-instance Project."""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from protocol_model.core import Verdict
from protocol_model.protocols.spec import ProtocolInstance
from protocol_model.protocols.apb import ApbConfig, ApbGeneratedTrace, build_apb_spec, generate_apb_trace
from protocol_model.virtual_dut import EmitNext, ScriptedSource, Sink

from ..lifecycle import ComponentUse, ProjectPhase, VerificationProject


@dataclass(frozen=True)
class ApbComparisonRun:
    verdict: Verdict
    traces: Mapping[int, ApbGeneratedTrace]
    mutation_trace: ApbGeneratedTrace
    mutation_rule: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "traces", MappingProxyType(dict(self.traces)))


class ApbComparisonProject(VerificationProject):
    """Bind protocol definitions, generate observations, and check one mutation."""

    def __init__(self):
        self.configs = {3: ApbConfig(3), 4: ApbConfig(4)}
        self.protocols: dict[int, ProtocolInstance] = {}
        super().__init__(
            "prj_apb_compare",
            (
                ComponentUse(
                    "stimulus",
                    "virtual_dut",
                    "ScriptedSource[ApbPinSample]",
                    "produce legal APB pin observations",
                ),
                ComponentUse(
                    "APB3",
                    "protocol",
                    "ProtocolInstance[APB3]",
                    "lower/check APB3 observations",
                ),
                ComponentUse(
                    "APB4",
                    "protocol",
                    "ProtocolInstance[APB4]",
                    "lower/check APB4 observations",
                ),
                ComponentUse(
                    "collector",
                    "virtual_dut",
                    "Sink[APB_TRANSFER, capture=True]",
                    "retain accepted canonical APB transfers",
                ),
            ),
        )

    def elaborate(self) -> None:
        self.protocols = {
            version: ProtocolInstance.bind(
                f"APB{version}", build_apb_spec(config), owner=self.name
            )
            for version, config in self.configs.items()
        }
        self.state.update(
            {
                "base_protocols": tuple(
                    item.base_spec.name for item in self.protocols.values()
                ),
                "protocol_instances": tuple(
                    item.qualified_name for item in self.protocols.values()
                ),
            }
        )
        self.transition(
            ProjectPhase.ELABORATED,
            "bound APB3/APB4 protocol instances to the comparison network",
        )

    def run(self, *, transactions: int = 4, seed: int = 41) -> ApbComparisonRun:
        if self.phase is ProjectPhase.CREATED:
            self.elaborate()
        if self.phase is not ProjectPhase.ELABORATED:
            raise RuntimeError(f"project must be ELABORATED, got {self.phase.value}")

        traces = {}
        for version, instance in self.protocols.items():
            generated = generate_apb_trace(
                self.configs[version],
                transactions=transactions,
                seed=seed + version,
                spec=instance.spec,
            )
            source = ScriptedSource(
                generated.samples, name=f"apb{version}_pin_source"
            )
            sink = Sink(name=f"apb{version}_transfer_sink", capture=True)
            monitor = instance.channel("APB").observation_model
            assert monitor is not None
            source_state = source.initial_state()
            monitor_state = monitor.initial_state()
            sink_state = sink.initial_state()
            while source.offers(source_state):
                source_step = source.step(source_state, EmitNext())
                source_state = source_step.state
                protocol_step = monitor.step(
                    monitor_state, source_step.emissions[0]
                )
                if protocol_step.fault is not None:
                    raise RuntimeError(
                        f"bound APB{version} instance rejected generated trace: "
                        f"{protocol_step.fault.rule}"
                    )
                monitor_state = protocol_step.state
                for transfer in protocol_step.emissions:
                    sink_step = sink.step(sink_state, transfer)
                    if sink_step.fault is not None:
                        raise RuntimeError(sink_step.fault.reason)
                    sink_state = sink_step.state
            traces[version] = ApbGeneratedTrace(
                generated.samples, sink_state.retained
            )
        mutated = list(traces[4].samples)
        setup_index = next(
            index
            for index, sample in enumerate(mutated)
            if sample.psel and not sample.penable
        )
        access = mutated[setup_index + 1]
        mutated[setup_index + 1] = replace(access, paddr=access.paddr ^ 1)
        monitor = self.protocols[4].channel("APB").observation_model
        assert monitor is not None
        mutation = monitor.run(mutated)
        mutation_rule = (
            mutation.violations[0].rule if mutation.violations else "NO VIOLATION"
        )
        verdict = (
            Verdict.PASS
            if mutation_rule.endswith("request_stability")
            else Verdict.FAIL
        )
        self.state.update(
            {
                "transactions": transactions,
                "apb3_cycles": len(traces[3].samples),
                "apb4_cycles": len(traces[4].samples),
                "apb3_collected": len(traces[3].transfers),
                "apb4_collected": len(traces[4].transfers),
                "mutation_rule": mutation_rule,
                "verdict": verdict.value,
            }
        )
        self.transition(ProjectPhase.EXECUTED, "ran both bound APB protocol instances")
        self.transition(
            ProjectPhase.CHECKED if verdict is Verdict.PASS else ProjectPhase.FAILED,
            "APB4 mutation matched expectation"
            if verdict is Verdict.PASS
            else "APB4 mutation was not detected",
        )
        return ApbComparisonRun(
            verdict,
            traces,
            ApbGeneratedTrace(tuple(mutated), tuple(mutation.emissions)),
            mutation_rule,
        )
