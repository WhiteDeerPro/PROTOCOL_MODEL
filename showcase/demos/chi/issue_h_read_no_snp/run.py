#!/usr/bin/env python3
"""Publish the executable CHI Issue H direct ReadNoSnp slice."""

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
from protocol_model.artifacts import RunArtifactStore  # noqa: E402
from protocol_model.protocols.amba.chi.issue_h.interface import (  # noqa: E402
    ChiReadNoSnpComplete,
    ChiReadNoSnpDirectLedger,
    ChiReadNoSnpDirectProfile,
    ChiReadNoSnpIssue,
)
from protocol_model.protocols.amba.chi.issue_h.participants import (  # noqa: E402
    ChiDirectHomeAccept,
    ChiDirectHomeNode,
    ChiDirectHomeService,
)
from protocol_model.protocols.amba.chi.issue_h.representation import (  # noqa: E402
    ChiIssueHDatProfile,
    ChiIssueHReqProfile,
    ChiNetworkPacket,
    ChiReadNoSnpMessage,
)
from protocol_model.protocols.amba.chi.issue_h.transport import (  # noqa: E402
    ChiDatChannelProfile,
    ChiDatDrain,
    ChiDatEnqueue,
    ChiDatPathTick,
    ChiDatPointToPointSession,
    ChiLinkEndpointRef,
    ChiReqChannelProfile,
    ChiReqDrain,
    ChiReqEnqueue,
    ChiReqPathTick,
    ChiReqPointToPointSession,
    ChiTransportLink,
    ChiTransportLinkProfile,
)
from protocol_model.visualization import (  # noqa: E402
    GraphvizRenderer,
    VisualizationPublisher,
)


DEMO_NAME = "issue-h-read-no-snp"


