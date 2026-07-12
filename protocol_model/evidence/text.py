"""Plain-text waveform and validation-process rendering."""

from __future__ import annotations

from typing import Iterable

from protocol_model.core import CanonicalEvent, SemanticRun
from protocol_model.patterns import ReadyValidSample, ResetSample


def _unpack_sample(sample):
    if isinstance(sample, ResetSample):
        return sample.asserted, sample.observation
    return False, sample


def _table(rows):
    widths = [max(len(str(row[index])) for row in rows) for index in range(len(rows[0]))]
    rendered = []
    for row_index, row in enumerate(rows):
        rendered.append(
            "  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row))
        )
        if row_index == 0:
            rendered.append("  ".join("-" * width for width in widths))
    return "\n".join(rendered)


def format_ready_valid_run(
    samples: Iterable[ReadyValidSample | ResetSample[ReadyValidSample]],
    result: SemanticRun,
) -> str:
    """Render waveform samples, monitor actions, transfers, and violations."""

    samples = tuple(samples)
    violations = {violation.index: violation for violation in result.violations}
    rows = [("cycle", "rst", "valid", "ready", "fire", "action", "event")]
    for index, wrapped in enumerate(samples):
        reset, sample = _unpack_sample(wrapped)
        if not isinstance(sample, ReadyValidSample):
            raise TypeError("format_ready_valid_run requires ReadyValidSample observations")
        if index in violations:
            action = f"VIOLATION:{violations[index].rule}"
        elif reset:
            action = "RESET"
        elif sample.valid and sample.ready:
            action = "TRANSFER"
        elif sample.valid:
            action = "STALL"
        else:
            action = "IDLE"
        event = sample.event.short() if sample.event is not None and sample.valid else "-"
        rows.append(
            (
                sample.cycle,
                int(reset),
                int(sample.valid),
                int(sample.ready),
                int(sample.valid and sample.ready and not reset),
                action,
                event,
            )
        )

    lines = ["WAVEFORM / MONITOR PROCESS", _table(rows), "", "LOWERED TRANSFERS"]
    if result.emissions:
        for index, event in enumerate(result.emissions):
            if not isinstance(event, CanonicalEvent):
                lines.append(f"  [{index}] {event!r}")
                continue
            lines.append(
                f"  [{index}] cycle={event.timestamp} source={event.source} {event.short()}"
            )
    else:
        lines.append("  (none)")

    lines.extend(("", "VALIDATION", f"  verdict={result.verdict.value}"))
    if result.violations:
        for violation in result.violations:
            lines.append(
                f"  violation index={violation.index} rule={violation.rule}: {violation.reason}"
            )
    else:
        lines.append("  violations=0")
    return "\n".join(lines)


def _pending_summary(state) -> str:
    pending = getattr(state, "pending", ())
    if not pending:
        return "-"
    return ", ".join(
        f"id={token.key!r}:remaining={token.remaining}/{token.total}"
        for token in pending
    )


def format_cardinality_run(
    events: Iterable[CanonicalEvent],
    result: SemanticRun,
    *,
    begin_kind: str,
    beat_kind: str,
) -> str:
    """Render transaction-token creation and beat-by-beat consumption."""

    events = tuple(events)
    violations = {violation.index: violation for violation in result.violations}
    first_failure = min(violations) if violations else None
    rows = [("index", "event", "action", "marking after event")]
    for index, event in enumerate(events):
        if first_failure is not None and index > first_failure:
            action = "NOT_EVALUATED"
            marking = "-"
        elif index in violations:
            action = f"VIOLATION:{violations[index].rule}"
            marking = _pending_summary(result.state_history[-1])
        else:
            action = "CREATE OBLIGATION" if event.kind == begin_kind else "CONSUME BEAT"
            state_index = min(index + 1, len(result.state_history) - 1)
            marking = _pending_summary(result.state_history[state_index])
        rows.append((index, event.short(), action, marking))

    lines = ["TRANSACTION VALIDATION PROCESS", _table(rows), "", "VALIDATION"]
    lines.append(f"  verdict={result.verdict.value}")
    if result.violations:
        for violation in result.violations:
            lines.append(
                f"  violation index={violation.index} rule={violation.rule}: {violation.reason}"
            )
    else:
        lines.append("  pending=0")
        lines.append("  violations=0")
    return "\n".join(lines)


def _correlated_marking(state) -> str:
    return (
        f"AWq={len(state.descriptors)} "
        f"Wpartial={len(state.current_burst)} "
        f"Wcomplete={len(state.completed_bursts)} "
        f"Bpending={len(state.completions)}"
    )


def format_correlated_run(
    events: Iterable[CanonicalEvent],
    result: SemanticRun,
    *,
    descriptor_kind: str,
    data_kind: str,
    completion_kind: str,
) -> str:
    events = tuple(events)
    violations = {violation.index: violation for violation in result.violations}
    first_failure = min(violations) if violations else None
    rows = [("index", "event", "semantic action", "marking after event")]
    for index, event in enumerate(events):
        if first_failure is not None and index > first_failure:
            action, marking = "NOT_EVALUATED", "-"
        elif index in violations:
            action = f"VIOLATION:{violations[index].rule}"
            marking = _correlated_marking(result.state_history[-1])
        else:
            before = result.state_history[index]
            after = result.state_history[index + 1]
            if event.kind == descriptor_kind:
                action = "QUEUE AW"
            elif event.kind == data_kind:
                action = "WLAST / JOIN" if event.payload.get("last") else "ACCUMULATE W"
            elif event.kind == completion_kind:
                action = "DISCHARGE B"
            else:
                action = "UNKNOWN"
            if len(after.completions) > len(before.completions):
                action += " → CREATE B OBLIGATION"
            marking = _correlated_marking(after)
        rows.append((index, event.short(), action, marking))
    lines = ["WRITE TRANSACTION SEMANTICS", _table(rows), "", "VALIDATION"]
    lines.append(f"  verdict={result.verdict.value}")
    if result.violations:
        violation = result.violations[0]
        lines.append(
            f"  violation index={violation.index} rule={violation.rule}: {violation.reason}"
        )
    else:
        lines.append(f"  final_marking={_correlated_marking(result.final_state)}")
    return "\n".join(lines)
