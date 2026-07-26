#!/usr/bin/env python3
"""Publish a two-source edge-interrupt priority and EOI witness."""

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
from protocol_model.integrations.recipes.control.interrupt import (  # noqa: E402
    build_edge_interrupt_controller_vdut,
    build_edge_interrupt_target_vdut,
)
from protocol_model.protocols.control.interrupt import (  # noqa: E402
    InterruptNotificationConfig,
    build_interrupt_notification_interface,
)
from protocol_model.semantics import CanonicalEvent  # noqa: E402
from protocol_model.system.protocol import SystemProtocol  # noqa: E402
from protocol_model.system.session import (  # noqa: E402
    DutAdvanceAction,
    SystemAction,
)
from protocol_model.system.topology.model import (  # noqa: E402
    InterfaceConnection,
    VirtualDutPortRef,
)
from protocol_model.virtual_dut.backend.interrupt import (  # noqa: E402
    InterruptControllerState,
    InterruptTargetState,
)
from protocol_model.virtual_dut.backend.simple import (  # noqa: E402
    CaptureBackend,
    CaptureState,
)
from protocol_model.virtual_dut.boundary.module import VirtualDut  # noqa: E402
from protocol_model.virtual_dut.boundary.port import InterfacePort  # noqa: E402
from protocol_model.visualization import (  # noqa: E402
    VisualizationPublisher,
    system_trace_dot,
    virtual_dut_structure_dot,
)


DEMO_NAME = "interrupt-control-plane"
SYSTEM_NAME = "edge_interrupt_control_plane"
LOW_INTERRUPT_ID = 40
LOW_PRIORITY = 7
HIGH_INTERRUPT_ID = 11
HIGH_PRIORITY = 1


def _notify(reference: int, interrupt_id: int, priority: int) -> CanonicalEvent:
    return CanonicalEvent(
        "INTERRUPT_NOTIFY",
        reference,
        {"interrupt_id": interrupt_id, "priority": priority},
    )


def _notifier_boundary(name: str, protocol) -> VirtualDut:
    return VirtualDut(
        name,
        {"irq": InterfacePort("irq", protocol, "notifier")},
        backend=CaptureBackend(),
        description=(
            "scenario-driven interrupt notifier boundary; captures completion"
        ),
    )


def _build_system():
    protocol = build_interrupt_notification_interface(
        InterruptNotificationConfig(maximum_outstanding=4)
    )
    source_a = _notifier_boundary("source_a", protocol)
    source_b = _notifier_boundary("source_b", protocol)
    controller = build_edge_interrupt_controller_vdut(
        "controller",
        protocol,
        ingress_ports=("from_a", "from_b"),
        target_port="to_cpu",
        capacity=4,
    )
    cpu = build_edge_interrupt_target_vdut(
        "cpu_target", protocol, port_name="irq"
    )
    links = {
        "source_a_irq": InterfaceConnection(
            "source_a_irq",
            protocol,
            {
                "notifier": VirtualDutPortRef("source_a", "irq"),
                "handler": VirtualDutPortRef("controller", "from_a"),
            },
        ),
        "source_b_irq": InterfaceConnection(
            "source_b_irq",
            protocol,
            {
                "notifier": VirtualDutPortRef("source_b", "irq"),
                "handler": VirtualDutPortRef("controller", "from_b"),
            },
        ),
        "cpu_irq": InterfaceConnection(
            "cpu_irq",
            protocol,
            {
                "notifier": VirtualDutPortRef("controller", "to_cpu"),
                "handler": VirtualDutPortRef("cpu_target", "irq"),
            },
        ),
    }
    return (
        SystemProtocol(
            SYSTEM_NAME,
            {
                item.name: item
                for item in (source_a, source_b, controller, cpu)
            },
            links,
        ),
        protocol,
    )


def _event_record(event) -> dict[str, object]:
    return {
        "index": event.index,
        "link": event.connection,
        "source": event.source.qualified_name,
        "destination": event.destination.qualified_name,
        "kind": event.event.kind,
        "reference": event.event.key,
        "payload": dict(event.event.payload),
    }


def _notification_text(item) -> str:
    notification = item.notification
    return (
        f"id={notification.interrupt_id} "
        f"p={notification.priority} "
        f"arrival={item.arrival_serial}"
    )


