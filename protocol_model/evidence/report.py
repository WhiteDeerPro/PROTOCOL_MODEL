"""Self-contained browser report for one generated protocol session."""

from __future__ import annotations

from html import escape

from protocol_model.protocols.spec import ProtocolSpec


def session_report_html(
    spec: ProtocolSpec,
    *,
    event_count: int,
    edge_count: int,
    cycle_count: int,
    step_count: int,
    max_parallel: int,
    replay_verdict: str,
) -> str:
    requirement_rows = []
    for item in spec.requirements:
        css = "done" if item.status == "implemented" else "missing"
        requirement_rows.append(
            "<tr>"
            f"<td>{escape(item.name)}</td>"
            f"<td>{escape(item.rule)}</td>"
            f"<td><code>{escape(item.foundation)}</code></td>"
            f'<td><span class="badge {css}">{escape(item.status)}</span></td>'
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AXI4 Protocol Model Session</title>
  <style>
    :root {{ color-scheme: light dark; font-family: Inter, system-ui, sans-serif; }}
    body {{ max-width: 1500px; margin: 0 auto; padding: 24px; background: #10141c; color: #e8edf5; }}
    h1, h2 {{ margin-bottom: 8px; }}
    .muted {{ color: #9ba8ba; }}
    .cards {{ display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }}
    .card, section {{ background: #181f2b; border: 1px solid #2d3849; border-radius: 10px; padding: 16px; }}
    .card strong {{ display: block; font-size: 1.6rem; color: #8bd5ff; }}
    section {{ margin: 16px 0; }}
    object {{ width: 100%; min-height: 1500px; background: white; border-radius: 6px; }}
    .wave-scroll {{ overflow-x: auto; padding-bottom: 8px; }}
    .wave-scroll object {{ width: 3200px; max-width: none; }}
    .graph object {{ min-height: 520px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
    th, td {{ text-align: left; vertical-align: top; padding: 9px; border-bottom: 1px solid #303b4b; }}
    code {{ color: #f5c2e7; }}
    .badge {{ border-radius: 999px; padding: 3px 8px; font-weight: 650; }}
    .done {{ background: #194d36; color: #9be9bd; }}
    .missing {{ background: #5b2c31; color: #ffb1ba; }}
    .pipeline {{ font-family: ui-monospace, monospace; line-height: 1.8; }}
    @media (max-width: 800px) {{ .cards {{ grid-template-columns: 1fr 1fr; }} }}
  </style>
</head>
<body>
  <h1>AXI4 Protocol Model：可执行语义快照</h1>
  <p class="muted">这是一条 constructive legal subset 的 witness，不宣称覆盖完整 AXI4 状态空间。</p>
  <div class="cards">
    <div class="card"><strong>{event_count}</strong>canonical events</div>
    <div class="card"><strong>{cycle_count}</strong>waveform cycles</div>
    <div class="card"><strong>{step_count}</strong>concurrent steps</div>
    <div class="card"><strong>{max_parallel}</strong>max events / step</div>
    <div class="card"><strong>{edge_count}</strong>causal edges</div>
    <div class="card"><strong>{escape(replay_verdict)}</strong>waveform replay</div>
  </div>
  <section>
    <h2>约束层</h2>
    <table><thead><tr><th>层</th><th>语义</th><th>当前AXI对象</th><th>是否属于时序</th></tr></thead><tbody>
      <tr><td>L0</td><td>字段类型、位宽、枚举、burst几何</td><td>ValueDomain / EventSpace</td><td>否</td></tr>
      <tr><td>L1</td><td>时钟边沿、reset、handshake、stall稳定、VALID前置条件</td><td>ResetEpoch / ClockedReadyValid / Axi4SignalSession</td><td><strong>是：通信时序从这里开始</strong></td></tr>
      <tr><td>L2</td><td>跨channel事务义务与必要先后</td><td>CardinalityObligation / AW-W join / B-R token</td><td>因果时序，不是固定延迟</td></tr>
      <tr><td>L3</td><td>同周期并发与事件交换</td><td>ProtocolSession dynamic commutation / pomset step</td><td>并发时序</td></tr>
      <tr><td>L4</td><td>deadline、最大响应周期、公平性</td><td>尚无；AXI本身通常不给固定响应延迟</td><td>定量时序，未建模</td></tr>
    </tbody></table>
  </section>
  <section>
    <h2>五通道波形</h2>
    <p class="muted">ARESETn 为 AXI 低有效复位；FIRE = VALID ∧ READY ∧ ARESETn。PAYLOAD 在 stall 周期保持。</p>
    <div class="wave-scroll"><object data="axi4_session.wave.svg" type="image/svg+xml"></object></div>
  </section>
  <section class="graph">
    <h2>必要因果关系</h2>
    <p class="muted">边表示协议必要依赖，不表示 Python 日志的偶然先后。</p>
    <object data="axi4_session.causality.svg" type="image/svg+xml"></object>
  </section>
  <section>
    <h2>需求实现状态</h2>
    <table><thead><tr><th>Requirement</th><th>Rule</th><th>Foundation</th><th>Status</th></tr></thead>
    <tbody>{''.join(requirement_rows)}</tbody></table>
  </section>
  <section>
    <h2>当前明确缺口</h2>
    <ul>
      <li>并发目前由有限 diamond/commutation 检查动态判定，尚未形成可查询的静态 IndependenceRelation。</li>
      <li>exclusive access、USER signals、endpoint capability 和 outstanding 上限。</li>
      <li>burst beat address 已用于 byte-lane/WSTRB 判定，但尚未作为独立 evidence lane 展示。</li>
      <li>VALID 对 READY 的策略独立性、无组合路径等 structural evidence。</li>
      <li>公平性和无界 eventual progress；随机 PASS 不能证明 liveness。</li>
    </ul>
  </section>
</body>
</html>
"""
