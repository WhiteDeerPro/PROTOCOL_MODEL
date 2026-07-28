"""Markdown presentation for the executable CHI Issue H flow gallery."""

from __future__ import annotations

from collections.abc import Mapping

from showcase.demos.chi.issue_h_flow_gallery.model import FlowGalleryCase


def guide(
    cases: Mapping[str, FlowGalleryCase],
    result: Mapping[str, object],
) -> str:
    """Build the publication index from the same executed case set."""

    lines = [
        "# CHI Issue H executable flow gallery",
        "",
        "每个具名案例分别执行一次模型；该案例的四种互相链接"
        "视图均由这次案例执行投影：",
        "",
        "1. **topology / participant boundary**：前四案画 resolved "
        "SystemProtocol 的真实连接，WriteBackFull 案只画实际 packet "
        "交互边界；",
        "2. **transaction time-space**：参与者、已接收消息和"
        "可见状态变化；",
        "3. **explicit causality**：只画模型产出、correlation、fan-out/join、"
        "Retry 或同址干涉所提供的因果边；",
        "4. **semantic event timeline**：按 `model_step` 排列相同事件引用，"
        "用于快速对照，不是 pin/cycle/RTL 波形。",
        "",
        f"本次执行结论：**{result['verdict']}**；"
        f"{result['case_count']} 个具名场景。",
        "",
        "## 场景导航",
        "",
        "| 场景 | 主要问题 | 四视图 |",
        "|---|---|---|",
    ]
    for case in cases.values():
        root = f"cases/{case.case_id}"
        lines.append(
            f"| `{case.case_id}` | {case.learning_goal} | "
            f"[拓扑/边界]({root}/topology.svg) · "
            f"[时空]({root}/transaction-time-space.svg) · "
            f"[因果]({root}/causal.svg) · "
            f"[语义时间线]({root}/semantic-event-timeline.svg) |"
        )

    lines.extend(
        (
            "",
            "## 怎样核对",
            "",
            "每个消息和状态变化都有稳定 `event_ref`；三个事件视图 "
            "SVG 以及 "
            "`sources/cases/<case>/transaction-time-space-view.json` "
            "使用同一组引用。DOT 与 WaveJSON 也保留在 `sources/`，因此"
            "可以区分模型事实、协议专用投影和最终排版。",
            "",
        )
    )
    for case in cases.values():
        case_result = result["cases"][case.case_id]
        lines.extend(
            (
                f"### {case.title}",
                "",
                f"![{case.title} topology or participant boundary]"
                f"(cases/{case.case_id}/topology.svg)",
                "",
                f"![{case.title} transaction time-space]"
                f"(cases/{case.case_id}/transaction-time-space.svg)",
                "",
                f"- 执行 verdict：`{case_result['verdict']}`；"
                f"{case_result['message_count']} 个已接收消息，"
                f"{case_result['state_change_count']} 个可见状态变化，"
                f"{case_result['causal_edge_count']} 条显式因果边。",
                f"- 学习目标：{case.learning_goal}",
                f"- 边界：{case.model_boundary}",
                "",
            )
        )

    lines.extend(
        (
            "## 能说明与不能说明的内容",
            "",
            "- 这些 case 证明相应 CHI lifecycle、participant state、"
            "correlation 和选定组合在当前模型中可执行；",
            "- 它们不把参考资料中的每个 flow 都冒充成已实现功能，"
            "也不由示例数量推断规范覆盖率；",
            "- `model_step` 是离散语义提交顺序。图中没有 packed "
            "pin/phit、物理时延、CDC 或 RTL sampling；",
            "- 当前四个 resolved flow 都是 direct topology，没有构造 "
            "XP/router。若案例实际提供 forwarding binding，拓扑会将其显示为 "
            "`routing forwarder (XP abstraction)`；",
            "- 时空图过滤逐 hop transport `MOVE`；原 `model_step` 标签的"
            "间隔只保留模型提交次序线索，不是 XP 周期延迟；",
            "- WriteBackFull 案的包交付顺序与延后交付由 scenario "
            "显式编排；它没有建模网络时延或 transport hop。包和状态转移"
            "仍来自生产 participant runtime；",
            "- 其余四案通过 resolved direct topology 与 "
            "coherence-network scheduler；",
            "- 因而最后一案的虚线图只证明 participant 间实际 packet "
            "交互，不把它提升为已构造、已执行的 transport hop。",
            "",
            "机器结果见 [result.json](result.json)，生成边界见"
            " [provenance.json](provenance.json)，全部资产清单见"
            " [manifest.json](manifest.json)。",
            "",
        )
    )
    return "\n".join(lines)


__all__ = ["guide"]
