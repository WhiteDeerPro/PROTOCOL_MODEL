"""User-facing project for two AXI links coupled by a read bridge."""

from __future__ import annotations

from dataclasses import dataclass, replace
from random import Random

from protocol_model.core import SemanticFault, Verdict
from protocol_model.engine import ExecutionTrace
from protocol_model.protocols.axi4 import Axi4Config, build_axi4_spec

from ..base import ComponentUse, ProjectPhase, VerificationProject
from .network import LinkRuntime, LocatedEvent, NetworkRecorder
from .virtual_dut_bridge import AxiReadBridge, BridgeInput
from .virtual_dut_responder import DumbAxiReadResponder


@dataclass(frozen=True)
class NetworkMilestone:
    name: str
    link_a_pending: int
    bridge_pending: int
    link_b_pending: int


@dataclass(frozen=True)
class AxiReadNetworkRun:
    verdict: Verdict
    trace: ExecutionTrace[LocatedEvent]
    milestones: tuple[NetworkMilestone, ...]
    fault: SemanticFault | None = None


@dataclass(frozen=True)
class AxiReadCase:
    name: str = "legal_4kb_edge"
    address: int = 0xFF0
    length: int = 3
    size: int = 2
    burst: str = "INCR"
    upstream_id: int = 3
    expect_violation: bool = False