def _quoted(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _apply(component, state, action):
    transition = component.step(state, action)
    if transition.fault is not None:
        raise RuntimeError(
            f"{component.name} faulted: {transition.fault.reason}"
        )
    if transition.blocked is not None:
        raise RuntimeError(
            f"{component.name} blocked: {transition.blocked.reason}"
        )
    return transition


def _build_components():
    profile = ChiReadNoSnpDirectProfile(
        requester_node_id=0x07,
        home_node_id=0x21,
        data_width=128,
        outstanding_capacity=1,
    )
    requester = ChiReadNoSnpDirectLedger("rn_i.reads", profile)
    home = ChiDirectHomeNode(
        "home",
        profile,
        lambda request: 0xC000_0000 | request.address,
        request_capacity=1,
    )
    request_path = ChiReqPointToPointSession(
        ChiTransportLink(
            "rn_to_home",
            ChiLinkEndpointRef("rn_i", "txreq"),
            ChiLinkEndpointRef("home", "rxreq"),
            ChiTransportLinkProfile(
                request=ChiReqChannelProfile(
                    representation=ChiIssueHReqProfile(),
                    credit_capacities=(1,),
                    observation="rn_to_home.req",
                ),
                data=None,
                clock="chi_clk",
                activation_observation="rn_to_home.active",
            ),
        ),
        transmitter_capacity=1,
        receiver_capacities_by_plane=(1,),
    )
    data_path = ChiDatPointToPointSession(
        ChiTransportLink(
            "home_to_rn",
            ChiLinkEndpointRef("home", "txdat"),
            ChiLinkEndpointRef("rn_i", "rxdat"),
            ChiTransportLinkProfile(
                request=None,
                data=ChiDatChannelProfile(
                    representation=ChiIssueHDatProfile(data_width=128),
                    credit_capacity=1,
                    observation="home_to_rn.dat",
                ),
                clock="chi_clk",
                activation_observation="home_to_rn.active",
            ),
        ),
        transmitter_capacity=1,
        receiver_capacity=1,
    )
    return profile, requester, home, request_path, data_path


def _execute() -> dict[str, object]:
    profile, requester, home, request_path, data_path = _build_components()
    request = ChiReadNoSnpMessage(
        transaction_id=3,
        address=0x4020,
        size=3,
        order=0,
        allow_retry=True,
        protocol_credit_type=0,
        expect_completion_ack=False,
        memory_attributes=0,
    )
    request_packet = ChiNetworkPacket.request(
        request,
        source_id=profile.requester_node_id,
        target_id=profile.home_node_id,
    )

    requester_state = _apply(
        requester,
        requester.initial_state(),
        ChiReadNoSnpIssue(request),
    ).state
    request_state = _apply(
        request_path,
        request_path.initial_state(),
        ChiReqEnqueue(request_packet),
    ).state
    data_state = data_path.initial_state()
    transport_ticks: list[dict[str, object]] = []

    def tick_both(*, request_active: bool, data_active: bool) -> None:
        nonlocal request_state, data_state
        request_step = _apply(
            request_path,
            request_state,
            ChiReqPathTick(active=request_active),
        )
        data_step = _apply(
            data_path,
            data_state,
            ChiDatPathTick(active=data_active),
        )
        request_state = request_step.state
        data_state = data_step.state
        request_observation = request_step.emissions[0]
        data_observation = data_step.emissions[0]
        transport_ticks.append(
            {
                "tick": request_observation.tick,
                "request": {
                    "phase": request_observation.phase.value,
                    "credit_grant": any(
                        request_observation.grants_by_plane
                    ),
                    "transfer": (
                        None
                        if request_observation.transfer is None
                        else request_observation.transfer.kind.value
                    ),
                },
                "data": {
                    "phase": data_observation.phase.value,
                    "credit_grant": data_observation.grant,
                    "transfer": (
                        None
                        if data_observation.transfer is None
                        else data_observation.transfer.kind.value
                    ),
                },
            }
        )

    for _ in range(3):
        tick_both(request_active=True, data_active=True)

    captured_request_packet = (
        request_state.receiver.captured[0].flit.packet
    )
    captured_request = captured_request_packet.message
    home_state = _apply(
        home,
        home.initial_state(),
        ChiDirectHomeAccept(captured_request),
    ).state
    request_state = _apply(
        request_path, request_state, ChiReqDrain()
    ).state
    serviced = _apply(home, home_state, ChiDirectHomeService())
    home_state = serviced.state
    response = serviced.emissions[0]
    response_packet = ChiNetworkPacket.data(
        response,
        source_id=profile.home_node_id,
        target_id=profile.requester_node_id,
    )
    data_state = _apply(
        data_path, data_state, ChiDatEnqueue(response_packet)
    ).state

    tick_both(request_active=False, data_active=True)
    captured_response_packet = data_state.receiver.captured[0].flit.packet
    captured_response = captured_response_packet.message
    completed = _apply(
        requester,
        requester_state,
        ChiReadNoSnpComplete(captured_response),
    )
    requester_state = completed.state
    data_state = _apply(data_path, data_state, ChiDatDrain()).state

    tick_both(request_active=False, data_active=False)
    tick_both(request_active=False, data_active=False)

    assertions = {
        "request_identity_preserved": (
            captured_request_packet == request_packet
            and captured_request == request
        ),
        "response_identity_correlated": (
            captured_response_packet == response_packet
            and captured_response.semantic_key == request.semantic_key
        ),
        "data_id_matches_chunk": captured_response.data_id == 2,
        "requester_quiescent": requester.is_quiescent(requester_state),
        "home_quiescent": home.is_quiescent(home_state),
        "request_link_quiescent": request_path.is_quiescent(request_state),
        "data_link_quiescent": data_path.is_quiescent(data_state),
        "captures_drained": (
            request_state.receiver.depth == 0
            and data_state.receiver.depth == 0
        ),
    }
    if not all(assertions.values()):
        failed = ", ".join(
            name for name, value in assertions.items() if not value
        )
        raise RuntimeError(f"direct-read assertions failed: {failed}")

    return {
        "schema": "protocol-model.showcase.chi-direct-read/v1",
        "profile": {
            "issue": "H",
            "requester_node_id": profile.requester_node_id,
            "home_node_id": profile.home_node_id,
            "data_width": profile.data_width,
            "outstanding_capacity": profile.outstanding_capacity,
            "request_fifo_capacity": 1,
            "home_fifo_capacity": 1,
            "data_fifo_capacity": 1,
            "link_credit_capacity": 1,
        },
        "request": request,
        "response": captured_response,
        "transport_ticks": transport_ticks,
        "assertions": assertions,
        "result": {
            "data": completed.emissions[0].data,
            "completed_count": len(requester_state.completed),
        },
    }


def _time_space_dot(result: dict[str, object]) -> str:
    request = result["request"]
    response = result["response"]
    rows = (
        ("E0 · allocate TxnID=3\noutstanding 0→1", ""),
        (
            "E1 · TXREQ receives L-Credit",
            "E1 · TXDAT receives L-Credit\ncredit usable next frame",
        ),
        ("E2 · REQ FIFO 1→0", "E2 · REQ capture 0→1"),
        ("", "E3 · accept request\ndrain REQ capture"),
        ("", "E4 · service FIFO head\nenqueue CompData"),
        ("E5 · DAT capture 0→1", "E5 · DAT FIFO 1→0"),
        ("E6 · correlate completion\noutstanding 1→0", ""),
        ("E7 · REQ/DAT captures drained", "E7 · both links return to STOP"),
    )
    lines = [
        "digraph chi_direct_read {",
        "  rankdir=TB;",
        '  graph [bgcolor="white", pad=0.35, ranksep=0.72, '
        'nodesep=1.15, splines=line, outputorder=edgesfirst, '
        'labelloc="t", fontsize=16, '
        'label="CHI Issue H · direct ReadNoSnp / event-index view"];',
        '  node [fontname="sans-serif", fontsize=10, shape=box, '
        'style="rounded,filled", margin="0.10,0.07"];',
        '  edge [fontname="sans-serif", fontsize=9];',
        '  rn_head [group="rn", fillcolor="#dbeafe", color="#2563eb", penwidth=1.6, '
        'label="RN-I requester\nledger + TXREQ + RXDAT"];',
        '  home_head [group="home", fillcolor="#ffedd5", color="#ea580c", penwidth=1.6, '
        'label="Direct Home\nRXREQ + FIFO/service + TXDAT"];',
        "  { rank=same; rn_head; home_head; }",
    ]
    for index, (rn_label, home_label) in enumerate(rows):
        for side, label, color, fill in (
            ("rn", rn_label, "#2563eb", "#eff6ff"),
            ("home", home_label, "#ea580c", "#fff7ed"),
        ):
            if label:
                lines.append(
                    f"  {side}{index} [group={_quoted(side)}, "
                    f"color={_quoted(color)}, "
                    f"fillcolor={_quoted(fill)}, label={_quoted(label)}];"
                )
            else:
                lines.append(
                    f'  {side}{index} [group={_quoted(side)}, '
                    f'shape=point, width=0.055, '
                    f'height=0.055, color={_quoted(color)}, '
                    f'fillcolor={_quoted(color)}, label=""];'
        )
        lines.append(
            f"  {{ rank=same; rn{index}; home{index}; }}"
        )
    lines.extend(
        (
            "  rn_head -> home_head [style=invis, weight=80];",
            "  rn_head -> rn0 "
            '[style=dashed, color="#94a3b8", arrowhead=none];',
            "  home_head -> home0 "
            '[style=dashed, color="#94a3b8", arrowhead=none];',
        )
    )
    for index in range(len(rows) - 1):
        lines.append(
            f"  rn{index} -> rn{index + 1} "
            '[style=dashed, color="#94a3b8", arrowhead=none];'
        )
        lines.append(
            f"  home{index} -> home{index + 1} "
            '[style=dashed, color="#94a3b8", arrowhead=none];'
        )
    lines.extend(
        (
            "  rn2 -> home2 [constraint=false, color=\"#2563eb\", "
            "penwidth=2.0, xlabel=\"REQ · ReadNoSnp\\n"
            f"Addr={request.address:#x} · uses old L-Credit\"];",
            "  home5 -> rn5 [constraint=false, color=\"#ea580c\", "
            "penwidth=2.0, xlabel=\"DAT · CompData\\n"
            f"DataID={response.data_id} · uses old L-Credit\"];",
            '  boundary [shape=note, fillcolor="#f8fafc", '
            'color="#64748b", label="event_index shows causal order, not '
            'raw RTL cycles\\nforward REQ and reverse DAT are independent '
            'directed transport links"];',
            "  rn7 -> boundary [style=invis];",
            "  home7 -> boundary [style=invis];",
            "}",
        )
    )
    return "\n".join(lines) + "\n"


def _guide(result: dict[str, object]) -> str:
    response = result["response"]
    return f"""# CHI Issue H：最小 direct-Home read

![事务时空图](transaction-time-space.svg)

本例执行了一次 `ReadNoSnp`：RN-I 先分配 `(SrcID=0x07, TxnID=3)` outstanding；请求经
RN→Home 的 REQ link 到达 direct Home；Home 显式 service 后生成 `CompData`；响应经 Home→RN 的
DAT link 返回，并以 `(TgtID=0x07, TxnID=3)` 关闭原事务。地址 `0x4020` 在 128-bit DAT 配置下对应
`DataID={response.data_id}`。

图的纵轴是 `event_index`，用于表达因果顺序。它不是 raw pin waveform，也不规定 RTL 必须在相同周期
插入或省略空拍。REQ 与 DAT 是方向相反、分别激活和持有 L-Credit 的两条 link。

## 本次实际检查

- L-Credit 在收到后的下一帧才可使用；
- 有限 TX FIFO、receiver reservation 与 capture 容量保持一致；
- Home 接收成功后才 drain REQ capture；
- RN correlation 成功后才 drain DAT capture；
- completion 释放 outstanding，两个 link 最终回到 STOP。

## 当前边界

这是 direct Home、单 DAT flit、common-clock reference transport 的受限 happy path。它不包含 bit codec、
Retry/P-Credit、RSP/SNP、完整 RN-I/HN、router、缓存一致性或 raw RTL timing。participant 与 capture 间的
交接由场景显式编排；多事务组合仍需要统一 admission/rollback。

机器结果见 [result.json](result.json)，图源见 [sources](sources/)，生成边界见
[provenance.json](provenance.json)。
"""


def _require_renderer() -> None:
    if shutil.which("dot") is None:
        raise SystemExit("Missing renderer dependency: Graphviz 'dot'")


def _build_publication(directory: Path) -> Path:
    result = _execute()
    store = RunArtifactStore("chi-issue-h-direct-read", directory)
    publisher = VisualizationPublisher(
        store, graphviz=GraphvizRenderer("dot")
    )
    publisher.render_dot(
        "transaction-time-space",
        _time_space_dot(result),
        kind="transaction_time_space",
    )
    store.write_json("result.json", result, kind="scenario_result")
    store.write_text(
        "README.md",
        _guide(result),
        kind="demo_guide",
        media_type="text/markdown",
    )
    store.write_json(
        "provenance.json",
        {
            "schema": "protocol-model.showcase.provenance/v1",
            "demo": DEMO_NAME,
            "source": (
                "showcase/demos/chi/issue_h_read_no_snp/run.py"
            ),
            "command": (
                ".venv/bin/python "
                "showcase/demos/chi/issue_h_read_no_snp/run.py"
            ),
            "protocol_model_version": __version__,
            "time_basis": "event_index with synchronized reference ticks",
            "construction": [
                "ChiReadNoSnpDirectLedger",
                "ChiDirectHomeNode",
                "ChiReqPointToPointSession",
                "ChiDatPointToPointSession",
            ],
            "renderer": "Graphviz dot; automatic hierarchical layout",
            "presentation_boundary": (
                "direct Home, one CompData flit, common-clock reference "
                "transport; no bit codec, raw waveform, Retry/RSP/SNP, "
                "complete RN/HN, routing, or coherence"
            ),
        },
        kind="provenance",
    )
    return store.finalize(
        verdict="PASS",
        protocols=(
            {
                "scope": "interface",
                "identity": "chi.issue_h.direct_read",
                "definition": "restricted ReadNoSnp to CompData lifecycle",
                "parameters": result["profile"],
            },
            {
                "scope": "transport",
                "identity": "chi.issue_h.req_dat_links",
                "definition": "independent directed REQ and DAT links",
                "parameters": {
                    "activation": "link-wide",
                    "credit_capacity": 1,
                },
            },
        ),
        cases=(
            {
                "name": "direct-read",
                "expected": "ReadNoSnp completes with correlated CompData",
                "observed": "PASS",
            },
        ),
        state={
            "completed_count": result["result"]["completed_count"],
            "transport_tick_count": len(result["transport_ticks"]),
            "assertions": result["assertions"],
        },
        metadata={
            "publication": (
                "showcase/generated/chi/issue-h-read-no-snp"
            ),
            "scope": "restricted_direct_home_read",
            "raw_waveform": False,
            "runtime_executable": True,
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
    except Exception:
        if previous.exists() and not target.exists():
            previous.replace(target)
        raise
    if previous.exists():
        shutil.rmtree(previous)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=SHOWCASE_ROOT / "generated" / "chi" / DEMO_NAME,
        help="publication directory",
    )
    args = parser.parse_args()
    target = args.output.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    _require_renderer()
    with TemporaryDirectory(
        prefix=f".{target.name}.stage-", dir=target.parent
    ) as temporary:
        staged = Path(temporary) / target.name
        _build_publication(staged)
        _publish(staged, target)
    print(f"Published CHI Issue H direct-read demo: {target}")
    print(f"Manifest: {target / 'manifest.json'}")


if __name__ == "__main__":
    main()
