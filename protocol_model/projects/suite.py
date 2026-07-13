"""Run the maintained experiment suite and publish a browser index."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

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


@dataclass(frozen=True)
class ExperimentSuite:
    directory: Path
    index: Path
    entries: tuple[SuiteEntry, ...]


def _default_out() -> Path:
    return Path(__file__).resolve().parents[2] / "out"


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
        ),
        SuiteEntry("prj_apb_compare", apb.report, apb.run.verdict.value),
        SuiteEntry(
            "prj_axi4_read_bridge",
            bridge.report,
            "PASS" if bridge.legal.verdict.value == "PASS" and bridge.rejected.fault else "FAIL",
        ),
        SuiteEntry(
            "prj_axi4_read_interleave",
            interleave.report,
            interleave.run.verdict.value,
        ),
        SuiteEntry(
            "prj_axi4_scenarios",
            scenarios.report,
            scenarios.run.verdict.value,
        ),
    )
    rows = "".join(
        "<tr>"
        f"<td><code>{escape(item.project)}</code></td>"
        f"<td>{escape(item.verdict)}</td>"
        f'<td><a href="{escape(item.report.relative_to(root).as_posix())}">open report</a></td>'
        "</tr>"
        for item in entries
    )
    index = root / "index.html"
    index.write_text(
        f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>Protocol Model experiment suite</title><style>
body{{font-family:system-ui;max-width:1000px;margin:40px auto;padding:0 20px;background:#f8fafc;color:#0f172a}}
table{{border-collapse:collapse;width:100%;background:white}}td,th{{padding:12px;border:1px solid #cbd5e1;text-align:left}}
code{{color:#7c3aed}}
</style></head><body><h1>Protocol Model 实验入口</h1>
<p>一次 suite 运行；每个 Project 是一个 run bundle，每个 bundle 内含 legal/negative cases。</p>
<table><tr><th>Project</th><th>Verdict</th><th>Report</th></tr>{rows}</table>
</body></html>""",
        encoding="utf-8",
    )
    return ExperimentSuite(root, index, entries)