def _snapshot(state) -> dict[str, object]:
    controller = state.dut_states["controller"]
    target = state.dut_states["cpu_target"]
    source_a = state.dut_states["source_a"]
    source_b = state.dut_states["source_b"]
    assert isinstance(controller, InterruptControllerState)
    assert isinstance(target, InterruptTargetState)
    assert isinstance(source_a, CaptureState)
    assert isinstance(source_b, CaptureState)
    return {
        "controller": {
            "pending": [_notification_text(item) for item in controller.pending],
            "active": (
                None
                if controller.active is None
                else {
                    "origin": _notification_text(controller.active.pending),
                    "delivery_reference": (
                        controller.active.delivery.notification_ref
                    ),
                }
            ),
            "occupancy": len(controller.pending)
            + (controller.active is not None),
            "completed_count": controller.completed_count,
        },
        "cpu_target": {
            "active": (
                None
                if target.active is None
                else target.active.interrupt_id
            ),
            "handled": [item.interrupt_id for item in target.handled],
        },
        "source_completion_count": {
            "source_a": len(source_a.received),
            "source_b": len(source_b.received),
        },
    }


def _record(
    label: str,
    short_label: str,
    transition,
) -> dict[str, object]:
    return {
        "label": label,
        "short_label": short_label,
        "fault": (
            None
            if transition.fault is None
            else {
                "rule": transition.fault.rule,
                "reason": transition.fault.reason,
            }
        ),
        "blocked": (
            None
            if transition.blocked is None
            else {
                "resource": transition.blocked.resource,
                "location": transition.blocked.location,
                "reason": transition.blocked.reason,
            }
        ),
        "emissions": [_event_record(item) for item in transition.emissions],
        "post_state": _snapshot(transition.state),
    }


def _execute(system):
    session = system.open_session()
    state = session.initial_state()
    records: list[dict[str, object]] = []
    actions = (
        (
            "A notifies low urgency · id 40 / priority 7",
            "A NOTIFY · 40/p7",
            SystemAction(
                VirtualDutPortRef("source_a", "irq"),
                _notify(9, LOW_INTERRUPT_ID, LOW_PRIORITY),
            ),
        ),
        (
            "B later notifies high urgency · id 11 / priority 1",
            "B NOTIFY · 11/p1",
            SystemAction(
                VirtualDutPortRef("source_b", "irq"),
                _notify(2, HIGH_INTERRUPT_ID, HIGH_PRIORITY),
            ),
        ),
        (
            "controller selects and delivers highest priority",
            "select · 11/p1",
            DutAdvanceAction("controller"),
        ),
        (
            "CPU explicitly EOI id 11; controller delivers id 40",
            "EOI 11 → deliver 40",
            DutAdvanceAction("cpu_target"),
        ),
        (
            "CPU explicitly EOI id 40",
            "EOI 40",
            DutAdvanceAction("cpu_target"),
        ),
    )
    for label, short_label, action in actions:
        transition = session.step(state, action)
        records.append(_record(label, short_label, transition))
        if transition.fault is not None:
            raise RuntimeError(
                f"interrupt witness failed at {label}: "
                f"{transition.fault.rule}: {transition.fault.reason}"
            )
        if transition.blocked is not None:
            raise RuntimeError(
                f"interrupt witness unexpectedly blocked at {label}: "
                f"{transition.blocked.resource}"
            )
        state = transition.state

    controller = state.dut_states["controller"]
    target = state.dut_states["cpu_target"]
    assert isinstance(controller, InterruptControllerState)
    assert isinstance(target, InterruptTargetState)
    handled = tuple(item.interrupt_id for item in target.handled)
    if handled != (HIGH_INTERRUPT_ID, LOW_INTERRUPT_ID):
        raise RuntimeError(f"priority delivery mismatch: got {handled!r}")
    if controller.completed_count != 2:
        raise RuntimeError("controller did not correlate two target EOIs")
    if not session.is_quiescent(state):
        raise RuntimeError("interrupt witness did not reach quiescence")
    return session, state, records


def _categorical_lane(name: str, values: list[object]) -> dict[str, object]:
    return {
        "name": name,
        "wave": "=" * len(values),
        "data": [str(value) for value in values],
    }


