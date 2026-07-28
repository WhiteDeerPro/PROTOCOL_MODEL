#!/usr/bin/env python3
"""Publish a Sensor FIFO -> DMA -> AXI4-Lite memory-copy witness."""

from __future__ import annotations

import argparse
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
    protocol_record_from_system,
)
from protocol_model.integrations.recipes.amba.endpoints.memory_copy import (  # noqa: E402
    build_amba_serialized_memory_copy_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.queued import (  # noqa: E402
    build_amba_queued_address_responder_vdut,
)
from protocol_model.integrations.recipes.amba.endpoints.sensor_fifo import (  # noqa: E402
    build_amba_sensor_fifo_vdut,
)
from protocol_model.integrations.recipes.amba.fabrics.axi4_lite_crossbar import (  # noqa: E402
    build_axi4_lite_address_crossbar_vdut,
)
from protocol_model.protocols.amba.axi.axi4_lite import (  # noqa: E402
    build_axi4_lite_interface,
)
from protocol_model.system import (  # noqa: E402
    AddressClaim,
    AddressRouterContract,
    AddressWindow,
    DutAdvanceAction,
    SystemProtocolBuilder,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.address import (  # noqa: E402
    AddressRead,
    AddressSpace,
    MemoryRegion,
)
from protocol_model.virtual_dut.backend.memory_copy import (  # noqa: E402
    MemoryCopyDescriptor,
    SerializedMemoryCopyState,
)
from protocol_model.virtual_dut.backend.queued_address import (  # noqa: E402
    QueuedAddressResponderState,
    constant_address_delay,
)
from protocol_model.virtual_dut.backend.sensor_fifo import (  # noqa: E402
    SensorFifoConfig,
    SensorFifoState,
    SensorFullPolicy,
    incrementing_sample_policy,
)
from protocol_model.virtual_dut.fabric import (  # noqa: E402
    AddressRoute,
    ScheduledAddressCrossbarState,
)
from protocol_model.visualization import (  # noqa: E402
    VisualizationPublisher,
    system_trace_dot,
    virtual_dut_structure_dot,
)


DEMO_NAME = "sensor-dma-capture"
SYSTEM_NAME = "sensor_dma_capture"
SAMPLE_BASE = 0x10203040
SOURCE_BASE = 0x1000
DESTINATION_BASE = 0x2000
BEAT_BYTES = 4
COPY_BEATS = 2
SENSOR_CAPACITY = 2
SENSOR_OPPORTUNITIES = 4


def _build_system():
    protocol = build_axi4_lite_interface()
    descriptor = MemoryCopyDescriptor(
        SOURCE_BASE,
        DESTINATION_BASE,
        COPY_BEATS * BEAT_BYTES,
        BEAT_BYTES,
        source_stride=0,
    )
    dma = build_amba_serialized_memory_copy_vdut(
        "dma", protocol, descriptor, port_name="axi"
    )
    sensor = build_amba_sensor_fifo_vdut(
        "sensor",
        protocol,
        SensorFifoConfig(
            0,
            BEAT_BYTES,
            SENSOR_CAPACITY,
            full_policy=SensorFullPolicy.DROP_NEWEST,
        ),
        incrementing_sample_policy(start=SAMPLE_BASE),
        port_name="axi",
    )
    memory_space = AddressSpace((MemoryRegion("ram", 0x100),))
    memory = build_amba_queued_address_responder_vdut(
        "memory",
        protocol,
        memory_space,
        capacity=2,
        delay_policy=constant_address_delay(0),
        port_name="axi",
    )
    routes = (
        AddressRoute(
            "sensor_data",
            SOURCE_BASE,
            BEAT_BYTES,
            "m_sensor",
            output_base_address=0,
        ),
        AddressRoute(
            "memory",
            DESTINATION_BASE,
            0x100,
            "m_memory",
            output_base_address=0,
        ),
    )
    router = AddressRouterContract(
        "dma_router",
        "crossbar",
        ("s_dma",),
        ("m_sensor", "m_memory"),
        routes,
    )
    builder = SystemProtocolBuilder(SYSTEM_NAME)
    for dut in (dma, sensor, memory):
        builder.add_dut(dut)
    builder.construct_address_router(
        router,
        lambda contract: build_axi4_lite_address_crossbar_vdut(
            contract.router,
            protocol,
            contract.ingress_ports,
            contract.egress_ports,
            contract.routes,
            ingress_queue_capacity=2,
        ),
    )
    builder.connect(
        "dma_bus",
        protocol,
        {
            "manager": VirtualDutPortRef("dma", "axi"),
            "subordinate": VirtualDutPortRef("crossbar", "s_dma"),
        },
    )
    builder.connect(
        "sensor_bus",
        protocol,
        {
            "manager": VirtualDutPortRef("crossbar", "m_sensor"),
            "subordinate": VirtualDutPortRef("sensor", "axi"),
        },
    )
    builder.connect(
        "memory_bus",
        protocol,
        {
            "manager": VirtualDutPortRef("crossbar", "m_memory"),
            "subordinate": VirtualDutPortRef("memory", "axi"),
        },
    )
    builder.add_address_claim(
        AddressClaim(
            "sensor_data_local",
            VirtualDutPortRef("sensor", "axi"),
            AddressWindow(0, BEAT_BYTES),
        )
    )
    builder.add_address_claim(
        AddressClaim(
            "memory_local",
            VirtualDutPortRef("memory", "axi"),
            AddressWindow(0, 0x100),
        )
    )
    return builder.build(), protocol, memory_space


def _event_record(event) -> dict[str, object]:
    return {
        "index": event.index,
        "link": event.connection,
        "source": event.source.qualified_name,
        "destination": event.destination.qualified_name,
        "kind": event.event.kind,
        "payload": dict(event.event.payload),
    }


def _state_snapshot(state) -> dict[str, object]:
    dma = state.dut_states["dma"]
    sensor = state.dut_states["sensor"]
    crossbar = state.dut_states["crossbar"]
    memory = state.dut_states["memory"]
    assert isinstance(dma, SerializedMemoryCopyState)
    assert isinstance(sensor, SensorFifoState)
    assert isinstance(crossbar, ScheduledAddressCrossbarState)
    assert isinstance(memory, QueuedAddressResponderState)
    return {
        "dma": {
            "phase": dma.phase.value,
            "beat_index": dma.beat_index,
            "bytes_copied": dma.bytes_copied,
            "buffered_data": dma.buffered_data,
        },
        "sensor": {
            "fifo": [f"0x{sample:08x}" for sample in sensor.samples],
            "queue_depth": sensor.queue_depth,
            "capacity": SENSOR_CAPACITY,
            "accepted_samples": sensor.accepted_samples,
            "overrun_count": sensor.overrun_count,
        },
        "crossbar": {
            "ingress_queue_usage": {
                name: len(queue)
                for name, queue in crossbar.ingress_queues.items()
            },
            "active_owners": len(crossbar.pending),
        },
        "memory": {
            "queue_depth": len(memory.queue),
        },
    }


def _record(label: str, transition) -> dict[str, object]:
    blocked = transition.blocked
    return {
        "label": label,
        "blocked": (
            None
            if blocked is None
            else {
                "resource": blocked.resource,
                "location": blocked.location,
                "reason": blocked.reason,
            }
        ),
        "fault": (
            None
            if transition.fault is None
            else {
                "rule": transition.fault.rule,
                "reason": transition.fault.reason,
            }
        ),
        "emissions": [_event_record(item) for item in transition.emissions],
        "post_state": _state_snapshot(transition.state),
    }


def _execute(system):
    session = system.open_session()
    state = session.initial_state()
    records: list[dict[str, object]] = []
    actions = [
        (
            "produce 4 samples (retain 2, drop 2)",
            DutAdvanceAction("sensor", steps=SENSOR_OPPORTUNITIES),
        )
    ]
    for beat in range(COPY_BEATS):
        actions.extend(
            (
                (
                    f"beat {beat}: DMA issues sensor read",
                    DutAdvanceAction("dma"),
                ),
                (
                    f"beat {beat}: crossbar routes sensor read/response",
                    DutAdvanceAction("crossbar"),
                ),
                (
                    f"beat {beat}: DMA issues memory write",
                    DutAdvanceAction("dma"),
                ),
                (
                    f"beat {beat}: crossbar routes memory write",
                    DutAdvanceAction("crossbar"),
                ),
                (
                    f"beat {beat}: memory services write/completion",
                    DutAdvanceAction("memory"),
                ),
            )
        )

    for label, action in actions:
        transition = session.step(state, action)
        records.append(_record(label, transition))
        if transition.fault is not None:
            raise RuntimeError(
                f"sensor-DMA witness failed at {label}: "
                f"{transition.fault.rule}: {transition.fault.reason}"
            )
        if transition.blocked is not None:
            raise RuntimeError(
                f"sensor-DMA witness unexpectedly blocked at {label}: "
                f"{transition.blocked.resource}"
            )
        state = transition.state

    dma = state.dut_states["dma"]
    sensor = state.dut_states["sensor"]
    assert isinstance(dma, SerializedMemoryCopyState)
    assert isinstance(sensor, SensorFifoState)
    if not dma.done or dma.bytes_copied != COPY_BEATS * BEAT_BYTES:
        raise RuntimeError("DMA did not complete the configured copy")
    if sensor.samples or sensor.overrun_count != 2:
        raise RuntimeError("sensor FIFO/overrun result does not match witness")
    if not session.is_quiescent(state):
        raise RuntimeError("sensor-DMA witness did not reach quiescence")
    return session, state, records


def _memory_bytes(state, memory_space: AddressSpace) -> bytes:
    memory = state.dut_states["memory"]
    assert isinstance(memory, QueuedAddressResponderState)
    read = memory_space.access(
        memory.handler_state,
        AddressRead(0, COPY_BEATS * BEAT_BYTES),
    )
    if not read.result.succeeded or read.result.data is None:
        raise RuntimeError("cannot inspect final memory image")
    return read.result.data.to_bytes(COPY_BEATS * BEAT_BYTES, "little")


def _categorical_lane(name: str, values: list[object]) -> dict[str, object]:
    return {
        "name": name,
        "wave": "=" * len(values),
        "data": [str(value) for value in values],
    }


def _event_text(item: dict[str, object]) -> str:
    payload = item["payload"]
    kind = str(item["kind"])
    detail = ""
    if kind in {"AR", "AW"}:
        detail = f"@0x{int(payload['addr']):04x}"
    elif kind == "R":
        detail = f"D={int(payload['data']):08x}"
    elif kind == "W":
        detail = f"D={int(payload['data']):08x}"
    elif kind == "B":
        detail = str(payload["resp"])
    return f"e{item['index']} {kind} {detail}".rstrip()


def _emission_lane(records, name: str, predicate) -> dict[str, object]:
    values = []
    for record in records:
        matching = [item for item in record["emissions"] if predicate(item)]
        values.append(
            " + ".join(_event_text(item) for item in matching) or "—"
        )
    return _categorical_lane(name, values)


def _wavejson(records: list[dict[str, object]]) -> dict[str, object]:
    states = [record["post_state"] for record in records]
    service_actions = ["produce×4 · keep2/drop2"]
    for beat in range(COPY_BEATS):
        service_actions.extend(
            (
                f"b{beat} · DMA read",
                f"b{beat} · sensor path",
                f"b{beat} · DMA write",
                f"b{beat} · memory path",
                f"b{beat} · memory complete",
            )
        )
    if len(service_actions) != len(records):
        raise RuntimeError("waveform action labels disagree with execution")
    return {
        "signal": [
            _categorical_lane(
                "MODEL STEP · not ACLK",
                [f"S{index}" for index in range(len(records))],
            ),
            [
                "scheduler",
                _categorical_lane(
                    "service action",
                    service_actions,
                ),
            ],
            [
                "accepted canonical events",
                _emission_lane(
                    records,
                    "DMA → crossbar",
                    lambda item: item["source"] == "dma.axi",
                ),
                _emission_lane(
                    records,
                    "crossbar ↔ sensor",
                    lambda item: item["link"] == "sensor_bus",
                ),
                _emission_lane(
                    records,
                    "crossbar ↔ memory",
                    lambda item: item["link"] == "memory_bus",
                ),
                _emission_lane(
                    records,
                    "crossbar → DMA",
                    lambda item: item["destination"] == "dma.axi",
                ),
            ],
            [
                "post-state",
                _categorical_lane(
                    "sensor FIFO",
                    [
                        f"{state['sensor']['queue_depth']}/"
                        f"{state['sensor']['capacity']}"
                        for state in states
                    ],
                ),
                _categorical_lane(
                    "sensor overruns",
                    [state["sensor"]["overrun_count"] for state in states],
                ),
                _categorical_lane(
                    "DMA phase",
                    [state["dma"]["phase"] for state in states],
                ),
                _categorical_lane(
                    "DMA bytes copied",
                    [state["dma"]["bytes_copied"] for state in states],
                ),
                _categorical_lane(
                    "memory request FIFO",
                    [state["memory"]["queue_depth"] for state in states],
                ),
            ],
        ],
        "head": {
            "text": (
                "Sensor FIFO → serialized DMA → memory · "
                "transaction-semantic execution"
            )
        },
        "foot": {
            "text": (
                "1 column = 1 accepted SystemSession action/service "
                "opportunity · POST-STATE · not AXI pins or cycle timing"
            )
        },
        "config": {"hscale": 6},
    }


def _structure_dot() -> str:
    """One publication-specific expansion of the executed system."""

    return r'''digraph sensor_dma_structure {
  rankdir=LR;
  label="Sensor capture system · constructed VirtualDuts and AXI4-Lite links";
  labelloc="t";
  graph [bgcolor="white", pad=0.3, nodesep=0.45, ranksep=0.72,
         splines=polyline, ordering=out];
  node [fontname="sans-serif", fontsize=10];
  edge [fontname="sans-serif", fontsize=9, color="#52606d", penwidth=1.3];

  scheduler [shape=note, style="rounded,dashed,filled", fillcolor="#fff7ed",
    color="#ea580c", label="scenario scheduler\nexplicit service opportunities\n(no implicit clock)"];

  dma [shape=plain, label=<
    <TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6" COLOR="#7c3aed">
      <TR><TD BGCOLOR="#ede9fe"><B>dma · VirtualDut</B></TD></TR>
      <TR><TD BGCOLOR="#f5f3ff">descriptor: src 0x1000 fixed<BR/>dst 0x2000 + 4 · 2 × 4-byte beats</TD></TR>
      <TR><TD BGCOLOR="#f5f3ff">serialized FSM: read → buffer → write<BR/>one outstanding</TD></TR>
      <TR><TD PORT="axi" BGCOLOR="#dbeafe">AXI4-Lite manager attachment</TD></TR>
    </TABLE>>];

  crossbar [shape=plain, label=<
    <TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6" COLOR="#ea580c">
      <TR><TD BGCOLOR="#ffedd5" COLSPAN="2"><B>crossbar · VirtualDut</B></TD></TR>
      <TR><TD PORT="s" BGCOLOR="#dbeafe" COLSPAN="2">s_dma interface port · subordinate</TD></TR>
      <TR><TD BGCOLOR="#e0f2fe" COLSPAN="2">AXI4-Lite completer attachment<BR/><FONT POINT-SIZE="9">AR/AW/W → AddressAccess · AccessResult → R/B</FONT></TD></TR>
      <TR><TD BGCOLOR="#fff7ed" COLSPAN="2">ingress request FIFO · capacity 2</TD></TR>
      <TR><TD BGCOLOR="#fff7ed" COLSPAN="2">decode/remap + egress arbitration + owner table</TD></TR>
      <TR><TD BGCOLOR="#e0f2fe">AXI4-Lite requester attachment<BR/><FONT POINT-SIZE="9">sensor access</FONT></TD><TD BGCOLOR="#e0f2fe">AXI4-Lite requester attachment<BR/><FONT POINT-SIZE="9">memory access</FONT></TD></TR>
      <TR><TD PORT="sensor" BGCOLOR="#dbeafe">m_sensor interface port<BR/><FONT POINT-SIZE="9">manager</FONT></TD><TD PORT="memory" BGCOLOR="#dbeafe">m_memory interface port<BR/><FONT POINT-SIZE="9">manager</FONT></TD></TR>
    </TABLE>>];

  sensor [shape=plain, label=<
    <TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6" COLOR="#0f766e">
      <TR><TD BGCOLOR="#ccfbf1"><B>sensor · VirtualDut</B></TD></TR>
      <TR><TD PORT="axi" BGCOLOR="#dbeafe">AXI4-Lite subordinate attachment</TD></TR>
      <TR><TD BGCOLOR="#f0fdfa">fixed data register @ local 0x0<BR/>read pops oldest sample</TD></TR>
      <TR><TD BGCOLOR="#f0fdfa">sample FIFO · capacity 2 · DROP_NEWEST<BR/>overrun counter</TD></TR>
      <TR><TD BGCOLOR="#ecfeff">deterministic policy<BR/>0x10203040 + service_index</TD></TR>
    </TABLE>>];

  memory [shape=plain, label=<
    <TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="6" COLOR="#16a34a">
      <TR><TD BGCOLOR="#dcfce7"><B>memory · VirtualDut</B></TD></TR>
      <TR><TD PORT="axi" BGCOLOR="#dbeafe">AXI4-Lite subordinate attachment</TD></TR>
      <TR><TD BGCOLOR="#f0fdf4">complete-request FIFO · capacity 2</TD></TR>
      <TR><TD BGCOLOR="#f0fdf4">MemoryRegion · local 0x0..0xff</TD></TR>
    </TABLE>>];

  { rank=same; scheduler; dma; }
  { rank=same; sensor; memory; }
  sensor -> memory [style=invis, weight=80];

  scheduler -> dma [style=dashed, color="#ea580c", constraint=false,
    label="advance DMA"];
  scheduler -> crossbar [style=dashed, color="#ea580c", constraint=false,
    label="advance interconnect"];
  scheduler -> sensor [style=dashed, color="#ea580c", constraint=false,
    label="produce samples"];
  scheduler -> memory [style=dashed, color="#ea580c", constraint=false,
    label="service queued write"];

  dma:axi -> crossbar:s [dir=both, arrowtail=normal,
    label=<<B>AXI4-Lite</B><BR/><FONT POINT-SIZE="8" COLOR="#64748b">dma_bus</FONT><BR/><FONT POINT-SIZE="8">request → · completion ←</FONT>>];
  crossbar:sensor -> sensor:axi [dir=both, arrowtail=normal,
    label=<<B>AXI4-Lite</B><BR/><FONT POINT-SIZE="8" COLOR="#64748b">sensor_bus</FONT><BR/><FONT POINT-SIZE="8">read → · data ←</FONT>>];
  crossbar:memory -> memory:axi [dir=both, arrowtail=normal,
    label=<<B>AXI4-Lite</B><BR/><FONT POINT-SIZE="8" COLOR="#64748b">memory_bus</FONT><BR/><FONT POINT-SIZE="8">write → · completion ←</FONT>>];
}
'''


def _msc_label(event) -> str:
    payload = event.event.payload
    detail = ""
    if event.event.kind in {"AR", "AW"}:
        detail = f" 0x{int(payload['addr']):x}"
    elif event.event.kind in {"R", "W"}:
        detail = f" 0x{int(payload['data']):08x}"
    elif event.event.kind == "B":
        detail = f" {payload['resp']}"
    return f"e{event.index} {event.event.kind}{detail}"


def _msc_dot(trace) -> str:
    """Arrange the first copied beat as a compact message-sequence chart."""

    participants = ("dma", "crossbar", "sensor", "memory")
    lines = [
        "digraph sensor_dma_msc {",
        "  rankdir=TB;",
        '  label="Sensor DMA · first beat message sequence (actual accepted events)";',
        '  labelloc="t";',
        '  graph [bgcolor="white", pad=0.28, nodesep=0.8, ranksep=0.36, newrank=true];',
        '  node [fontname="sans-serif", fontsize=10];',
        '  edge [fontname="sans-serif", fontsize=9];',
    ]
    for participant in participants:
        lines.append(
            f'  h_{participant} [shape=box, style="rounded,filled", '
            f'fillcolor="#f8fafc", group={json.dumps(participant)}, '
            f'label={json.dumps(participant)}];'
        )
    lines.append(
        "  { rank=same; h_dma; h_crossbar; h_sensor; h_memory; }"
    )
    first_beat = trace.events[:10]
    previous = {participant: f"h_{participant}" for participant in participants}
    for row, event in enumerate(first_beat):
        row_nodes = []
        for participant in participants:
            node = f"p{row}_{participant}"
            row_nodes.append(node)
            lines.append(
                f'  {node} [shape=point, width=0.035, label="", '
                f'color="#94a3b8", group={json.dumps(participant)}];'
            )
            lines.append(
                f"  {previous[participant]} -> {node} "
                '[arrowhead=none, color="#cbd5e1", penwidth=1.0, weight=1000];'
            )
            previous[participant] = node
        lines.append("  { rank=same; " + "; ".join(row_nodes) + "; }")
        lines.append(
            "  " + " -> ".join(row_nodes)
            + " [style=invis, weight=100];"
        )
        source = f"p{row}_{event.source.dut}"
        destination = f"p{row}_{event.destination.dut}"
        color = "#2563eb" if event.event.kind in {"AR", "AW", "W"} else "#059669"
        lines.append(
            f"  {source} -> {destination} [constraint=false, penwidth=1.6, "
            f"color={json.dumps(color)}, fontcolor={json.dumps(color)}, "
            f"label={json.dumps(_msc_label(event))}];"
        )
    lines.extend(
        (
            '  repeat [shape=note, style="rounded,dashed,filled", '
            'fillcolor="#fff7ed", color="#ea580c", '
            'label="beat 1 repeats the same read→write lifecycle\nwith the next retained sample"];',
            "  p9_crossbar -> repeat [style=dashed, color=\"#ea580c\"];",
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def _stack_causal_components(dot: str) -> str:
    """Keep disconnected per-service causal components in one reading column."""

    return dot.replace(
        "splines=polyline];",
        'splines=polyline, pack=true, packmode="array_u1"];',
        1,
    )


def _readme() -> str:
    return """# Sensor FIFO → DMA → memory

这个发布包由具名脚本装配并执行一个最小 AXI4-Lite 系统。传感器、DMA、crossbar
和 memory 都是具体 `VirtualDut`；三条 `InterfaceConnection` 连接它们。

## 结构与数据流

![constructed system](structure.svg)

三条 `InterfaceConnection` 在结构图中直接画成 module port 之间的边。粗体标签表示协议，
较小标签表示连接实例；crossbar 框内进一步列出 ingress completer attachment、
两个 egress requester attachment 及其 interface ports。

传感器不是随机信号源。本例使用确定性的递增 sample policy，使同一组 service
opportunity 可以重复生成相同证据。depth=2 的 FIFO 接受前两个样本；额外两个样本
采用 `DROP_NEWEST`，因此 `overrun_count=2`。DMA 的 source stride 为零，反复读取
传感器固定寄存器；destination 每拍增加四字节。

共享 VirtualDut projector 生成的单体展开图：

- [sensor internal structure](sensor-structure.svg)
- [DMA internal structure](dma-structure.svg)

## 模型步骤视图

![model-step waveform](model-steps.svg)

每列是一次已接纳的 `SystemSession` action/service opportunity。它显示 canonical
AXI4-Lite 事件和执行后的 reference state，不表示 ACLK、VALID/READY pin 或物理周期。
一列内出现多条事件，表示一次模型调用内的固定点传播。

## 实际事务顺序

![message sequence](message-sequence.svg)

MSC 取实际 trace 的前十个事件，覆盖第一拍 `sensor read → memory write`。第二拍
重复同一生命周期，但携带下一个样本。

## 已记录的因果边

![causality](causality.svg)

因果图只投影当前运行时已保存的 causal edge。跨显式 `DutAdvanceAction` 的 delayed
emission 尚未保留完整 lineage，因此它是可检查的现有证据，不应解读成完整的端到端
因果证明。

最终 memory 内容是 `40 30 20 10 41 30 20 10`。机器可读结果见
[result.json](result.json)，DOT/WaveJSON 源见 [sources](sources/)，生成边界见
[provenance.json](provenance.json)，完整文件清单见 [manifest.json](manifest.json)。
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


def _build_publication(directory: Path) -> Path:
    system, protocol, memory_space = _build_system()
    session, state, records = _execute(system)
    trace = session.trace(state)
    final_memory = _memory_bytes(state, memory_space)
    expected = b"".join(
        (SAMPLE_BASE + index).to_bytes(BEAT_BYTES, "little")
        for index in range(COPY_BEATS)
    )
    if final_memory != expected:
        raise RuntimeError(
            f"memory mismatch: expected {expected.hex()}, got {final_memory.hex()}"
        )

    store = RunArtifactStore("vdut-sensor-dma-capture", directory)
    publisher = VisualizationPublisher(store)
    publisher.render_dot("structure", _structure_dot(), kind="topology")
    publisher.render_dot(
        "sensor-structure",
        virtual_dut_structure_dot(system.virtual_duts["sensor"]),
        kind="vdut_structure",
    )
    publisher.render_dot(
        "dma-structure",
        virtual_dut_structure_dot(system.virtual_duts["dma"]),
        kind="vdut_structure",
    )
    publisher.render_wave(
        "model-steps", _wavejson(records), kind="execution_step_view"
    )
    publisher.render_dot(
        "message-sequence", _msc_dot(trace), kind="message_sequence"
    )
    publisher.render_dot(
        "causality",
        _stack_causal_components(
            system_trace_dot(
                trace, title="Sensor DMA · recorded causal edges"
            )
        ),
        kind="causality",
    )
    store.write_json(
        "result.json",
        {
            "schema": "protocol-model.showcase.sensor-dma/v1",
            "system": {
                "name": system.name,
                "virtual_duts": list(system.virtual_duts),
                "links": list(system.connections),
            },
            "configuration": {
                "sample_policy": "incrementing",
                "sample_base": f"0x{SAMPLE_BASE:08x}",
                "sensor_capacity": SENSOR_CAPACITY,
                "sensor_opportunities": SENSOR_OPPORTUNITIES,
                "sensor_full_policy": "drop_newest",
                "copy_beats": COPY_BEATS,
                "beat_bytes": BEAT_BYTES,
            },
            "steps": records,
            "assertions": {
                "fault_free": True,
                "blocked_steps": 0,
                "sensor_overruns": 2,
                "dma_done": True,
                "final_quiescent": True,
                "memory_bytes": final_memory.hex(" "),
            },
            "event_count": len(trace.events),
            "causal_edges": [list(edge) for edge in trace.causal_edges],
        },
        kind="execution_result",
    )
    store.write_text(
        "README.md",
        _readme(),
        kind="demo_guide",
        media_type="text/markdown",
    )
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": DEMO_NAME,
            "source": "showcase/demos/vdut/sensor_dma_capture/run.py",
            "command": (
                ".venv/bin/python "
                "showcase/demos/vdut/sensor_dma_capture/run.py"
            ),
            "protocol_model_version": __version__,
            "execution_models": [
                "SensorFifoBackend",
                "SerializedMemoryCopyBackend",
                "ScheduledAddressCrossbarBackend",
                "QueuedAddressResponderBackend",
                "SystemSession",
            ],
            "renderers": {
                "structure": "Graphviz dot + demo-local arranged expansion",
                "sensor_structure": (
                    "Graphviz dot + shared VirtualDut structure projection"
                ),
                "dma_structure": (
                    "Graphviz dot + shared VirtualDut structure projection"
                ),
                "model_steps": "WaveDrom + model-step state projection",
                "message_sequence": (
                    "Graphviz dot + first-beat SystemTrace projection"
                ),
                "causality": "Graphviz dot + shared SystemTrace projection",
            },
            "presentation_boundary": (
                "transaction-semantic execution witness; not random traffic, "
                "raw RTL pins, physical time, or a cycle-golden trace"
            ),
        },
        kind="provenance",
    )
    return store.finalize(
        verdict="PASS",
        protocols=(
            protocol_record_from_system(system),
            protocol_record_from_interface(protocol),
        ),
        cases=(
            {
                "name": "sensor-overrun-and-dma-copy",
                "expected": (
                    "retain the oldest two samples, record two overruns, "
                    "and copy retained data into memory"
                ),
                "observed": "PASS",
            },
        ),
        state={
            "event_count": len(trace.events),
            "causal_edge_count": len(trace.causal_edges),
            "final_memory": final_memory.hex(),
            "final_quiescent": True,
        },
        metadata={
            "publication": "showcase/generated/vdut/sensor-dma-capture",
            "network_scope": "non-coherent AXI4-Lite 1x2 address network",
            "sample_source": "deterministic incrementing policy",
            "raw_pin_capture": False,
            "time_basis": "model_step",
        },
        tool_version=__version__,
    )


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
        description="Publish the Sensor FIFO to DMA capture witness."
    )
    parser.add_argument(
        "--publish-root",
        type=Path,
        default=SHOWCASE_ROOT / "generated" / "vdut",
        help="parent directory of the stable demo publication",
    )
    args = parser.parse_args(argv)
    publish_root = args.publish_root.expanduser().resolve()
    target = publish_root / DEMO_NAME
    build_root = publish_root.parent / ".build"
    build_root.mkdir(parents=True, exist_ok=True)

    _require_renderers()
    with TemporaryDirectory(
        prefix=f"{DEMO_NAME}-", dir=build_root
    ) as temporary:
        staged = Path(temporary) / DEMO_NAME
        manifest = _build_publication(staged)
        if not manifest.is_file():
            raise RuntimeError("staged demo has no manifest")
        for required in (
            "README.md",
            "result.json",
            "structure.svg",
            "sources/structure.dot",
            "sensor-structure.svg",
            "sources/sensor-structure.dot",
            "dma-structure.svg",
            "sources/dma-structure.dot",
            "model-steps.svg",
            "sources/model-steps.json",
            "message-sequence.svg",
            "sources/message-sequence.dot",
            "causality.svg",
            "sources/causality.dot",
            "provenance.json",
        ):
            if not (staged / required).is_file():
                raise RuntimeError(f"staged demo lacks {required}")
        _publish(staged, target)

    try:
        build_root.rmdir()
    except OSError:
        pass
    print(f"Published sensor-DMA demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
