#!/usr/bin/env python3
"""Execute and publish the four-phase handshake and CDC-frequency showcase."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory


if sys.version_info < (3, 10):
    raise SystemExit("this demo requires Python 3.10 or newer")


DEMO_DIRECTORY = Path(__file__).resolve().parent
REPOSITORY_ROOT = DEMO_DIRECTORY.parents[3]
SHOWCASE_ROOT = REPOSITORY_ROOT / "showcase"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


from protocol_model import __version__  # noqa: E402
from protocol_model.artifacts import (  # noqa: E402
    RunArtifactStore,
    protocol_record_from_interface,
)
from protocol_model.protocols.asynchronous import (  # noqa: E402
    FourPhaseTokenConfig,
    build_four_phase_token_interface,
)
from protocol_model.observation import (  # noqa: E402
    AsynchronousSample,
    FourPhaseDataWindow,
    FourPhaseObserver,
    FourPhaseSignals,
)
from protocol_model.semantics import CanonicalEvent, Verdict  # noqa: E402
from protocol_model.visualization import VisualizationPublisher  # noqa: E402


DEMO_NAME = "four-phase-handshake"
DATA_WIDTH = 8


@dataclass(frozen=True)
class ExampleCase:
    name: str
    title: str
    purpose: str
    samples: tuple[AsynchronousSample, ...]
    expected: Verdict
    expected_rule_suffix: str | None = None


@dataclass(frozen=True)
class ExampleRun:
    case: ExampleCase
    semantic_run: object
    actual: Verdict
    fault: object | None
    expectation_met: bool


def _event(reference: int, data: int) -> CanonicalEvent:
    return CanonicalEvent("TRANSFER", reference, {"data": data})


def _sample(
    sequence: int,
    timestamp_ns: float,
    req: bool,
    ack: bool,
    event: CanonicalEvent | None = None,
) -> AsynchronousSample:
    return AsynchronousSample(
        sequence,
        {"mailbox": FourPhaseSignals(req, ack, event)},
        timestamp=timestamp_ns,
        source="model-authored async snapshots",
    )


def _build_cases() -> tuple[ExampleCase, ...]:
    stable = _event(17, 0x5A)
    legal = ExampleCase(
        "legal-delayed-ack",
        "合法传输：接收端任意等待后确认",
        "REQ 保持期间 payload 稳定；ACK 上升只产生一个 TRANSFER。",
        (
            _sample(0, 0.0, False, False),
            _sample(1, 2.7, True, False, stable),
            _sample(2, 5.2, True, False, stable),
            _sample(3, 9.9, True, False, stable),
            _sample(4, 12.4, True, True, stable),
            _sample(5, 15.0, False, True),
            _sample(6, 18.6, False, False),
        ),
        Verdict.PASS,
    )
    ack_early = ExampleCase(
        "ack-before-request",
        "非法传输：ACK 在 REQ 前出现",
        "idle 不能直接进入 01；错误在单 link observation 边界定位。",
        (
            _sample(0, 0.0, False, False),
            _sample(1, 3.1, False, True),
        ),
        Verdict.FAIL,
        "phase_order",
    )
    overwritten = ExampleCase(
        "payload-overwrite-before-ack",
        "非法传输：等待 ACK 时 payload 被覆盖",
        "默认 EARLY window 要求 REQ 上升至 ACK 上升期间 event identity 稳定。",
        (
            _sample(0, 0.0, False, False),
            _sample(1, 2.0, True, False, _event(23, 0x31)),
            _sample(2, 7.5, True, False, _event(23, 0xC7)),
        ),
        Verdict.FAIL,
        "event_stability",
    )
    return legal, ack_early, overwritten


def _execute(case: ExampleCase, transfer_schema) -> ExampleRun:
    observer = FourPhaseObserver(
        f"showcase.{case.name}",
        "mailbox",
        transfer_schema,
        FourPhaseDataWindow.EARLY,
    )
    semantic_run = observer.run(case.samples)
    fault = (
        semantic_run.violations[0].fault
        if semantic_run.violations
        else None
    )
    expectation_met = semantic_run.verdict is case.expected
    if case.expected_rule_suffix is not None:
        expectation_met = (
            expectation_met
            and fault is not None
            and fault.rule.endswith(case.expected_rule_suffix)
        )
    return ExampleRun(
        case,
        semantic_run,
        semantic_run.verdict,
        fault,
        expectation_met,
    )


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _bool_wave(values: list[bool]) -> str:
    previous: bool | None = None
    symbols = []
    for value in values:
        symbols.append("." if value is previous else ("1" if value else "0"))
        previous = value
    return "".join(symbols)


def _categorical_lane(name: str, values: list[object]) -> dict[str, object]:
    return {
        "name": name,
        "wave": "=" * len(values),
        "data": [str(value) for value in values],
    }


def _sparse_lane(
    name: str, values: list[object | None]
) -> dict[str, object]:
    wave = []
    data = []
    idle = False
    for value in values:
        if value is None:
            wave.append("." if idle else "x")
            idle = True
        else:
            wave.append("=")
            data.append(str(value))
            idle = False
    return {"name": name, "wave": "".join(wave), "data": data}


def _pair_name(req: bool, ack: bool) -> str:
    return {
        (False, False): "00 idle",
        (True, False): "10 requested",
        (True, True): "11 acknowledged",
        (False, True): "01 returning",
    }[(req, ack)]


def _case_wavejson(run: ExampleRun) -> dict[str, object]:
    samples = run.case.samples
    signals = [sample.get("mailbox") for sample in samples]
    accepted_sequences = {
        event.sequence for event in run.semantic_run.emissions
    }
    state_history = run.semantic_run.state_history[1:]
    fault_index = (
        run.semantic_run.violations[0].index
        if run.semantic_run.violations
        else None
    )
    phase_values = []
    for index, (signal, state) in enumerate(zip(signals, state_history)):
        phase = state.phase.value
        if fault_index == index:
            phase = f"REJECT · {_pair_name(signal.req, signal.ack)}"
        phase_values.append(phase)
    payloads = [
        (
            None
            if signal.event is None
            else f"ref={signal.event.key} · 0x{int(signal.event.payload['data']):02X}"
        )
        for signal in signals
    ]
    diagnostics = [None] * len(samples)
    if run.fault is not None:
        diagnostics[-1] = run.fault.rule
    else:
        diagnostics[-1] = "PASS"
    return {
        "signal": [
            _categorical_lane(
                "OBSERVATION ORDER · not clock",
                [f"S{sample.sequence}" for sample in samples],
            ),
            _categorical_lane(
                "timestamp note (ns)",
                [f"{float(sample.timestamp):g}" for sample in samples],
            ),
            {"name": "pin · REQ", "wave": _bool_wave([item.req for item in signals])},
            {"name": "pin · ACK", "wave": _bool_wave([item.ack for item in signals])},
            _sparse_lane("pin · bundled event", payloads),
            _categorical_lane("model · observer post-state", phase_values),
            {
                "name": "model · accepted TRANSFER",
                "wave": _bool_wave(
                    [sample.sequence in accepted_sequences for sample in samples]
                ),
            },
            _sparse_lane("model · verdict / diagnostic", diagnostics),
        ],
        "head": {"text": run.case.title},
        "foot": {
            "text": (
                "Edge-complete logical snapshots · timestamps are annotations · "
                "not a shared-clock RTL/VCD capture"
            )
        },
        "config": {"hscale": 3},
    }


def _case_causality_dot(run: ExampleRun) -> str:
    lines = [
        "digraph four_phase_case {",
        "  rankdir=TB;",
        f"  label={_quoted(run.case.title + ' · observation-order evidence')};",
        '  labelloc="t";',
        '  graph [bgcolor="white", pad=0.25, nodesep=0.3, ranksep=0.38, splines=polyline];',
        '  node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=10];',
        '  edge [fontname="sans-serif", fontsize=9, color="#5f7280"];',
    ]
    fault_index = (
        run.semantic_run.violations[0].index
        if run.semantic_run.violations
        else None
    )
    for index, sample in enumerate(run.case.samples):
        signal = sample.get("mailbox")
        fill = "#fee2e2" if index == fault_index else "#e8f1fb"
        label = (
            f"S{sample.sequence} · t={float(sample.timestamp):g} ns\n"
            f"{_pair_name(signal.req, signal.ack)}"
        )
        lines.append(
            f"  s{index} [label={_quoted(label)}, fillcolor={_quoted(fill)}, "
            'color="#537a99"];'
        )
        if index:
            lines.append(
                f"  s{index - 1} -> s{index} [label=\"observed next\"];"
            )
    for event_index, event in enumerate(run.semantic_run.emissions):
        source_index = next(
            index
            for index, sample in enumerate(run.case.samples)
            if sample.sequence == event.sequence
        )
        label = (
            f"TRANSFER accepted\nref={event.key} "
            f"data=0x{int(event.payload['data']):02X}"
        )
        lines.append(
            f"  e{event_index} [shape=diamond, label={_quoted(label)}, "
            'fillcolor="#dcfce7", color="#2f855a"];'
        )
        lines.append(
            f"  s{source_index} -> e{event_index} "
            '[label="ACK↑ lowers to event", color="#2f855a"];'
        )
    if run.fault is not None:
        label = f"{run.fault.rule}\n{run.fault.reason}"
        lines.append(
            f"  fault [shape=octagon, label={_quoted(label)}, "
            'fillcolor="#fecaca", color="#b91c1c"];'
        )
        lines.append(
            f"  s{fault_index} -> fault [label=\"diagnostic\", color=\"#b91c1c\"];"
        )
    lines.extend(
        (
            '  note [shape=note, label="Edges above preserve observation order;\\n'
            'they are not physical delay or cross-event CausalGraph edges", '
            'fillcolor="#fff7d6", color="#b7791f"];',
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def _decision_dot() -> str:
    return r'''digraph async_choice {
  rankdir=TB;
  label="Where asynchronous handshakes appear / 异步握手出现在哪里";
  labelloc="t";
  graph [bgcolor="white", pad=0.3, nodesep=0.45, ranksep=0.55, splines=polyline];
  node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=10, margin="0.16,0.10"];
  edge [fontname="sans-serif", fontsize=9, color="#526b7a"];

  boundary [shape=diamond, label="Can both endpoints rely on\none sampling clock?\n两端是否共享可靠采样时钟？", fillcolor="#f5efff", color="#7356a8"];
  sync [label="Synchronous interface\nAPB / ready-valid / wait states\n慢速不等于异步", fillcolor="#e8f1fb", color="#2b6cb0"];
  payload [shape=diamond, label="What must cross?\n需要跨越什么？", fillcolor="#f5efff", color="#7356a8"];
  level [label="Persistent single bit\n多级 synchronizer", fillcolor="#ecfdf5", color="#2f855a"];
  token [label="Exactly-once sparse token\nFour-phase REQ/ACK\n允许接收端任意等待", fillcolor="#fff7d6", color="#b7791f"];
  stream [label="Continuous / burst data\nAsynchronous FIFO\n有限容量 + backpressure", fillcolor="#ffedd5", color="#c05621"];

  boundary -> sync [label="yes / 是"];
  boundary -> payload [label="no, independent/gated clocks / 否"];
  payload -> level [label="stable level"];
  payload -> token [label="confirmed command/event"];
  payload -> stream [label="buffered stream"];

  apb [shape=note, label="APB at one PCLK remains synchronous.\nPREADY handles wait; it does not solve CDC.", fillcolor="#f8fafc", color="#64748b"];
  sync -> apb [style=dashed, arrowhead=none];
}
'''


def _high_delta_fifo_records() -> tuple[dict[str, object], ...]:
    write_hz = 250_000_000
    read_hz = 100_000_000
    depth = 8
    end = Fraction(80, 1_000_000_000)
    events: list[tuple[Fraction, str]] = []
    time = Fraction(0)
    write_attempts = 0
    while time <= end and write_attempts < 8:
        events.append((time, "write_edge"))
        time += Fraction(1, write_hz)
        write_attempts += 1
    time = Fraction(1, 1_000_000_000)
    while time <= end:
        events.append((time, "read_edge"))
        time += Fraction(1, read_hz)
    events.sort(key=lambda item: (item[0], item[1] != "read_edge"))

    occupancy = 0
    records = []
    for time, kind in events:
        admitted = False
        stalled = False
        consumed = False
        if kind == "write_edge":
            if occupancy < depth:
                occupancy += 1
                admitted = True
            else:
                stalled = True
        elif occupancy:
            occupancy -= 1
            consumed = True
        records.append(
            {
                "time_ns": float(time * 1_000_000_000),
                "kind": kind,
                "write_admitted": admitted,
                "write_stalled": stalled,
                "read_consumed": consumed,
                "occupancy": occupancy,
            }
        )
    return tuple(records)


def _high_delta_wavejson(records: tuple[dict[str, object], ...]) -> dict[str, object]:
    return {
        "signal": [
            _categorical_lane(
                "ANALYTIC EDGE ORDER · not one clock",
                [f"{item['time_ns']:g}ns" for item in records],
            ),
            {
                "name": "250MHz write · edge",
                "wave": _bool_wave(
                    [item["kind"] == "write_edge" for item in records]
                ),
            },
            {
                "name": "250MHz write · admitted",
                "wave": _bool_wave(
                    [bool(item["write_admitted"]) for item in records]
                ),
            },
            {
                "name": "250MHz write · backpressure",
                "wave": _bool_wave(
                    [bool(item["write_stalled"]) for item in records]
                ),
            },
            {
                "name": "100MHz read · edge",
                "wave": _bool_wave(
                    [item["kind"] == "read_edge" for item in records]
                ),
            },
            {
                "name": "100MHz read · consumed",
                "wave": _bool_wave(
                    [bool(item["read_consumed"]) for item in records]
                ),
            },
            _categorical_lane(
                "idealized FIFO occupancy / 8",
                [item["occupancy"] for item in records],
            ),
        ],
        "head": {
            "text": "High Δf finite burst: 250 MHz → depth-8 async FIFO → 100 MHz"
        },
        "foot": {
            "text": (
                "8-beat burst drains; sustained load fills in ≈53.33 ns and needs "
                "backpressure · idealized occupancy"
            )
        },
        "config": {"hscale": 1},
    }


def _near_equal_dot() -> str:
    return r'''digraph near_equal {
  rankdir=LR;
  label="Near-equal independent clocks / 近同频异步：1 GHz + 1 Hz";
  labelloc="t";
  graph [bgcolor="white", pad=0.32, nodesep=0.5, ranksep=0.55, splines=polyline];
  node [shape=box, style="rounded,filled", fontname="sans-serif", fontsize=10, margin="0.16,0.12"];
  edge [fontname="sans-serif", fontsize=9, color="#526b7a"];

  clocks [label="write = 1,000,000,001 Hz\nread  = 1,000,000,000 Hz\nΔf = +1 Hz", fillcolor="#e8f1fb", color="#2b6cb0"];
  beat [label="relative-phase beat\nTbeat = 1 / |Δf| = 1 s\n≈ 10⁹ cycles per sweep", fillcolor="#f5efff", color="#7356a8"];
  slip [label="period slip per paired cycle\n≈ 1 attosecond\nphase moves very slowly", fillcolor="#fff7d6", color="#b7791f"];
  fifo [label="continuous one-word-per-edge traffic\nnet drift = +1 word/s\ndepth 8 fills in ≈ 8 s", fillcolor="#ffedd5", color="#c05621"];
  policy [label="Async FIFO preserves CDC safety\nand short-term elasticity.\nLong-term balance still needs\nbackpressure / rate matching / idle insertion.", fillcolor="#ecfdf5", color="#2f855a"];

  clocks -> beat -> slip -> fifo -> policy;
  sim [shape=note, label="A cycle-expanded one-beat trace would need about one billion columns.\nThe showcase records the exact rate/beat relations analytically instead.", fillcolor="#f8fafc", color="#64748b"];
  beat -> sim [style=dashed, arrowhead=none];

  t0 [label="t=0 s\nnet +0 word", fillcolor="#f8fafc", color="#64748b"];
  t1 [label="t=1 s\nnet +1 word", fillcolor="#f8fafc", color="#64748b"];
  t8 [label="t≈8 s\ndepth-8 reaches full", fillcolor="#fee2e2", color="#b91c1c"];
  t0 -> t1 -> t8 [label="compressed occupancy scale", style=dashed];
  jitter [shape=note, label="Real clock jitter and ppm error can exceed this ideal 1 Hz offset.\nThe example isolates the cumulative-rate principle.", fillcolor="#f8fafc", color="#64748b"];
  clocks -> jitter [style=dashed, arrowhead=none];
}
'''


def _frequency_record(
    high_records: tuple[dict[str, object], ...]
) -> dict[str, object]:
    high_write = 250_000_000
    high_read = 100_000_000
    high_depth = 8
    near_write = 1_000_000_001
    near_read = 1_000_000_000
    delta = near_write - near_read
    slip_seconds = abs(
        Fraction(1, near_read) - Fraction(1, near_write)
    )
    return {
        "schema": "protocol-model.showcase.cdc-frequency/v1",
        "high_delta": {
            "write_frequency_hz": high_write,
            "read_frequency_hz": high_read,
            "delta_frequency_hz": high_write - high_read,
            "fifo_depth": high_depth,
            "traffic": "finite eight-word burst",
            "ideal_fill_time_without_backpressure_ns": float(
                Fraction(high_depth, high_write - high_read) * 1_000_000_000
            ),
            "projection_window_ns": 80,
            "write_admitted": sum(
                bool(item["write_admitted"]) for item in high_records
            ),
            "write_stalled": sum(
                bool(item["write_stalled"]) for item in high_records
            ),
            "read_consumed": sum(
                bool(item["read_consumed"]) for item in high_records
            ),
            "final_occupancy": high_records[-1]["occupancy"],
            "peak_occupancy": max(
                int(item["occupancy"]) for item in high_records
            ),
            "sustained_stream": {
                "rate_gap_words_per_second": high_write - high_read,
                "steady_state_backpressure_attempts_per_second": (
                    high_write - high_read
                ),
                "interpretation": (
                    "finite FIFO absorbs a burst; sustained offered load above "
                    "read bandwidth requires backpressure"
                ),
            },
            "trace": high_records,
        },
        "near_equal": {
            "write_frequency_hz": near_write,
            "read_frequency_hz": near_read,
            "delta_frequency_hz": delta,
            "beat_period_seconds": float(Fraction(1, abs(delta))),
            "write_cycles_per_beat": near_write,
            "period_slip_seconds_per_paired_cycle": float(slip_seconds),
            "period_slip_attoseconds_per_paired_cycle": float(
                slip_seconds * 1_000_000_000_000_000_000
            ),
            "net_word_drift_per_second": delta,
            "depth_8_ideal_fill_time_seconds": 8 / delta,
            "interpretation": (
                "async FIFO handles CDC and finite elasticity; sustained rate "
                "mismatch still requires admission or rate matching"
            ),
        },
    }


def _case_record(run: ExampleRun) -> dict[str, object]:
    return {
        "schema": "protocol-model.showcase.four-phase-case/v1",
        "name": run.case.name,
        "title": run.case.title,
        "purpose": run.case.purpose,
        "data_window": FourPhaseDataWindow.EARLY.value,
        "expected": run.case.expected.value,
        "observed": run.actual.value,
        "expectation": "MET" if run.expectation_met else "MISMATCH",
        "fault": (
            None
            if run.fault is None
            else {
                "rule": run.fault.rule,
                "reason": run.fault.reason,
                "scope": run.fault.scope.value,
                "location": run.fault.location,
            }
        ),
        "emissions": [
            {
                "kind": event.kind,
                "key": event.key,
                "payload": dict(event.payload),
                "timestamp": event.timestamp,
                "sequence": event.sequence,
            }
            for event in run.semantic_run.emissions
        ],
        "final_state": {
            "phase": run.semantic_run.final_state.phase.value,
            "quiescent": (
                run.semantic_run.final_state.phase.value == "idle_00"
            ),
        },
        "samples": [
            {
                "sequence": sample.sequence,
                "timestamp_ns": sample.timestamp,
                "req": sample.get("mailbox").req,
                "ack": sample.get("mailbox").ack,
                "event": (
                    None
                    if sample.get("mailbox").event is None
                    else {
                        "kind": sample.get("mailbox").event.kind,
                        "key": sample.get("mailbox").event.key,
                        "payload": dict(sample.get("mailbox").event.payload),
                    }
                ),
            }
            for sample in run.case.samples
        ],
    }


def _readme(runs: tuple[ExampleRun, ...], frequency: dict[str, object]) -> str:
    rows = []
    for run in runs:
        rule = "—" if run.fault is None else f"`{run.fault.rule}`"
        rows.append(
            f"| `{run.case.name}` | {run.case.title} | "
            f"`{run.case.expected.value}` → `{run.actual.value}` | {rule} | "
            f"[wave](cases/{run.case.name}/waveform.svg) · "
            f"[cause](cases/{run.case.name}/causality.svg) · "
            f"[JSON](cases/{run.case.name}/result.json) |"
        )
    high = frequency["high_delta"]
    near = frequency["near_equal"]
    return f"""# Four-phase handshake 与异步频差 Showcase

