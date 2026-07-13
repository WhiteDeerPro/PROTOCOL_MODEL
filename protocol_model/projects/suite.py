"""Run the maintained experiment suite and publish a browser index."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import shutil

from .prj_apb_compare import build_simulation as build_apb
from .prj_axi4_read_bridge import build_simulation as build_axi_bridge
from .prj_axi4_read_interleave import build_simulation as build_axi_interleave
from .prj_axi4_scenarios import build_simulation as build_axi_scenarios
from .prj_ready_valid_sink import build_simulation as build_ready_valid


@dataclass(frozen=True)
class SuiteEntry:
    project: str
    report: Path
    verdict: str
    summary: str


@dataclass(frozen=True)
class ExperimentSuite:
    directory: Path
    index: Path
    entries: tuple[SuiteEntry, ...]


def _default_out() -> Path:
    return Path(__file__).resolve().parents[2] / "out"


def _label(kind: str, path: str) -> str:
    labels = {
        "network": "Project 组网",
        "state": "协议状态图",
        "waveform": "波形图",
        "waveform_axi-a": "AXI-A 波形图",
        "waveform_axi-b": "AXI-B 波形图",
        "causality": "因果事件图",
    }
    return labels.get(kind, kind.replace("_", " ")) + f" · {Path(path).name}"


def _figure(root: Path, project_root: Path, artifact: dict) -> str:
    path = project_root / artifact["path"]
    source = path.relative_to(root).as_posix()
    kind = str(artifact["kind"])
    causal = " causality" if kind == "causality" else ""
    return (
        f'<figure class="figure{causal}"><figcaption>{escape(_label(kind, artifact["path"]))}</figcaption>'
        f'<div class="frame"><object data="{escape(source)}" type="image/svg+xml"></object></div></figure>'
    )


def _project_section(root: Path, entry: SuiteEntry) -> tuple[str, int]:
    project_root = entry.report.parent
    manifest = json.loads((project_root / "manifest.json").read_text(encoding="utf-8"))
    artifacts = [
        item
        for item in manifest["artifacts"]
        if item["media_type"] == "image/svg+xml"
    ]
    root_figures = "".join(
        _figure(root, project_root, item)
        for item in artifacts
        if item.get("case") is None
    )
    case_sections = []
    for case in manifest["cases"]:
        name = str(case["name"])
        expected = escape(str(case.get("expected", "-")))
        observed = escape(str(case.get("observed", "-")))
        description = escape(str(case.get("description", case.get("detail", name))))
        figures = "".join(
            _figure(root, project_root, item)
            for item in artifacts
            if item.get("case") == name
        )
        case_sections.append(
            f'<section class="case"><h3><code>{escape(name)}</code></h3>'
            f'<p>{description}</p><p class="result">Expected {expected} · Observed {observed}</p>'
            f'<div class="gallery">{figures}</div></section>'
        )
    report_link = f' · <a href="{escape(entry.report.relative_to(root).as_posix())}">打开独立报告</a>'
    return (
        f'<article id="{escape(entry.project)}"><h2>{escape(entry.project)}</h2>'
        f'<p>{escape(entry.summary)}</p><p><strong>{escape(entry.verdict)}</strong> · '
        f'{len(manifest["cases"])} cases{report_link}</p>'
        f'<div class="gallery project-figures">{root_figures}</div>{"".join(case_sections)}</article>',
        len(manifest["cases"]),
    )


def _markdown_figure(
    docs_root: Path, assets_root: Path, project_root: Path, project: str, artifact: dict
) -> str:
    source = project_root / artifact["path"]
    target = assets_root / project / artifact["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    label = _label(str(artifact["kind"]), artifact["path"])
    relative = target.relative_to(docs_root).as_posix()
    return f"#### {label}\n\n![{label}]({relative})\n"


def _project_markdown(
    docs_root: Path, assets_root: Path, entry: SuiteEntry
) -> tuple[str, int]:
    project_root = entry.report.parent
    manifest = json.loads((project_root / "manifest.json").read_text(encoding="utf-8"))
    artifacts = [
        item
        for item in manifest["artifacts"]
        if item["media_type"] == "image/svg+xml"
    ]
    lines = [
        f"## `{entry.project}`",
        "",
        entry.summary,
        "",
        f"结果：**{entry.verdict}**；{len(manifest['cases'])} 个 case。",
        "",
    ]
    root_figures = [item for item in artifacts if item.get("case") is None]
    if root_figures:
        lines.extend(("### Project 图", ""))
        lines.extend(
            _markdown_figure(docs_root, assets_root, project_root, entry.project, item)
            for item in root_figures
        )
    for case in manifest["cases"]:
        name = str(case["name"])
        description = str(case.get("description", case.get("detail", name)))
        expected = str(case.get("expected", "-"))
        observed = str(case.get("observed", "-"))
        lines.extend(
            (
                f"### `{name}`",
                "",
                description,
                "",
                f"预期：`{expected}`；观察到：`{observed}`。",
                "",
            )
        )
        lines.extend(
            _markdown_figure(docs_root, assets_root, project_root, entry.project, item)
            for item in artifacts
            if item.get("case") == name
        )
    return "\n".join(lines), len(manifest["cases"])


def run_suite(
    directory: str | Path | None = None, *, run_id: str = "01"
) -> ExperimentSuite:
    root = _default_out() if directory is None else Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    ready = build_ready_valid(root / "prj_ready_valid_sink" / run_id)
    apb = build_apb(root / "prj_apb_compare" / run_id)
    bridge = build_axi_bridge(root / "prj_axi4_read_bridge" / run_id)
    interleave = build_axi_interleave(root / "prj_axi4_read_interleave" / run_id)
    scenarios = build_axi_scenarios(root / "prj_axi4_scenarios" / run_id)
    entries = (
        SuiteEntry(
            "prj_ready_valid_sink",
            ready.report,
            "PASS"
            if ready.legal.verdict.value == "PASS" and ready.mutation.fault
            else "FAIL",
            "最小 ready-valid 链路：握手、stall 与 payload stability。",
        ),
        SuiteEntry(
            "prj_apb_compare",
            apb.report,
            apb.run.verdict.value,
            "APB3/APB4 两阶段传输、wait state 与请求保持。",
        ),
        SuiteEntry(
            "prj_axi4_read_bridge",
            bridge.report,
            "PASS" if bridge.legal.verdict.value == "PASS" and bridge.rejected.fault else "FAIL",
            "两个 AXI4 实例之间的 read bridge、转发因果与 4KB 拒绝。",
        ),
        SuiteEntry(
            "prj_axi4_read_interleave",
            interleave.report,
            interleave.run.verdict.value,
            "跨 ID read-data 交织、同 ID 顺序与 Project profile。",
        ),
        SuiteEntry(
            "prj_axi4_scenarios",
            scenarios.report,
            scenarios.run.verdict.value,
            "无 bridge 的 AXI4 source/responder 批量场景，覆盖五通道事务、并发、ordering 与 reset。",
        ),
    )
    project_sections = []
    case_counts = {}
    for item in entries:
        section, count = _project_section(root, item)
        project_sections.append(section)
        case_counts[item.project] = count
    rows = "".join(
        "<tr>"
        f"<td><code>{escape(item.project)}</code></td>"
        f"<td>{escape(item.summary)}</td>"
        f"<td>{case_counts[item.project]}</td>"
        f"<td>{escape(item.verdict)}</td>"
        f'<td><a href="#{escape(item.project)}">查看图表</a></td>'
        "</tr>"
        for item in entries
    )
    def document(title: str, sections: str) -> str:
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>{title}</title><style>
:root{{color-scheme:light}}*{{box-sizing:border-box}}body{{font-family:system-ui;max-width:1500px;margin:36px auto;padding:0 24px;background:#f8fafc;color:#0f172a;line-height:1.55}}
h1,h2,h3{{scroll-margin-top:18px}}article{{margin:52px 0;padding-top:12px;border-top:3px solid #334155}}.case{{margin:32px 0;padding:18px;background:#fff;border:1px solid #cbd5e1;border-radius:10px}}
table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:10px;border:1px solid #cbd5e1;text-align:left}}code{{color:#7c3aed}}a{{color:#0369a1}}
.gallery{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}}figure{{margin:0;min-width:0}}figcaption{{font-weight:650;margin-bottom:7px}}
.frame{{width:100%;min-height:300px;background:#fff;border:1px solid #cbd5e1;overflow:auto}}.frame object{{width:100%;height:100%;min-height:420px}}
.causality .frame{{min-height:560px}}.causality object{{min-height:560px}}
.result{{color:#475569}}@media(max-width:900px){{.gallery{{grid-template-columns:1fr}}}}
</style></head><body><h1>Protocol Model Project 功能导览</h1>
<p>五个内建 Project 由简单到复杂排列。每个 case 同时展示采样层波形与事务层因果事件图；负例的预期结果为 FAIL，表示相应约束被成功触发。</p>
<table><tr><th>Project</th><th>测试内容</th><th>Cases</th><th>结果</th><th>图表</th></tr>{rows}</table>
{sections}
</body></html>"""

    index = root / "index.html"
    index.write_text(document("Protocol Model Project 功能导览", "".join(project_sections)), encoding="utf-8")
    repository = Path(__file__).resolve().parents[2]
    docs_root = repository / "docs"
    assets_root = docs_root / "project-guide-assets"
    if assets_root.exists():
        shutil.rmtree(assets_root)
    assets_root.mkdir()
    guide_sections = []
    for item in entries:
        section, _ = _project_markdown(docs_root, assets_root, item)
        guide_sections.append(section)
    guide_header = "\n".join(
        (
            "# Protocol Model Project 功能导览",
            "",
            "五个内建 Project 按简单到复杂排列。每个 case 的波形图与因果事件图均由同一次 `run-all` 生成。",
            "负例的预期结果为 `FAIL`，表示对应约束被成功触发。",
            "",
            "| Project | 测试内容 | Cases | 结果 |",
            "|---|---|---:|---|",
            *(
                f"| `{item.project}` | {item.summary} | {case_counts[item.project]} | {item.verdict} |"
                for item in entries
            ),
            "",
        )
    )
    (docs_root / "project-guide.md").write_text(
        guide_header + "\n\n".join(guide_sections), encoding="utf-8"
    )
    (docs_root / "project-guide.html").unlink(missing_ok=True)
    return ExperimentSuite(root, index, entries)
