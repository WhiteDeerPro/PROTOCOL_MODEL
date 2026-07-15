"""Execute example inputs through the repository's actual AXI4 components."""

from __future__ import annotations

from dataclasses import dataclass

from protocol_model import AtomicFrame, CanonicalEvent, ReadyValidSignals, Verdict
from protocol_model.link.amba.axi.axi4 import Axi4ObservationSession
from protocol_model.semantics import SemanticFault

from common import AXI4_CHANNELS, ExecutionMode, ExampleCase


@dataclass(frozen=True)
class ExampleRun:
    case: ExampleCase
    actual_verdict: Verdict
    expectation_met: bool
    accepted_events: tuple[CanonicalEvent, ...]
    causal_edges: tuple[tuple[int, int], ...]
    resource_peak: dict[str, int]
    final_resources: dict[str, int]
    fault: SemanticFault | None = None


def _event_record(event: CanonicalEvent) -> dict[str, object]:
    return {
        "kind": event.kind,
        "key": event.key,
        "payload": dict(event.payload),
        "source": event.source,
        "clock": event.clock,
        "timestamp": event.timestamp,
        "trace_index": event.trace_index,
    }


def _frame_record(frame: AtomicFrame) -> dict[str, object]:
    lanes = {}
    for name in AXI4_CHANNELS:
        signals = frame.get(name)
        assert isinstance(signals, ReadyValidSignals)
        lanes[name] = {
            "valid": signals.valid,
            "ready": signals.ready,
            "event": (
                _event_record(signals.event)
                if signals.event is not None
                else None
            ),
        }
    return {
        "type": "AtomicFrame",
        "tick": frame.tick,
        "clock": frame.clock,
        "reset": frame.get("reset"),
        "source": frame.source,
        "lanes": lanes,
    }


def _fault_record(fault: SemanticFault | None) -> dict[str, object] | None:
    if fault is None:
        return None
    return {
        "rule": fault.rule,
        "reason": fault.reason,
        "scope": fault.scope.value,
        "location": fault.location,
    }


def _resource_projection(component, states, *, observation: bool):
    snapshots = []
    for state in states:
        link_state = state.link_state if observation else state
        snapshots.append(dict(component.resource_usage(link_state)))
    names = {name for snapshot in snapshots for name in snapshot}
    peak = {
        name: max(snapshot.get(name, 0) for snapshot in snapshots)
        for name in sorted(names)
    }
    final = snapshots[-1] if snapshots else {}
    return peak, final


def execute(case: ExampleCase) -> ExampleRun:
    """Run a case and compare its declared expectation with model evidence."""

    if case.mode is ExecutionMode.LINK:
        if not all(isinstance(item, CanonicalEvent) for item in case.actions):
            raise TypeError(f"link case {case.name!r} contains a non-event input")
        component = case.protocol.open_session()
        semantic_run = component.run(case.actions)
        peak, final = _resource_projection(
            component, semantic_run.state_history, observation=False
        )
        causal_edges = semantic_run.final_state.causal_edges
    else:
        if not all(isinstance(item, AtomicFrame) for item in case.actions):
            raise TypeError(
                f"observation case {case.name!r} contains a non-frame input"
            )
        observer = Axi4ObservationSession(case.protocol)
        semantic_run = observer.run(case.actions)
        peak, final = _resource_projection(
            observer.link_session,
            semantic_run.state_history,
            observation=True,
        )
        causal_edges = semantic_run.final_state.link_state.causal_edges

    fault = (
        semantic_run.violations[0].fault if semantic_run.violations else None
    )
    rule_matches = (
        case.expected_rule is None
        or (fault is not None and fault.rule == case.expected_rule)
    )
    reason_matches = (
        case.expected_reason_contains is None
        or (
            fault is not None
            and case.expected_reason_contains in fault.reason
        )
    )
    expectation_met = (
        semantic_run.verdict is case.expected_verdict
        and rule_matches
        and reason_matches
    )
    return ExampleRun(
        case=case,
        actual_verdict=semantic_run.verdict,
        expectation_met=expectation_met,
        accepted_events=tuple(semantic_run.emissions),
        causal_edges=tuple(causal_edges),
        resource_peak=peak,
        final_resources=final,
        fault=fault,
    )


def result_record(run: ExampleRun) -> dict[str, object]:
    inputs = []
    for action in run.case.actions:
        if isinstance(action, CanonicalEvent):
            inputs.append({"type": "CanonicalEvent", **_event_record(action)})
        else:
            assert isinstance(action, AtomicFrame)
            inputs.append(_frame_record(action))
    return {
        "schema": "protocol-model.showcase.axi4-example/v1",
        "name": run.case.name,
        "theme": run.case.theme,
        "title": {"en": run.case.title_en, "zh-CN": run.case.title_zh},
        "claim": {"en": run.case.claim_en, "zh-CN": run.case.claim_zh},
        "execution": {
            "mode": run.case.mode.value,
            "protocol": run.case.protocol.name,
            "model": (
                "LinkSession"
                if run.case.mode is ExecutionMode.LINK
                else "Axi4ObservationSession"
            ),
        },
        "presentation": {
            "level": "deep-dive" if run.case.deep_dive else "catalog",
        },
        "expected": {
            "verdict": run.case.expected_verdict.value,
            "rule": run.case.expected_rule,
            "reason_contains": run.case.expected_reason_contains,
        },
        "observed": {
            "verdict": run.actual_verdict.value,
            "rule": run.fault.rule if run.fault is not None else None,
            "expectation_met": run.expectation_met,
        },
        "inputs": inputs,
        "accepted_events": [_event_record(item) for item in run.accepted_events],
        "causal_edges": [list(item) for item in run.causal_edges],
        "resources": {
            "peak": run.resource_peak,
            "final": run.final_resources,
        },
        "fault": _fault_record(run.fault),
    }


def compact_record(run: ExampleRun) -> dict[str, object]:
    return {
        "name": run.case.name,
        "theme": run.case.theme,
        "title": {"en": run.case.title_en, "zh-CN": run.case.title_zh},
        "mode": run.case.mode.value,
        "protocol": run.case.protocol.name,
        "expected": run.case.expected_verdict.value,
        "observed": run.actual_verdict.value,
        "rule": run.fault.rule if run.fault is not None else None,
        "expectation": "MET" if run.expectation_met else "MISMATCH",
        "result": f"cases/{run.case.name}/result.json",
        "waveform": f"cases/{run.case.name}/waveform.svg",
        "causality": f"cases/{run.case.name}/causality.svg",
        "deep_dive": run.case.deep_dive,
    }


__all__ = [
    "ExampleRun",
    "compact_record",
    "execute",
    "result_record",
]