本例回答两个问题：四相 REQ/ACK 在什么边界出现，以及异步 FIFO 面对不同频差时究竟解决什么。

![选择异步运输的方法](where-used.svg)

## 什么时候需要

判断依据是两端能否依赖共同采样时刻，而不是接口绝对速度。一个很慢的 APB endpoint 只要与 manager
共用 PCLK，仍通过 PREADY 插入同步 wait state；它不需要为“慢”改成异步握手。典型异步边界包括：

- 独立 PLL、可停钟或可掉电 domain 之间的 command/completion；
- 总线 wrapper 与内部异步外设、DMA source、mailbox 或混合信号控制；
- 必须逐笔确认且允许接收方任意等待的稀疏 token；
- 连续数据或 burst，此时通常采用有限 async FIFO，而不是逐 word 四相往返。

## 四相 observation 的可执行证据

横轴是 edge-complete observation order；timestamp 只是本例提供的 ns 注记。三个场景都由当前
`FourPhaseObserver` 执行，每项都有波形、诊断关系图和机器结果。

| case | 目标 | expected → observed | rule | evidence |
|---|---|---|---|---|
{chr(10).join(rows)}

### 合法路径精讲

![合法四相波形](cases/legal-delayed-ack/waveform.svg)

![合法四相证据关系](cases/legal-delayed-ack/causality.svg)

