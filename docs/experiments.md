# 可执行实验图册

本页把四个当前 Project 的可执行结果整理为可阅读的证据，而不是把 SVG 当作装饰。每组图都
对应一次 `out/<project>/<run-id>/manifest.json` 记录的运行；完整 JSON、约束表、HTML 报告和
源 WaveJSON/DOT 仍保留在 `out/`，但不进入 Git。本页的 SVG 是经过确认后复制的稳定快照。

阅读顺序建议是：先看网络图了解谁驱动或响应，再看波形了解各周期发生什么，最后看因果图
了解事务级依赖。`PASS` 表示该有限 trace 满足当前已经实现的规则；并不等于整个协议或真实
RTL 已被完全证明。

## 1. ready-valid：只有已握手的传输才会到达 Sink

运行：

```bash
.venv/bin/python -m protocol_model ready-valid-sink
```

这个最小 Project 连接 `ScriptedSource → DATA protocol instance → Sink`。正例包含一次
`VALID=1, READY=0` 的 stall；随后 payload 保持不变并完成握手。负例只改变 stall 中的
payload，因此应精确命中 `data.ready_valid.payload_stability`，并且 Sink 不接收该传输。

<p align="center">
  <strong>验证网络：协议 monitor 位于 Source 与 Sink 之间</strong><br>
  <img src="images/experiments/ready-valid-network.svg" alt="Ready-valid source, protocol and sink network" width="700">
</p>

<table>
  <tr>
    <td width="50%" valign="top">
      <strong>合法波形</strong><br>
      4 个 sample、2 次已接受 transfer、Sink 收到 2 项。<br>
      <img src="images/experiments/ready-valid-legal-waveform.svg" alt="Legal ready-valid waveform" width="560">
    </td>
    <td width="50%" valign="top">
      <strong>单点变异波形</strong><br>
      仅在 READY 为低时改变 payload，因此应失败。<br>
      <img src="images/experiments/ready-valid-mutation-waveform.svg" alt="Ready-valid stall payload mutation waveform" width="560">
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <strong>合法事件因果图</strong><br>
      <img src="images/experiments/ready-valid-legal-causality.svg" alt="Legal ready-valid causality" width="560">
    </td>
    <td width="50%" valign="top">
      <strong>违规事件因果图</strong><br>
      <img src="images/experiments/ready-valid-mutation-causality.svg" alt="Ready-valid mutation causality" width="560">
    </td>
  </tr>
</table>

## 2. APB3 与 APB4：两阶段传输与 wait state

运行：

```bash
.venv/bin/python -m protocol_model apb --transactions 4
```

此 Project 同时实例化 APB3 和 APB4。两者都要求每笔传输经过 SETUP 再进入 ACCESS；当
`PREADY=0` 时，ACCESS 延长但请求信号不得变化。APB4 额外检查 `PSTRB` 和 `PPROT`。
本次正例分别生成 4 笔 APB3 与 APB4 传输；负例在 APB4 ACCESS 阶段改变地址，命中
`apb4.two_phase.request_stability`。

<p align="center">
  <strong>一个 Project 中并列的 APB3/APB4 协议实例</strong><br>
  <img src="images/experiments/apb-compare-network.svg" alt="APB3 APB4 comparison network" width="720">
</p>

<table>
  <tr>
    <td width="50%" valign="top">
      <strong>APB3 波形</strong><br>
      <img src="images/experiments/apb3-waveform.svg" alt="APB3 waveform" width="620">
    </td>
    <td width="50%" valign="top">
      <strong>APB4 波形</strong><br>
      <img src="images/experiments/apb4-waveform.svg" alt="APB4 waveform" width="620">
    </td>
  </tr>
</table>

<p align="center">
  <strong>两阶段状态关系：SETUP、等待中的 ACCESS 与完成条件</strong><br>
  <img src="images/experiments/apb-compare-state.svg" alt="APB two phase state graph" width="680">
</p>

## 3. AXI4 read bridge：两条链路上的请求转发与响应返回

运行：

```bash
.venv/bin/python -m protocol_model axi-read-network
```