def _event_label(item: dict[str, object]) -> str:
    payload = item["payload"]
    suffix = f" id={payload['interrupt_id']}"
    if item["kind"] == "INTERRUPT_NOTIFY":
        suffix += f" p={payload['priority']}"
    return f"e{item['index']} {item['kind'].removeprefix('INTERRUPT_')}{suffix}"


def _event_lane(records, name: str, predicate) -> dict[str, object]:
    values = []
    for record in records:
        matching = [item for item in record["emissions"] if predicate(item)]
        values.append(" + ".join(_event_label(item) for item in matching) or "—")
    return _categorical_lane(name, values)


def _pending_text(state: dict[str, object]) -> str:
    pending = state["controller"]["pending"]
    if not pending:
        return "empty"
    return " | ".join(
        value.replace("priority=", "p=").replace("arrival=", "a=")
        for value in pending
    )


def _active_text(state: dict[str, object]) -> str:
    active = state["controller"]["active"]
    if active is None:
        return "none"
    origin = active["origin"].split(" arrival=", 1)[0]
    return f"{origin} · ref={active['delivery_reference']}"


def _wavejson(records: list[dict[str, object]]) -> dict[str, object]:
    states = [record["post_state"] for record in records]
    return {
        "signal": [
            _categorical_lane(
                "MODEL STEP · not clock",
                [f"S{index}" for index in range(len(records))],
            ),
            [
                "scheduler",
                _categorical_lane(
                    "completed action / service opportunity",
                    [record["short_label"] for record in records],
                ),
            ],
            [
                "accepted canonical events",
                _event_lane(
                    records,
                    "sources → controller",
                    lambda item: item["kind"] == "INTERRUPT_NOTIFY"
                    and item["destination"].startswith("controller.from_"),
                ),
                _event_lane(
                    records,
                    "controller → sources · retained ACK",
                    lambda item: item["kind"] == "INTERRUPT_COMPLETE"
                    and item["source"].startswith("controller.from_"),
                ),
                _event_lane(
                    records,
                    "controller → CPU target",
                    lambda item: item["kind"] == "INTERRUPT_NOTIFY"
                    and item["source"] == "controller.to_cpu",
                ),
                _event_lane(
                    records,
                    "CPU target → controller · EOI",
                    lambda item: item["kind"] == "INTERRUPT_COMPLETE"
                    and item["source"] == "cpu_target.irq",
                ),
            ],
            [
                "post-state",
                _categorical_lane(
                    "controller pending queue",
                    [_pending_text(state) for state in states],
                ),
                _categorical_lane(
                    "controller active delivery",
                    [_active_text(state) for state in states],
                ),
                _categorical_lane(
                    "CPU active interrupt",
                    [
                        state["cpu_target"]["active"]
                        if state["cpu_target"]["active"] is not None
                        else "none"
                        for state in states
                    ],
                ),
                _categorical_lane(
                    "CPU handled order",
                    [
                        ", ".join(map(str, state["cpu_target"]["handled"]))
                        or "empty"
                        for state in states
                    ],
                ),
                _categorical_lane(
                    "controller completed count",
                    [state["controller"]["completed_count"] for state in states],
                ),
            ],
        ],
        "head": {
            "text": (
                "Edge-interrupt notification · priority select and explicit EOI"
            )
        },
        "foot": {
            "text": (
                "1 column = 1 completed SystemSession action/service opportunity "
                "· POST-STATE · NOT clock, RTL pins, latency, GIC or PLIC timing"
            )
        },
        "config": {"hscale": 6},
    }