REQ 在 `S1` 上升，接收端可以停留在 `10`；`S4` 的 ACK 上升产生唯一 `TRANSFER`。REQ、ACK
随后依次归零，wire slot 才重新可用。

## 高差频：FIFO 吸收弹性，满后实施背压

![高差频 FIFO](high-delta-fifo.svg)

本投影使用 250 MHz producer、100 MHz consumer、depth-8 FIFO。一次 8-beat burst 的峰值占用为
`{high['peak_occupancy']}/8`，没有触发 backpressure，并在读侧继续运行后排空——这是高差频 FIFO 很擅长的
有限 burst elasticity。若 producer 持续满速，150 Mword/s 的长期带宽缺口会在理想流体近似下约
`{high['ideal_fill_time_without_backpressure_ns']:.2f} ns` 填满 FIFO，之后仍必须背压。图中没有展开 Gray
pointer 同步延迟，因此它说明容量/admission，不作为具体 async FIFO RTL 证明。

## 低差频：1 GHz 与 1 GHz + 1 Hz 的慢速 beat

![近同频异步分析](near-equal-beat.svg)

两时钟独立时，频率看起来几乎相同也不能按同步处理。这里 `Δf=1 Hz`：

- 完整相对相位 sweep 需要 `{near['beat_period_seconds']:g} s`，约十亿个 cycle；
- 对应周期差约 `{near['period_slip_attoseconds_per_paired_cycle']:.9f} as`；
- 连续 one-word-per-edge 流量仍净积累 `{near['net_word_drift_per_second']} word/s`；
- depth-8 FIFO 在没有背压/速率匹配时约 `{near['depth_8_ideal_fill_time_seconds']:g} s` 填满。