该 Project 使用两个命名 AXI4 实例：上游 AXI-A、下游 AXI-B。`AxiReadBridge` 是 Project
内的 VirtualDut：它接受上游 `AR`、转发下游 `AR`，再将下游 `R` beat 返回上游。另一个
responder 终止下游请求。正例为 4 beat read，共记录 10 个事件；负例构造跨越 4KB 边界的
burst，并在上游 `AR` 事件空间被拒绝，bridge 与下游链路不应开始事务。

<p align="center">
  <strong>双链路网络</strong><br>
  <img src="images/experiments/axi4-read-bridge-network.svg" alt="AXI4 read bridge network" width="900">
</p>

<p align="center">
  <strong>请求、转发与 read-data 返回的因果链</strong><br>
  <img src="images/experiments/axi4-read-bridge-causality.svg" alt="AXI4 read bridge causality" width="900">
</p>

<table>
  <tr>
    <td width="50%" valign="top">
      <strong>AXI-A：上游观察</strong><br>
      <img src="images/experiments/axi4-read-bridge-axi-a-waveform.svg" alt="Upstream AXI-A waveform" width="650">
    </td>
    <td width="50%" valign="top">
      <strong>AXI-B：下游观察</strong><br>
      <img src="images/experiments/axi4-read-bridge-axi-b-waveform.svg" alt="Downstream AXI-B waveform" width="650">
    </td>
  </tr>
</table>

## 4. AXI4 cross-ID read interleave：协议基础与 Project profile 分开

运行：

```bash
.venv/bin/python -m protocol_model axi-read-interleave
```

该 Project 从通用 AXI4 派生 read-only profile，并将 active read ID 限定为 1、2；未使用的
AR sideband 固定为零，AW/W/B 通道保持 quiet。输入 VirtualDut 依次发出 `AR(1)`、`AR(2)`；
输出 VirtualDut 交替发出 `R(2)`、`R(1)`，因此不同 ID 可以交织，且 ID2 可以先完成。

四个负例分别确认：同 ID 不得越序、RID 必须在 active set、ARCACHE 必须为零、AWVALID
必须保持低。这些是可追溯的 profile/协议规则，而不是隐藏在 stimulus 中的假设。

<p align="center">
  <strong>两个 VirtualDut 与派生 AXI4 profile</strong><br>
  <img src="images/experiments/axi4-read-interleave-network.svg" alt="AXI4 interleave network" width="820">
</p>

<table>
  <tr>
    <td width="52%" valign="top">
      <strong>短 trace 波形：2 个 AR 与 4 个交织 R beat</strong><br>
      <img src="images/experiments/axi4-read-interleave-waveform.svg" alt="Short AXI4 cross ID interleave waveform" width="700">
    </td>
    <td width="48%" valign="top">
      <strong>因果图</strong><br>
      每个 AR 仅约束自己的 R beat 序列；不同 ID 的 beat 没有额外先后边。<br>
      <img src="images/experiments/axi4-read-interleave-causality.svg" alt="AXI4 cross ID interleave causality" width="620">
    </td>
  </tr>
</table>

## 5. 长 trace：两笔 16-beat 读取的交织

运行：

```bash
.venv/bin/python -m protocol_model axi-read-interleave --beats 16 \
  --sim-dir out/prj_axi4_read_interleave/long
```

这不是另一套协议：它复用上一节相同的 AXI4 profile 和 VirtualDut，只将每笔请求扩展为
16 个 R beat。该运行包含 2 个 `AR` 与 32 个 `R`，共 **34 个规范事件**，最终为 `PASS`。
波形中可观察到：每个 ID 内的 beat 次序保持，而 ID1/ID2 的 R beat 交替；ID2 的最后一拍
先出现，因此它先完成。这个例子用来展示模型对较长有限 trace 的 obligation 与因果处理，
不应被解读为吞吐率或时序性能测量。

<p align="center">
  <strong>34-event AXI4 cross-ID interleaving trace（每笔 16 beat）</strong><br>
  <img src="images/experiments/axi4-read-interleave-long-waveform.svg" alt="Long AXI4 cross ID interleave waveform with two sixteen beat reads" width="1100">
</p>