class AxiReadNetworkProject(VerificationProject):
    """Lifecycle owner for Initiator → AXI-A → bridge → AXI-B → responder."""

    def __init__(self, config: Axi4Config | None = None):
        self.config = config or Axi4Config()
        super().__init__(
            "prj_axi4_read_bridge",
            (
                ComponentUse("stimulus", "test", "AxiReadCase", "inject one AR burst"),
                ComponentUse("AXI-A", "link", "ProtocolSession[AXI4]", "upstream protocol instance"),
                ComponentUse("bridge", "virtual_dut", "AxiReadBridge", "ID-remapping read forward bridge"),
                ComponentUse("AXI-B", "link", "ProtocolSession[AXI4]", "downstream protocol instance"),
                ComponentUse("responder", "virtual_dut", "DumbAxiReadResponder", "terminating read endpoint"),
            ),
        )
        self.spec_a = None
        self.spec_b = None

    def elaborate(self) -> None:
        self.spec_a = build_axi4_spec(self.config)
        self.spec_b = build_axi4_spec(self.config)
        self.state.update({"links": 2, "dut_count": 2, "case": None})
        self.transition(ProjectPhase.ELABORATED, "created two independent AXI4 sessions and DUT definitions")

    @staticmethod
    def _pending(link: LinkRuntime) -> int:
        return len(link.state.state_of("read").pending)

    def run_case(self, case: AxiReadCase) -> AxiReadNetworkRun:
        if self.phase is ProjectPhase.CREATED:
            self.elaborate()
        if self.phase is not ProjectPhase.ELABORATED:
            raise RuntimeError(f"project must be ELABORATED, got {self.phase.value}")
        assert self.spec_a is not None and self.spec_b is not None
        self.state["case"] = case.name
        recorder = NetworkRecorder()
        link_a = LinkRuntime("AXI-A", self.spec_a.open_session(), recorder)
        link_b = LinkRuntime("AXI-B", self.spec_b.open_session(), recorder)
        bridge = AxiReadBridge(downstream_id_width=self.config.id_width)
        bridge_state = bridge.initial_state()
        responder = DumbAxiReadResponder(self.spec_b)
        milestones = []

        request_space = self.spec_a.channel("AR").transfer
        sampled = request_space.sample(Random(1))
        request = replace(
            sampled,
            key=case.upstream_id,
            payload={
                **sampled.payload,
                "addr": case.address,
                "len": case.length,
                "size": case.size,
                "burst": case.burst,
            },
        )
        accepted_a, ar_a_index, fault = link_a.accept(request)
        if fault is not None:
            milestones.append(NetworkMilestone("rejected_at_link_a", 0, 0, 0))
            run = AxiReadNetworkRun(Verdict.FAIL, recorder.trace(), tuple(milestones), fault)
            return self._finish_case(case, run)
        assert accepted_a is not None and ar_a_index is not None
        milestones.append(
            NetworkMilestone("after_ar_a", self._pending(link_a), 0, 0)
        )

        bridge_step = bridge.step(
            bridge_state,
            BridgeInput("upstream", replace(accepted_a, trace_index=ar_a_index)),
        )
        if bridge_step.fault is not None:
            run = AxiReadNetworkRun(
                Verdict.FAIL, recorder.trace(), tuple(milestones), bridge_step.fault
            )
            return self._finish_case(case, run)
        bridge_state = bridge_step.state
        forwarded_ar = bridge_step.emissions[0].event
        accepted_b, ar_b_index, fault = link_b.accept(
            forwarded_ar, parents=(ar_a_index,)
        )
        if fault is not None:
            run = AxiReadNetworkRun(Verdict.FAIL, recorder.trace(), tuple(milestones), fault)
            return self._finish_case(case, run)
        assert accepted_b is not None and ar_b_index is not None
        milestones.append(
            NetworkMilestone(
                "after_ar_b",
                self._pending(link_a),
                len(bridge_state.pending),
                self._pending(link_b),
            )
        )

        response_step = responder.step(responder.initial_state(), accepted_b)
        if response_step.fault is not None:
            run = AxiReadNetworkRun(
                Verdict.FAIL, recorder.trace(), tuple(milestones), response_step.fault
            )
            return self._finish_case(case, run)
        for beat, downstream_r in enumerate(response_step.emissions):
            accepted_r_b, r_b_index, fault = link_b.accept(downstream_r)
            if fault is not None:
                run = AxiReadNetworkRun(
                    Verdict.FAIL, recorder.trace(), tuple(milestones), fault
                )
                return self._finish_case(case, run)
            assert accepted_r_b is not None and r_b_index is not None
            bridge_step = bridge.step(
                bridge_state,
                BridgeInput(
                    "downstream", replace(accepted_r_b, trace_index=r_b_index)
                ),
            )
            if bridge_step.fault is not None:
                run = AxiReadNetworkRun(
                    Verdict.FAIL,
                    recorder.trace(),
                    tuple(milestones),
                    bridge_step.fault,
                )
                return self._finish_case(case, run)
            bridge_state = bridge_step.state
            upstream_r = bridge_step.emissions[0].event
            _, _, fault = link_a.accept(upstream_r, parents=(r_b_index,))
            if fault is not None:
                run = AxiReadNetworkRun(
                    Verdict.FAIL, recorder.trace(), tuple(milestones), fault
                )
                return self._finish_case(case, run)
            milestones.append(
                NetworkMilestone(
                    f"after_r_beat_{beat}",
                    self._pending(link_a),
                    len(bridge_state.pending),
                    self._pending(link_b),
                )
            )

        quiescent = link_a.quiescent and link_b.quiescent and bridge.is_quiescent(bridge_state)
        run = AxiReadNetworkRun(
            Verdict.PASS if quiescent else Verdict.INCONCLUSIVE,
            recorder.trace(),
            tuple(milestones),
        )
        return self._finish_case(case, run)

    def _finish_case(
        self, case: AxiReadCase, run: AxiReadNetworkRun
    ) -> AxiReadNetworkRun:
        self.state.update(
            {
                "verdict": run.verdict.value,
                "events": len(run.trace.events),
                "fault": run.fault.rule if run.fault else None,
            }
        )
        self.transition(ProjectPhase.EXECUTED, f"executed case {case.name}")
        matched = (run.fault is not None) if case.expect_violation else run.verdict is Verdict.PASS
        if matched:
            self.transition(ProjectPhase.CHECKED, "observed result matched case expectation")
        else:
            self.transition(ProjectPhase.FAILED, "observed result did not match case expectation")
        return run