def _topology_dot() -> str:
    """A compact fixed layout for this two-source demonstration."""

    return r'''digraph interrupt_control_plane_topology {
  rankdir=LR;
  label="Edge-interrupt control plane · three notification InterfaceConnection instances";
  labelloc="t";
  graph [bgcolor="white", pad=0.28, nodesep=0.6, ranksep=0.85,
         splines=polyline, ordering=out, newrank=true];
  node [fontname="sans-serif", fontsize=10, shape=box,
        style="rounded,filled", margin="0.15,0.1"];
  edge [fontname="sans-serif", fontsize=9, color="#52606d", penwidth=1.35];

  source_a [label="source_a · VirtualDut\nscenario-driven notifier boundary\nid 40 · priority 7",
    fillcolor="#eff6ff", color="#2563eb", group="a"];
  source_b [label="source_b · VirtualDut\nscenario-driven notifier boundary\nid 11 · priority 1",
    fillcolor="#eff6ff", color="#2563eb", group="b"];
  controller [label="controller · VirtualDut\nretain capacity 4\nlower priority value first\none active target delivery",
    fillcolor="#fff7ed", color="#ea580c", penwidth=1.7];
  cpu [label="cpu_target · VirtualDut\none active slot\nexplicit EOI service",
    fillcolor="#ecfdf5", color="#059669"];

  { rank=same; source_a; source_b; }
  source_a -> source_b [style=invis, weight=80];

  source_a -> controller [dir=none, label=<<B>interrupt_edge_notification</B><BR/><FONT POINT-SIZE="8">source_a_irq · source_a.irq ↔ controller.from_a</FONT>>];
  source_b -> controller [dir=none, label=<<B>interrupt_edge_notification</B><BR/><FONT POINT-SIZE="8">source_b_irq · source_b.irq ↔ controller.from_b</FONT>>];
  controller -> cpu [dir=none, label=<<B>interrupt_edge_notification</B><BR/><FONT POINT-SIZE="8">cpu_irq · controller.to_cpu ↔ cpu_target.irq</FONT>>];
}
'''


def _msc_event_label(event) -> str:
    payload = event.event.payload
    reference = event.event.key
    if event.event.kind == "INTERRUPT_NOTIFY":
        return (
            f"e{event.index} NOTIFY · id {payload['interrupt_id']} · "
            f"p{payload['priority']} · ref {reference}"
        )
    completion = "EOI" if event.source.dut == "cpu_target" else "RETAINED ACK"
    return f"e{event.index} {completion} · id {payload['interrupt_id']} · ref {reference}"