因此 async FIFO 很适合隔离相位不确定性、同步指针并提供有限 elasticity；它不会凭空修正长期平均
速率。近同频场景还说明为什么项目以后需要 symbolic phase/time-window 分析，而不应为一次 beat 展开
十亿列波形。

现实 1 GHz clock 的 jitter 或 ppm 误差可能远大于这个理想化 `1 Hz` offset；这个刻意极端的例子用于分离
“CDC 相位安全”与“长期累计速率差”两个问题。

## 证据边界

- `waveform.svg` 是模型生成的 normalized signal/analytic edge projection，不是 RTL/VCD；
- 四相 observer 检查相位与 EARLY data window，不证明 synchronizer、MTBF 或 STA；
- 高频 FIFO 图是容量与 admission 演示，尚未声称仓库已经实现 Gray-pointer async FIFO VirtualDut；
- 近同频结论来自文件中保存的精确频率关系，完整数字见 [result.json](result.json)；
- 生成参数、命令与 renderer 见 [provenance.json](provenance.json)，文件清单见 [manifest.json](manifest.json)。
"""


def _require_renderers() -> None:
    missing = []
    if shutil.which("dot") is None:
        missing.append("Graphviz 'dot'")
    wavedrom = REPOSITORY_ROOT / "node_modules" / ".bin" / "wavedrom"
    if not wavedrom.is_file():
        missing.append("WaveDrom (run 'npm ci' at repository root)")
    if missing:
        raise SystemExit("Missing renderer dependency: " + "; ".join(missing))


def _build_publication(directory: Path) -> tuple[Path, tuple[ExampleRun, ...]]:
    protocol = build_four_phase_token_interface(
        FourPhaseTokenConfig(data_width=DATA_WIDTH)
    )
    transfer = protocol.event_kinds["transfer"].schema
    runs = tuple(_execute(case, transfer) for case in _build_cases())
    if not all(run.expectation_met for run in runs):
        mismatches = [run.case.name for run in runs if not run.expectation_met]
        raise RuntimeError(f"four-phase expectation mismatch: {mismatches!r}")
    legal = next(run for run in runs if run.case.name == "legal-delayed-ack")
    link_run = protocol.open_session().run(legal.semantic_run.emissions)
    if link_run.verdict is not Verdict.PASS:
        raise RuntimeError("accepted four-phase transfer failed InterfaceSession")

    high_records = _high_delta_fifo_records()
    frequency = _frequency_record(high_records)
    store = RunArtifactStore("link-four-phase-handshake", directory)
    publisher = VisualizationPublisher(store)

    publisher.render_dot("where-used", _decision_dot(), kind="decision_view")
    publisher.render_wave(
        "high-delta-fifo",
        _high_delta_wavejson(high_records),
        kind="frequency_fifo_view",
    )
    publisher.render_dot(
        "near-equal-beat",
        _near_equal_dot(),
        kind="frequency_beat_view",
    )
    for run in runs:
        store.write_json(
            "result.json",
            _case_record(run),
            kind="case_result",
            case=run.case.name,
        )
        publisher.render_wave(
            "waveform",
            _case_wavejson(run),
            kind="waveform",
            case=run.case.name,
        )
        publisher.render_dot(
            "causality",
            _case_causality_dot(run),
            kind="causality",
            case=run.case.name,
        )

    result = {
        "schema": "protocol-model.showcase.four-phase/v1",
        "protocol": protocol.name,
        "wire_encoding": protocol.parameters["wire_encoding"],
        "case_count": len(runs),
        "all_expectations_met": True,
        "cases": [
            {
                "name": run.case.name,
                "expected": run.case.expected.value,
                "observed": run.actual.value,
                "fault_rule": (
                    None if run.fault is None else run.fault.rule
                ),
            }
            for run in runs
        ],
        "frequency_analysis": frequency,
    }
    store.write_json("result.json", result, kind="showcase_result")
    store.write_text(
        "README.md",
        _readme(runs, frequency),
        kind="demo_guide",
        media_type="text/markdown",
    )
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": DEMO_NAME,
            "source": "showcase/demos/link/four_phase_handshake/run.py",
            "command": (
                "python3 showcase/demos/link/four_phase_handshake/run.py"
            ),
            "protocol_model_version": __version__,
            "execution_models": ["FourPhaseObserver", "InterfaceSession"],
            "data_window": FourPhaseDataWindow.EARLY.value,
            "reset_policy": "not exercised by these three showcase cases",
            "frequency_models": {
                "high_delta": (
                    "ideal finite eight-beat FIFO capacity/admission edge simulation; "
                    "independent 1 ns read-domain phase offset"
                ),
                "near_equal": (
                    "exact integer frequency and rational period relations; "
                    "no billion-cycle expansion"
                ),
            },
            "renderers": {
                "waveform": "WaveDrom 3.6.2 (package.json)",
                "diagram": "Graphviz dot",
            },
            "presentation_boundary": (
                "edge-complete logical snapshots and analytic FIFO capacity; "
                "not synchronizer structure, Gray-pointer RTL, metastability/MTBF, "
                "STA, physical clocks or RTL/VCD"
            ),
        },
        kind="provenance",
    )
    manifest = store.finalize(
        verdict="PASS",
        protocols=(protocol_record_from_interface(protocol),),
        cases=tuple(
            {
                "name": run.case.name,
                "expected": run.case.expected.value,
                "observed": run.actual.value,
                "observed_rule": (
                    None if run.fault is None else run.fault.rule
                ),
                "expectation": "MET",
            }
            for run in runs
        ),
        state={
            "accepted_transfer_count": len(legal.semantic_run.emissions),
            "high_delta_final_occupancy": frequency["high_delta"]["final_occupancy"],
            "near_equal_beat_period_seconds": frequency["near_equal"]["beat_period_seconds"],
        },
        metadata={
            "publication": "showcase/generated/link/four-phase-handshake",
            "case_count": len(runs),
            "run_status": "success",
            "waveform_interpretation": "asynchronous observation/edge order",
            "shared_clock": False,
            "rtl_capture": False,
            "async_fifo_rtl_implemented": False,
        },
        tool_version=__version__,
    )
    return manifest, runs


def _publish(staged: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = target.with_name(f".{target.name}.previous")
    if previous.exists():
        shutil.rmtree(previous)
    if target.exists():
        target.replace(previous)
    try:
        staged.replace(target)
    except BaseException:
        if previous.exists() and not target.exists():
            previous.replace(target)
        raise
    else:
        if previous.exists():
            shutil.rmtree(previous)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish the four-phase handshake and CDC-frequency showcase."
    )
    parser.add_argument(
        "--publish-root",
        type=Path,
        default=SHOWCASE_ROOT / "generated" / "link",
        help="parent directory of the stable demo publication",
    )
    args = parser.parse_args(argv)
    publish_root = args.publish_root.expanduser().resolve()
    target = publish_root / DEMO_NAME
    build_root = publish_root.parent / ".build"
    build_root.mkdir(parents=True, exist_ok=True)

    _require_renderers()
    with TemporaryDirectory(prefix=f"{DEMO_NAME}-", dir=build_root) as temporary:
        staged = Path(temporary) / DEMO_NAME
        manifest, runs = _build_publication(staged)
        if not manifest.is_file():
            raise RuntimeError("staged four-phase showcase has no manifest")
        for required in (
            "README.md",
            "result.json",
            "where-used.svg",
            "high-delta-fifo.svg",
            "near-equal-beat.svg",
            "provenance.json",
            "sources/where-used.dot",
            "sources/high-delta-fifo.json",
            "sources/near-equal-beat.dot",
        ):
            if not (staged / required).is_file():
                raise RuntimeError(f"staged showcase lacks {required}")
        for run in runs:
            case_root = staged / "cases" / run.case.name
            source_root = staged / "sources" / "cases" / run.case.name
            for required in ("result.json", "waveform.svg", "causality.svg"):
                if not (case_root / required).is_file():
                    raise RuntimeError(
                        f"case {run.case.name!r} lacks {required}"
                    )
            for required in ("waveform.json", "causality.dot"):
                if not (source_root / required).is_file():
                    raise RuntimeError(
                        f"case {run.case.name!r} lacks source {required}"
                    )
        _publish(staged, target)

    try:
        build_root.rmdir()
    except OSError:
        pass
    print(f"Published four-phase handshake showcase: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
