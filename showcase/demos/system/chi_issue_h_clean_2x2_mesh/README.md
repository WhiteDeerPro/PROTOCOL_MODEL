# CHI Issue H：Clean ReadUnique 经过 2×2 XP mesh

这个示例把当前 CHI clean-coherence runtime 放进一个最小的有环网络。四个 XP 位于正方形四角，
相邻 XP 之间具有两个方向的 transport connection；一个 requester、一个 Home 和两个 snoopee
分别挂在四角。它们共同完成一笔 `ReadUnique`：

```text
 RN0/requester ── XP00 ═════════ XP10 ── RN1/snoopee
                   ║               ║
                   ║               ║
 RN2/snoopee  ── XP01 ═════════ XP11 ── HN0/Home
```

REQ、两路 SNP、两路 SnpResp、DAT 与 CompAck 选择不同的确定性路径。一次事务生命周期因此会经过
正方形的四条边；这个例子展示“拓扑中存在环且数据确实经过它”，而不是只把四个方框摆成环形。

## 运行

写入具名的默认发布目录：

```bash
.venv/bin/python \
  showcase/demos/system/chi_issue_h_clean_2x2_mesh/run.py
```

开发或复核时可以发布到临时目录：

```bash
.venv/bin/python \
  showcase/demos/system/chi_issue_h_clean_2x2_mesh/run.py \
  --publish-root /tmp/protocol-model-chi-mesh
```

脚本先在目标目录旁建立 staging tree。场景执行、三张图渲染和 manifest 构造均完成后，才原子替换
`chi-issue-h-clean-2x2-mesh/`。

## 生成内容

- `topology.svg`：四个 XP、四个参与节点和实际 transport connection；固定四角位置使环保持可读；
- `transaction-sequence.svg`：在参与节点层面投影 ReadUnique、SNP、RSP、DAT 与 CompAck 的因果顺序，
  并保留实际 XP 路径作为注释；
- `coherence-state.svg`：请求前后的 clean coherence 状态与 Home authority 变化；
- `result.json`：场景执行结果、packet 路径、状态和断言；
- `README.md`：与本次执行结果对应的导航说明；
- `provenance.json`：构造入口、时间基准、renderer 和能力边界；
- `sources/*.dot`：三张 SVG 的可检查 Graphviz 源；
- `manifest.json`：产物、协议切面、case、状态摘要和运行结论。

这些图是事务、packet 路径与 coherence 状态的模型级投影。它们**不是 raw pin waveform**，也不要求
RTL 使用相同的周期距离、空拍位置或内部流水级数。

## 场景说明

初始时，RN1 与 RN2 持有同一 cache line 的 clean shared copy，RN0 没有该 line，Home 记录两个
sharer。RN0 发出 `ReadUnique` 后：

1. REQ 经 XP00、XP10、XP11 到达 Home；
2. Home 向 RN1 与 RN2 发出 `SnpUnique`；
3. 两个 clean sharer 返回 `SnpResp` 并转为 Invalid；
4. Home 向 RN0 返回 `CompData`；
5. RN0 发送 `CompAck`，事务资源关闭；
6. 最终 RN0 为 clean unique owner，RN1/RN2 为 Invalid。

这里的 mesh 由调用方通过 system topology 组装；CHI package 没有把 2×2 固定成协议内建拓扑。
XP 执行逐跳存储转发和确定性 route，coherence session 管理跨参与节点的事务阶段与状态闭合。

## 这个示例覆盖什么

本例集中展示：

- 2×2 XP square mesh 的端口、方向、connection ownership 和 route 闭合；
- REQ/RSP/SNP/DAT 四类 transport channel 在多跳路径上的传播；
- 一对多 snoop fan-out 在有限发送容量下分批提交；
- transaction、message/packet 与逐跳 transport 的职责边界；
- clean-only `I/SC/UC` 状态变化以及 Home 的 sharer/unique-owner 记录；
- 整个场景完成后 packet、credit、pending batch 与参与节点状态的收束。

当前边界是 clean `ReadUnique` 的可执行证据。它还不表示完整 CHI compliance，也不包含 dirty owner、
完整 MESI/MOESI、任意自适应路由、router QoS/fairness 或网络 deadlock proof。拓扑中的环使后续
wait-for/deadlock 分析有了真实结构，但这张图本身不构成相关证明。

## 文件职责

- `model.py` 组装实际 system topology、participants 与 session，并执行场景；
- `presentation.py` 只把执行结果投影成三张易读的图和生成版说明；
- `run.py` 管理显式 staging、渲染、provenance、manifest 与发布。

协议、participant、transport 和 coherence runtime 的实现仍位于
`protocol_model/protocols/amba/chi/issue_h/`；本目录不复制这些规则。
