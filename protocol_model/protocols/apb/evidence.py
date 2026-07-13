"""WaveDrom and browser views for APB3/APB4 traces."""

from __future__ import annotations

from html import escape

from .generator import ApbGeneratedTrace
from .spec import ApbConfig, ApbPinSample


def _bit_wave(values) -> str:
    result = []
    previous = None
    for value in values:
        symbol = "1" if value else "0"
        result.append("." if symbol == previous else symbol)
        previous = symbol
    return "".join(result)


def _short_hex(value: int, width: int) -> str:
    raw = format(value, f"0{(width + 3) // 4}x")
    shown = f"{raw[:2]}..{raw[-2:]}" if len(raw) > 4 else raw
    return f"0x{shown} '{width}"


def _bus_lane(samples, getter, active, formatter):
    wave = []
    data = []
    unset = object()
    previous = unset
    for sample in samples:
        if not active(sample):
            wave.append("." if wave else "0")
            continue
        value = getter(sample)
        if previous is not unset and value == previous:
            wave.append(".")
        else:
            wave.append("=")
            data.append(formatter(value))
        previous = value
    return {"wave": "".join(wave), "data": data}


def _phase(sample: ApbPinSample) -> str:
    if not sample.presetn:
        return "RESET"
    if not sample.psel:
        return "IDLE"
    if not sample.penable:
        return "SETUP"
    if not sample.pready:
        return "WAIT"
    return "COMPLETE"


def apb_to_wavejson(config: ApbConfig, trace: ApbGeneratedTrace):
    samples = trace.samples
    active_request = lambda sample: sample.psel
    active_read_data = lambda sample: (
        sample.psel and sample.penable and sample.pready and not sample.pwrite
    )
    phase = _bus_lane(samples, _phase, lambda sample: True, str)
    addr = _bus_lane(
        samples,
        lambda sample: sample.paddr,
        active_request,
        lambda value: _short_hex(value, config.address_width),
    )
    wdata = _bus_lane(
        samples,
        lambda sample: sample.pwdata,
        lambda sample: sample.psel and sample.pwrite,
        lambda value: _short_hex(value, config.data_width),
    )
    rdata = _bus_lane(
        samples,
        lambda sample: sample.prdata,
        active_read_data,
        lambda value: _short_hex(value, config.data_width),
    )
    signals = [
        {"name": "PCLK", "wave": "p" + "." * max(0, len(samples) - 1)},
        {"name": "PRESETn", "wave": _bit_wave(sample.presetn for sample in samples)},
        {"name": "PHASE", **phase},
        {},
        {"name": "PSEL", "wave": _bit_wave(sample.psel for sample in samples)},
        {"name": "PENABLE", "wave": _bit_wave(sample.penable for sample in samples)},
        {"name": "PREADY", "wave": _bit_wave(sample.pready for sample in samples)},
        {"name": "PWRITE", "wave": _bit_wave(sample.pwrite for sample in samples)},
        {"name": "PADDR", **addr},
        {"name": "PWDATA", **wdata},
        {"name": "PRDATA", **rdata},
        {"name": "PSLVERR", "wave": _bit_wave(sample.pslverr for sample in samples)},
    ]
    if config.version == 4:
        strb = _bus_lane(
            samples,
            lambda sample: sample.pstrb,
            active_request,
            lambda value: f"0x{value:x}",
        )
        prot = _bus_lane(
            samples,
            lambda sample: sample.pprot,
            active_request,
            lambda value: f"{value:03b}",
        )
        signals.extend(
            (
                {"name": "PSTRB", **strb},
                {"name": "PPROT", **prot},
            )
        )
    return {
        "signal": signals,
        "head": {"text": f"APB{config.version} two-phase transfers", "tick": 0},
        "config": {"hscale": 3},
    }


def apb_state_dot() -> str:
    return """digraph apb_state {
  rankdir=LR;
  graph [nodesep=0.5, ranksep=0.7];
  node [shape=circle, fontname="monospace"];
  IDLE -> SETUP [label="PSEL && !PENABLE"];
  SETUP -> ACCESS [label="next cycle: PENABLE"];
  ACCESS -> ACCESS [label="!PREADY / hold request"];
  ACCESS -> IDLE [label="PREADY / complete"];
  ACCESS -> SETUP [label="PREADY / back-to-back"];
  IDLE -> IDLE [label="!PSEL"];
}
"""


def apb_report_html(
    *, apb3_cycles: int, apb4_cycles: int, transactions: int, violation: str
) -> str:
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>APB3 / APB4 Model</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1500px;margin:auto;padding:24px;background:#10141c;color:#e8edf5}}
section{{background:#181f2b;border:1px solid #2d3849;border-radius:10px;padding:16px;margin:16px 0;overflow:auto}}
object{{background:white;border-radius:6px;width:2200px;min-height:500px}}
.state object{{width:100%;min-height:340px}} table{{border-collapse:collapse;width:100%}}td,th{{padding:9px;border-bottom:1px solid #344054;text-align:left}}
code{{color:#f5c2e7}} .ok{{color:#9be9bd}}
</style></head><body>
<h1>APB3 / APB4 可执行协议模型</h1>
<p>每版 {transactions} 个 transfer；APB3 {apb3_cycles} cycles，APB4 {apb4_cycles} cycles。</p>
<section><h2>版本差异</h2><table><tr><th>版本</th><th>基础行为</th><th>新增信号</th></tr>
<tr><td>APB3</td><td>SETUP/ACCESS、PREADY wait、PSLVERR</td><td>相对 APB2：PREADY、PSLVERR</td></tr>
<tr><td>APB4</td><td>继承 APB3</td><td>PSTRB、PPROT</td></tr></table></section>
<section><h2>约束层</h2><table><tr><th>层</th><th>APB语义</th><th>是否属于时序</th></tr>
<tr><td>L0</td><td>地址/数据位宽、APB3/4信号集合</td><td>否</td></tr>
<tr><td>L1</td><td>SETUP下一周期进入ACCESS；PREADY低时保持请求</td><td><strong>是：通信时序从这里开始</strong></td></tr>
<tr><td>L2</td><td>PSEL &amp;&amp; PENABLE &amp;&amp; PREADY产生canonical transfer</td><td>完成事件投影</td></tr>
<tr><td>L3</td><td>外设响应延迟上限、timeout、公平性</td><td>系统策略，当前不约束</td></tr>
</table></section>
<section><h2>APB3 WaveDrom</h2><object data="waveform.apb3.svg" type="image/svg+xml"></object></section>
<section><h2>APB4 WaveDrom</h2><object data="waveform.apb4.svg" type="image/svg+xml"></object></section>
<section class="state"><h2>共享自动机</h2><object data="state.svg" type="image/svg+xml"></object></section>
<section><h2>最小 violation witness</h2><p>要求：SETUP 到完成之间请求字段保持。</p>
<p>Mutation：ACCESS 周期修改 PADDR。</p><p class="ok">Observed: <code>{escape(violation)}</code></p></section>
</body></html>"""
