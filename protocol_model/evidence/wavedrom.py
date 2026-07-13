"""WaveDrom projection of virtual AXI ready/valid pin samples."""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from types import MappingProxyType
from typing import Mapping

from protocol_model.core import CanonicalEvent, Verdict
from protocol_model.engine import ExecutionTrace
from protocol_model.patterns import ReadyValidSample, ResetSample
from protocol_model.protocols.spec import ProtocolSpec
from protocol_model.protocols.axi4.signal import Axi4Cycle, Axi4SignalSession


@dataclass(frozen=True)
class VirtualWaveform:
    samples: Mapping[str, tuple[ResetSample[ReadyValidSample], ...]]
    transfers: tuple[CanonicalEvent, ...]
    field_widths: Mapping[str, Mapping[str, int]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "samples", MappingProxyType(dict(self.samples)))
        object.__setattr__(
            self,
            "field_widths",
            MappingProxyType(
                {
                    channel: MappingProxyType(dict(widths))
                    for channel, widths in self.field_widths.items()
                }
            ),
        )


def synthesize_axi_waveform(
    spec: ProtocolSpec,
    trace: ExecutionTrace[CanonicalEvent],
    *,
    seed: int = 0,
    stall_probability: float = 0.35,
) -> VirtualWaveform:
    if not 0.0 <= stall_probability <= 1.0:
        raise ValueError("stall_probability must be in [0, 1]")
    rng = Random(seed)
    channel_by_kind = {
        channel.transfer.kind: channel.name for channel in spec.channels.values()
    }
    samples = {name: [] for name in spec.channels}
    cycle = 0

    def append_cycle(active=None, ready=False, reset=False):
        nonlocal cycle
        active = active or {}
        for name in spec.channels:
            selected = name in active
            observation = ReadyValidSample(
                cycle,
                selected,
                ready if selected else rng.choice((False, True)),
                active.get(name),
                "aclk",
                f"virtual_{name.lower()}",
            )
            samples[name].append(ResetSample(reset, observation))
        cycle += 1

    append_cycle(reset=True)
    for step in trace.steps:
        active = {
            channel_by_kind[trace.events[index].kind]: trace.events[index]
            for index in step
        }
        if rng.random() < stall_probability:
            append_cycle(active, ready=False)
        append_cycle(active, ready=True)

    frozen = {name: tuple(channel_samples) for name, channel_samples in samples.items()}
    interface_cycles = tuple(
        Axi4Cycle({name: frozen[name][index] for name in spec.channels})
        for index in range(cycle)
    )
    result = Axi4SignalSession(spec=spec).run(interface_cycles)
    if result.verdict == Verdict.FAIL:
        violation = result.violations[0]
        raise RuntimeError(f"virtual waveform violated {violation.rule}: {violation.reason}")
    transfers = result.emissions
    return VirtualWaveform(frozen, tuple(transfers), _field_widths(spec))


def _field_widths(spec: ProtocolSpec):
    field_widths = {}
    for name, channel in spec.channels.items():
        widths = {}
        key_width = getattr(channel.transfer.key, "width", None)
        if key_width is not None:
            widths["id"] = key_width
        for field_name, domain in channel.transfer.payload.items():
            width = getattr(domain, "width", None)
            if width is not None:
                widths[field_name] = width
        field_widths[name] = widths
    return field_widths


def synthesize_axi_network_timeline(
    spec: ProtocolSpec,
    located_events,
    *,
    location: str,
) -> VirtualWaveform:
    """Place network events on one shared cycle axis for a single AXI link."""

    channel_by_kind = {
        channel.transfer.kind: channel.name for channel in spec.channels.values()
    }
    samples = {name: [] for name in spec.channels}
    transfers = []
    total_cycles = len(located_events) + 1
    for cycle in range(total_cycles):
        located = located_events[cycle - 1] if cycle else None
        active_name = None
        active_event = None
        if located is not None and located.location == location:
            active_event = located.event
            active_name = channel_by_kind[active_event.kind]
            transfers.append(active_event)
        for name in spec.channels:
            active = name == active_name
            samples[name].append(
                ResetSample(
                    cycle == 0,
                    ReadyValidSample(
                        cycle,
                        active,
                        active,
                        active_event if active else None,
                        "aclk",
                        f"network_{location.lower()}",
                    ),
                )
            )
    frozen = {name: tuple(items) for name, items in samples.items()}
    interface_cycles = tuple(
        Axi4Cycle({name: frozen[name][cycle] for name in spec.channels})
        for cycle in range(total_cycles)
    )
    result = Axi4SignalSession(spec=spec).run(interface_cycles)
    if result.verdict == Verdict.FAIL:
        violation = result.violations[0]
        raise RuntimeError(
            f"network waveform violated {violation.rule}: {violation.reason}"
        )
    return VirtualWaveform(frozen, tuple(transfers), _field_widths(spec))


def synthesize_axi_attempt_waveform(
    spec: ProtocolSpec, event: CanonicalEvent
) -> VirtualWaveform:
    """Project one attempted transfer, including an event rejected by the spec."""

    return synthesize_axi_event_sequence_waveform(spec, (event,))