def _message_sequence_dot(trace) -> str:
    participants = ("source_a", "source_b", "controller", "cpu_target")
    display = {
        "source_a": "notifier A\nlow arrives first",
        "source_b": "notifier B\nhigh arrives second",
        "controller": "priority controller",
        "cpu_target": "explicit-EOI target",
    }
    lines = [
        "digraph interrupt_msc {",
        "  rankdir=TB;",
        '  label="Interrupt control plane · actual accepted event sequence";',
        '  labelloc="t";',
        '  graph [bgcolor="white", pad=0.3, nodesep=0.85, ranksep=0.34, newrank=true];',
        '  node [fontname="sans-serif", fontsize=10];',
        '  edge [fontname="sans-serif", fontsize=9];',
    ]
    for participant in participants:
        lines.append(
            f"  h_{participant} [shape=box, style=\"rounded,filled\", "
            f"fillcolor=\"#f8fafc\", "
            f"group={json.dumps(participant)}, "
            f"label={json.dumps(display[participant], ensure_ascii=False)}];"
        )
    lines.append(
        "  { rank=same; h_source_a; h_source_b; h_controller; h_cpu_target; }"
    )
    previous = {participant: f"h_{participant}" for participant in participants}
    for row, event in enumerate(trace.events):
        row_nodes = []
        for participant in participants:
            node = f"p{row}_{participant}"
            row_nodes.append(node)
            lines.append(
                f"  {node} [shape=point, width=0.035, label=\"\", "
                f'color="#94a3b8", group={json.dumps(participant)}];'
            )
            lines.append(
                f"  {previous[participant]} -> {node} "
                '[arrowhead=none, color="#cbd5e1", penwidth=1.0, weight=1000];'
            )
            previous[participant] = node
        lines.append("  { rank=same; " + "; ".join(row_nodes) + "; }")
        lines.append(
            "  " + " -> ".join(row_nodes) + " [style=invis, weight=100];"
        )
        source = f"p{row}_{event.source.dut}"
        destination = f"p{row}_{event.destination.dut}"
        notify = event.event.kind == "INTERRUPT_NOTIFY"
        color = "#2563eb" if notify else "#059669"
        lines.append(
            f"  {source} -> {destination} [constraint=false, penwidth=1.6, "
            f"color={json.dumps(color)}, fontcolor={json.dumps(color)}, "
            f"label={json.dumps(_msc_event_label(event), ensure_ascii=False)}];"
        )
    lines.extend(
        (
            '  note [shape=note, style="rounded,filled", fillcolor="#fff7ed", '
            'color="#ea580c", label="Selection result: id 11 (p1) before id 40 (p7)\n'
            'Next delivery waits for explicit EOI"];',
            "  p7_controller -> note [style=dashed, color=\"#ea580c\"];",
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def _controller_structure_dot(controller: VirtualDut) -> str:
    """Keep the shared projection but stack its long pipeline for reading."""

    return virtual_dut_structure_dot(controller).replace(
        "  rankdir=LR;", "  rankdir=TB;", 1
    )


def _stack_causal_components(dot: str) -> str:
    """Stack disconnected runtime causal components in one reading column."""

    return dot.replace(
        "splines=polyline];",
        'splines=polyline, pack=true, packmode="array_u1"];',
        1,
    )


def _readme() -> str:
    return """# Edge-interrupt notification control plane

这个发布包来自一次真实 `SystemSession` 执行。两路 scenario-driven notifier 通过
两个中断通知 `InterfaceConnection` 连接到 priority controller；controller 再通过第三条
link 连接 explicit-EOI target。

## 系统连接

![topology](topology.svg)

`source_a` 和 `source_b` 是演示环境驱动的 notifier 边界。它们使用 `CaptureBackend`
接收 controller 在安全保留通知后返回的 completion，并不模拟传感器或设备内部行为。
`controller` 与 `cpu_target` 是 constructed `VirtualDut`。

这三条 link 都是同一个 `control.interrupt_notification` 协议的实例。协议只规定一次
edge notification 的字段、live reference、FIFO completion 和 correlation；priority
选择、容量、active slot 与 EOI 调度属于 controller/target 的 module 行为。

拓扑图用 VirtualDut 之间的直接边表示这些 link：粗体是协议名，较小的一行是
InterfaceConnection 实例名和两端的具体 port，因此图中没有额外的中断交换节点。

## Controller 的可检查内部构造

![controller structure](controller-structure.svg)

这张图由共享 VirtualDut projector 生成。入口 attachment 把 link event 解成
notification operation；controller 保留 edge，按“较小 priority 优先、同优先级按
到达顺序”选择，并维持一个 active target delivery，直到匹配的 EOI 返回。

## 模型步骤视图

![model-step view](model-steps.svg)

A 先提交 `id=40, priority=7`，B 后提交 `id=11, priority=1`。S2 的显式 controller
service opportunity 选择 id 11。S3 的 CPU service opportunity 发出 id 11 的 EOI；
同一次固定点传播中 controller 激活并投递 id 40。S4 再完成 id 40。

每一列是一项已经完成的模型 action/service opportunity，状态 lane 是该列结束后的
post-state。它不是时钟波形，不表达物理延迟、RTL pin 或 cycle-exact EOI 时序。

## 实际消息顺序

![message sequence](message-sequence.svg)

MSC 中每支箭头来自本次执行的 `SystemTrace`，包括源通知、入口 completion、target
delivery 和 EOI。controller-facing delivery 使用新的 reference；它与原 ingress
reference 的关联保存在 controller state 中。

## 当前记录的因果边

![recorded causality](causality.svg)

因果图只显示 runtime 已保存的 causal edge。由独立 `DutAdvanceAction` 稍后触发的
delivery 尚未携带原 ingress event 的完整 delayed lineage，所以本图不能被解读成
完整的端到端因果证明。

## 范围边界

本例建模 edge-notification transport 与一个 priority controller/EOI target。它没有
CSR 地址端口，因此当前 controller 不具备可寻址配置界面；这不妨碍它作为控制平面
VirtualDut 工作。若后续需要 mask、priority register 或 status register，可以再 attach
一个地址协议端口，不能据此推断已经实现 GIC、PLIC、APIC、level-trigger、affinity、
抢占、多 target 或 MSI。

机器可读结果见 [result.json](result.json)，图源见 [sources](sources/)，发布边界见
[provenance.json](provenance.json)，完整文件表见 [manifest.json](manifest.json)。
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
    system, protocol = _build_system()
    session, state, records = _execute(system)
    trace = session.trace(state)
    target = state.dut_states["cpu_target"]
    controller = state.dut_states["controller"]
    assert isinstance(target, InterruptTargetState)
    assert isinstance(controller, InterruptControllerState)
    handled = [item.interrupt_id for item in target.handled]

    store = RunArtifactStore("vdut-interrupt-control-plane", directory)
    publisher = VisualizationPublisher(store)
    publisher.render_dot(
        "topology",
        _topology_dot(),
        kind="topology",
    )
    publisher.render_dot(
        "controller-structure",
        _controller_structure_dot(system.virtual_duts["controller"]),
        kind="vdut_structure",
    )
    publisher.render_wave(
        "model-steps",
        _wavejson(records),
        kind="execution_step_view",
    )
    publisher.render_dot(
        "message-sequence",
        _message_sequence_dot(trace),
        kind="message_sequence",
    )
    publisher.render_dot(
        "causality",
        _stack_causal_components(
            system_trace_dot(
                trace,
                title="Interrupt control plane · recorded causal edges",
            )
        ),
        kind="causality",
    )
    store.write_json(
        "result.json",
        {
            "schema": "protocol-model.showcase.interrupt-control-plane/v1",
            "system": {
                "name": system.name,
                "virtual_duts": list(system.virtual_duts),
                "links": list(system.connections),
            },
            "configuration": {
                "controller_capacity": 4,
                "priority_order": "lower_numeric_value_first",
                "preemption": False,
                "target_completion": "explicit_eoi",
                "notifications": [
                    {
                        "source": "source_a",
                        "interrupt_id": LOW_INTERRUPT_ID,
                        "priority": LOW_PRIORITY,
                        "arrival": 0,
                    },
                    {
                        "source": "source_b",
                        "interrupt_id": HIGH_INTERRUPT_ID,
                        "priority": HIGH_PRIORITY,
                        "arrival": 1,
                    },
                ],
            },
            "steps": records,
            "assertions": {
                "fault_free": True,
                "blocked_steps": 0,
                "handled_order": handled,
                "expected_handled_order": [HIGH_INTERRUPT_ID, LOW_INTERRUPT_ID],
                "completed_count": controller.completed_count,
                "final_quiescent": True,
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
            "source": (
                "showcase/demos/vdut/interrupt_control_plane/run.py"
            ),
            "command": (
                ".venv/bin/python "
                "showcase/demos/vdut/interrupt_control_plane/run.py"
            ),
            "protocol_model_version": __version__,
            "execution_models": [
                "SystemSession",
                "PriorityInterruptControllerBackend",
                "ExplicitEoiInterruptTargetBackend",
                "CaptureBackend notifier boundaries",
            ],
            "renderers": {
                "topology": "Graphviz dot + demo-local fixed topology layout",
                "controller_structure": (
                    "Graphviz dot + shared VirtualDut structure projection"
                ),
                "model_steps": "WaveDrom + model-step state projection",
                "message_sequence": (
                    "Graphviz dot + demo-local SystemTrace MSC projection"
                ),
                "causality": "Graphviz dot + shared SystemTrace projection",
            },
            "presentation_boundary": (
                "edge-notification transaction-semantic witness; not an RTL "
                "clock waveform, addressable interrupt architecture, GIC, "
                "PLIC, APIC, or complete delayed-causality proof"
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
                "name": "priority-and-explicit-eoi",
                "expected": (
                    "later id 11/p1 is delivered before earlier id 40/p7; "
                    "each next delivery waits for explicit EOI"
                ),
                "observed": "PASS",
            },
        ),
        state={
            "event_count": len(trace.events),
            "causal_edge_count": len(trace.causal_edges),
            "handled_order": handled,
            "controller_completed_count": controller.completed_count,
            "final_quiescent": True,
        },
        metadata={
            "publication": (
                "showcase/generated/vdut/interrupt-control-plane"
            ),
            "control_scope": "edge interrupt notification",
            "notifier_source": "scenario-driven CaptureBackend boundaries",
            "addressable": False,
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
        description="Publish the edge-interrupt priority and EOI witness."
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
            "topology.svg",
            "sources/topology.dot",
            "controller-structure.svg",
            "sources/controller-structure.dot",
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
    print(f"Published interrupt control-plane demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
