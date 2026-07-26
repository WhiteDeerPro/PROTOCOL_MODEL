# CHI Issue H：两级 XP 路由读取示例

这个示例展示项目怎样从一个协议事务扩展到调用方声明的 transport 网络：RN-I 发出受限
`ReadNoSnp`，REQ 依次经过两个 store-and-forward XP 到达 I/O Home；Home 返回单个 `CompData`，DAT
沿独立的反向路径经过同样两个 XP，最终关闭 RN-I 的 outstanding transaction。

```text
sensor_reader_rn (NodeID 0x07)
       ──REQ──> xp0 ──REQ──> xp1 ──REQ──> sensor_io_home (NodeID 0x21)
       <─DAT─── xp0 <─DAT─── xp1 <─DAT───
```

这里的拓扑不是 CHI package 中固化的 fixture。`model.py` 使用 `SystemProtocolBuilder`、四个
`VirtualDut`、六条 `DirectedTransportConnection` 和具体 `TransportPort` 组装它；
`ChiReadNoSnpSystemSession` 再从 elaborated transport plan 解析正向与返回路径。

## 运行

写入默认发布目录：

```bash
.venv/bin/python showcase/demos/system/chi_issue_h_routed_read/run.py
```

开发或复核时可以指定临时目录，不改写仓库发布材料：

```bash
.venv/bin/python showcase/demos/system/chi_issue_h_routed_read/run.py \
  --publish-root /tmp/protocol-model-chi-routed-read
```

脚本先在目标目录旁建立 staging tree，全部执行、渲染和 manifest 构造成功后才替换目标。

## 生成内容

- `topology.svg`：由公共 `system_topology_dot()` 从实际 `SystemProtocol` 自动投影；
- `transaction-path.svg`：REQ、Home service 和反向 DAT 的模型级路径；
- `lineage.svg`：从 completion 实际携带的 lineage 标签生成的因果 custody 链；
- `result.json`：节点、连接、路由、事件、响应和断言；
- `provenance.json`：构造方法、时间基准和能力边界；
- `manifest.json`：产物登记、协议切面和运行结论；
- `sources/*.dot`：三张图对应的可检查源。

这些图表达 topology、已提交的模型动作和因果关系。它们不是 raw pin waveform，也不规定 RTL 必须使用
相同的周期距离或空拍安排。

## 示例中的“传感器”

`sensor_io_home` 现在通过 `ChiAddressHomeNode` 将 `ReadNoSnp` 转换为协议无关的 `AddressRead`，再交给
`AddressSpace/MemoryRegion`。只读 MemoryRegion 持有地址 `0x4020` 的确定性采样值；Home participant state
同时持有唯一的 AddressTarget state，因此网络调度回滚不会留下另一份设备状态。

这是一条 CHI family participant 到通用地址状态核的 composition boundary。转换直接使用 typed CHI message/packet
与 `AddressRead`，本地状态只保存在 Home participant 中。Sensor FIFO 的自主采样、空队列背压，以及全局
address→Home authority 仍需后续合同。

## 当前验证边界

本例实际覆盖：

- caller-built topology 的 port direction、transport family 和唯一 ownership elaboration；
- 三跳 REQ 与三跳 DAT 的路径闭合；
- 每跳 activation、L-Credit、有限 TX/RX 容量和背压；
- 两个 XP 的 exact `TgtID + channel` route、有限 FIFO 和透明转发；
- RN-I transaction correlation、Home service、CompData 返回和最终静默；
- 完整路径 lineage 对六条 hop 的覆盖。

本例采用 direct-Home、aligned full-DAT-width、single-DAT-flit、REQ/DAT-only profile。它当前不包含完整
CHI Port、bit codec、narrow DAT placement、CHI error-response mapping、Retry/P-Credit、RSP/SNP、缓存
一致性、multi-flit response、router QoS/fairness、任意多 Home 调度或网络 deadlock proof。

## 文件职责

- `model.py` 只做场景装配和执行，不重新实现 CHI 规则；
- `presentation.py` 将执行结果投影成教程图和生成版说明；
- `run.py` 管理具名发布、provenance 与 manifest。

协议与网络能力的实现仍位于 `protocol_model/protocols/amba/chi/issue_h/`，通用 topology 和图投影仍位于
`protocol_model/system/` 与 `protocol_model/visualization/`。