def synthesize_axi_event_sequence_waveform(
    spec: ProtocolSpec, events
) -> VirtualWaveform:
    """Project canonical attempts without requiring the sequence to be legal."""

    channel_by_kind = {
        channel.transfer.kind: channel.name for channel in spec.channels.values()
    }
    events = tuple(events)
    unknown = [event.kind for event in events if event.kind not in channel_by_kind]
    if unknown:
        raise ValueError(f"event kind {unknown[0]!r} is not an AXI channel transfer")
    samples = {name: [] for name in spec.channels}
    for name in spec.channels:
        samples[name].append(
            ResetSample(
                True,
                ReadyValidSample(0, False, False, clock="aclk", source="attempt"),
            )
        )
    for cycle, event in enumerate(events, start=1):
        active_name = channel_by_kind[event.kind]
        for name in spec.channels:
            active = name == active_name
            samples[name].append(
                ResetSample(
                    False,
                    ReadyValidSample(
                        cycle,
                        active,
                        active,
                        event if active else None,
                        "aclk",
                        "attempt",
                    ),
                )
            )
    frozen = {name: tuple(items) for name, items in samples.items()}
    return VirtualWaveform(frozen, events, _field_widths(spec))


def axi_cycles_to_waveform(
    spec: ProtocolSpec, cycles: tuple[Axi4Cycle, ...]
) -> VirtualWaveform:
    """Retain raw signal attempts, including cycles rejected by a profile."""

    samples = {}
    has_reset_prefix = bool(cycles) and all(
        wrapped.asserted for wrapped in cycles[0].channels.values()
    )
    for name in spec.channels:
        reset = ResetSample(
            True,
            ReadyValidSample(0, False, False, clock="aclk", source="attempt"),
        )
        prefix = () if has_reset_prefix else (reset,)
        samples[name] = (*prefix, *(cycle.channels[name] for cycle in cycles))
    transfers = tuple(
        wrapped.observation.event
        for cycle in cycles
        for wrapped in cycle.channels.values()
        if wrapped.observation.valid and wrapped.observation.event is not None
    )
    return VirtualWaveform(samples, transfers, _field_widths(spec))


def _bit_wave(values) -> str:
    wave = []
    previous = None
    for value in values:
        symbol = "1" if value else "0"
        wave.append("." if symbol == previous else symbol)
        previous = symbol
    return "".join(wave)


def _format_field(name: str, value: object, width: int | None = None) -> str:
    if name in {"addr", "data", "strb"}:
        raw = format(int(value), "x")
        if width is not None:
            raw = raw.zfill((width + 3) // 4)
        if len(raw) > 4:
            shown = f"{raw[:2]}..{raw[-2:]}"
        else:
            shown = raw
        suffix = f" '{width}" if width else ""
        return f"0x{shown}{suffix}"
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _field_lane(
    channel_samples, name: str, *, key: bool = False, width: int | None = None
):
    wave = []
    data = []
    unset = object()
    previous = unset
    was_active = False
    for wrapped in channel_samples:
        sample = wrapped.observation
        if not sample.valid:
            wave.append("x" if was_active or not wave else ".")
            previous = unset
            was_active = False
            continue
        value = sample.event.key if key else sample.event.payload[name]
        if was_active and previous is not unset and value == previous:
            wave.append(".")
        else:
            wave.append("=")
            data.append(_format_field(name, value, width))
        previous = value
        was_active = True
    return "".join(wave), data


def to_wavejson(
    waveform: VirtualWaveform,
    *,
    title: str = "AXI4 virtual waveform",
    hide_inactive_channels: bool = False,
):
    names = tuple(waveform.samples)
    length = len(waveform.samples[names[0]]) if names else 0
    first = waveform.samples[names[0]] if names else ()
    signals = [
        {"name": "ACLK", "wave": "p" + "." * max(0, length - 1)},
        {"name": "ARESETn", "wave": _bit_wave(not item.asserted for item in first)},
    ]
    reset_waves = {
        name: _bit_wave(not item.asserted for item in waveform.samples[name])
        for name in names
    }
    if len(set(reset_waves.values())) > 1:
        signals.append(
            [
                "RESET BY CHANNEL",
                *(
                    {"name": f"{name}RESETn", "wave": reset_waves[name]}
                    for name in names
                ),
            ]
        )
    for name in names:
        channel_samples = waveform.samples[name]
        valid = [item.observation.valid for item in channel_samples]
        if hide_inactive_channels and not any(valid):
            continue
        ready = [item.observation.ready for item in channel_samples]
        reset = [item.asserted for item in channel_samples]
        fire = [v and r and not rst for v, r, rst in zip(valid, ready, reset)]
        group = [
            name,
            {"name": f"{name}VALID", "wave": _bit_wave(valid)},
            {"name": f"{name}READY", "wave": _bit_wave(ready)},
            {"name": f"{name}FIRE", "wave": _bit_wave(fire)},
        ]
        first_event = next(
            (
                item.observation.event
                for item in channel_samples
                if item.observation.valid
            ),
            None,
        )
        if first_event is not None and first_event.key is not None:
            wave, data = _field_lane(
                channel_samples,
                "id",
                key=True,
                width=waveform.field_widths[name].get("id"),
            )
            group.append({"name": f"{name}ID", "wave": wave, "data": data})
        if first_event is not None:
            for field_name in first_event.payload:
                wave, data = _field_lane(
                    channel_samples,
                    field_name,
                    width=waveform.field_widths[name].get(field_name),
                )
                group.append(
                    {
                        "name": f"{name}{field_name.upper()}",
                        "wave": wave,
                        "data": data,
                    }
                )
        signals.append(group)
    return {
        "signal": signals,
        "head": {"text": title, "tick": 0},
        "config": {"hscale": 3},
    }
