# 可执行示例目录约定

本目录保存宣传材料使用的可执行场景源码。AXI4 当前只有一套公开介绍例：

- [`axi4/`](axi4/README.md) 含 24 个具名场景，按事务生命周期、burst 与字节几何、
  ordering/interleave、观察与复位、独占访问与 profile 五个主题组织；
- 每个场景都由同一个 runner 实际生成 `result.json`、`waveform.svg` 和
  `causality.svg`；
- `write-narrow-unaligned-incr` 与 `write-early-wlast` 是同一套 24 案中的两项精讲，
  不是另一套 quick start，也不重复计数。

当前组织与近期扩展点：

```text
showcase/demos/
├── axi4/
│   ├── cases/          # 按语义主题拆分的输入目录
│   ├── common.py       # 小型输入构造词汇
│   ├── execution.py    # 调用当前协议模型并收集结果
│   ├── hero_cases.py   # 两个精讲 case 的丰富 AtomicFrame 输入
│   ├── presentation.py # 波形、因果图和导航投影
│   └── run.py          # 唯一具名发布入口
├── link/
│   └── four_phase_handshake/ # 四相 observer、高/低差频与 FIFO 容量直觉
├── chi/
│   └── issue_h_read_no_snp/  # 双向 link 上的 direct ReadNoSnp→CompData
├── system/                    # 明确以多节点 SystemProtocol 为讲解主体的新示例
│   ├── axi4_lite_single_manager_fabric/ # 一个 manager、三个 subordinate
│   ├── axi4_single_manager_read_demux/  # AXI4 read-only AR/R 1×M 特化
│   ├── axi4_read_2x4_crossbar/          # AXI4 AR/R N×M 与 raw-ID return owner
│   ├── chi_issue_h_routed_read/         # RN-I、两个 XP 与 I/O Home
│   └── chi_issue_h_clean_2x2_mesh/      # 四 XP 方环与 clean ReadUnique
├── vdut/
    ├── apb4_queued_responder/ # attachment、有限队列与显式 service
    ├── axi_ahb_apb_chain/    # 两级 bridge、APB fabric 与两个 endpoint
    ├── axi4_lite_2x2_crossbar/ # 双入口/双出口、仲裁与返回 owner
    ├── sensor_dma_capture/    # Sensor FIFO、DMA、crossbar 与 memory 搬运
    └── interrupt_control_plane/ # edge notification、priority 与显式 EOI
```

`link/`、`chi/`、`vdut/` 是早期示例按不同观察轴形成的目录，当前仍保留其稳定发布路径。新建的多节点
故事统一进入 `system/`；后续若迁移旧示例，需要同步 provenance、生成命令和发布链接，不在本轮为目录整齐
批量搬动。

[`link/four_phase_handshake/`](link/four_phase_handshake/README.md) 执行四相 RTZ 的合法传输、ACK 抢跑和
payload 覆盖场景，并用两个时间尺度解释 async FIFO：250 MHz→100 MHz 的有限 burst 由 FIFO 吸收，
`1,000,000,001 Hz`→`1,000,000,000 Hz` 则形成一秒 beat 和每秒一个 word 的长期漂移。后者采用解析投影，
不会为了画图展开约十亿个周期。

[`chi/issue_h_read_no_snp/`](chi/issue_h_read_no_snp/README.md) 执行受限的 direct-Home read：
`ReadNoSnp` 经正向 REQ link 到达 Home，单个 `CompData` 经反向 DAT link 返回。示例用事件级时空图表达
correlation 与 L-Credit 因果关系，不把 reference transport tick 冒充 raw RTL waveform。

[`system/axi4_lite_single_manager_fabric/`](system/axi4_lite_single_manager_fabric/README.md)
专门展示传统“一根 AXI 总线挂多个设备”的阅读方式。执行模型仍保留一个 single-ingress fabric
VirtualDut 和四条二端 InterfaceConnection；公共投影器额外把同一结构折叠成带地址窗口的 bus-strip，
不会产生第二份隐式 topology。

[`system/axi4_single_manager_read_demux/`](system/axi4_single_manager_read_demux/README.md)
执行 AXI4 read-only profile 的单 manager、双 subordinate AR/R 读通路。示例让不同 RID 从两个设备交错返回，并展示同一
RID 改投另一个设备时的 destination-lock `BLOCK`、`RLAST` 释放和显式重试；当前范围只包含 AR/R。

[`system/axi4_read_2x4_crossbar/`](system/axi4_read_2x4_crossbar/README.md)
实例化同一个通用 AXI4 read-only AR/R builder 为两个 manager、四个 memory target。它展示同一
egress/raw RID 的 return-owner FIFO、不同 manager 的 RID namespace，以及同一 manager/RID
跨 target 的 destination lock。Canonical AR 已是 accepted transfer，因而示例记录的提交顺序
是本次 witness 的 grant 顺序，不表示 pin-level 仲裁或 ACLK 时序。当前
`raw-ID-serialized` profile 不包含 AW/W/B、ID remap 或多 ingress exclusive read。

[`system/chi_issue_h_routed_read/`](system/chi_issue_h_routed_read/README.md)
装配 `RN-I → XP0 → XP1 → I/O Home` 的三跳 REQ 路径及反向三跳 DAT 路径。示例执行一次受限
`ReadNoSnp`，展示自由 topology、每跳 L-Credit/有限缓存、router 转发和端到端 transaction lineage；
Home 已通过 CHI participant adapter 委派给通用 `AddressSpace/MemoryRegion` 状态核。完整 CHI、coherence、
Sensor FIFO progress 和 address→Home authority 仍在本例范围之外。

[`system/chi_issue_h_clean_2x2_mesh/`](system/chi_issue_h_clean_2x2_mesh/README.md)
用四个 XP 组成最小 2×2 square mesh。一次 clean `ReadUnique` 让 REQ、两路 SNP、两路 RSP、DAT 和
CompAck 覆盖方环四边，并把 RN0/RN1/RN2 与 Home directory 从 `I/SC/SC + sharers` 收束到
`UC/I/I + unique owner`。拓扑图采用示例级固定四角排版；节点、连接、packet route 和状态仍来自同一次
可执行构造。

[`vdut/axi_ahb_apb_chain/`](vdut/axi_ahb_apb_chain/README.md) 是当前的微型
网络组合例：它使用公共投影器发布紧凑拓扑、可检查的展开拓扑、两个 bridge
的内部结构、APB decoder/response mux、因果链和运行结果。场景驱动位于
VirtualDut 边界外，图中不会把它误认为 DUT 内部事务发生器。

[`vdut/axi4_lite_2x2_crossbar/`](vdut/axi4_lite_2x2_crossbar/README.md)
展示两个 manager 竞争同一 target 的最小 N×M 组网见证。发布包同时给出 crossbar
内部资源图和 trace-conformance 图，用来区分一条 deterministic execution witness
与允许空拍、不同合法调度的 RTL behavior set。

[`vdut/sensor_dma_capture/`](vdut/sensor_dma_capture/README.md) 使用确定性样本策略运行
`Sensor FIFO → serialized DMA → AXI4-Lite crossbar → memory`。它同时展示 FIFO
overrun、固定地址 read-to-pop、连续目标写入和各 constructed VirtualDut 的内部投影。

[`vdut/interrupt_control_plane/`](vdut/interrupt_control_plane/README.md) 演示项目级 edge
notification InterfaceProtocol：两个 source 向 priority controller 发出通知，controller 在一个
active delivery 与显式 EOI 约束下向 CPU target 串行投递。该示例不冒充 GIC/PLIC，也没有
memory-mapped 配置端口。

公开阅读入口是 [AXI4 可执行示例导航](../generated/axi4/README.zh-CN.md)，英文版见
[AXI4 executable example guide](../generated/axi4/README.en.md)。普通 case 在导航中用折叠块串起
短说明、波形和因果图；两个精讲 case 直接展开并解释新的观察边界或资源关系。

目录只拥有场景编排和教程投影：

- 协议规则继续由 `protocol_model/protocols/` 与通用 `interface/`、`transport/` 设施拥有；
- DUT attachment 与 bridge recipe 继续由 `protocol_model/integrations/` 拥有；
- 通用运行产物继续由 `protocol_model/artifacts/` 和 `protocol_model/visualization/` 管理；
- 具名脚本原子替换自己拥有的 `showcase/generated/axi4/`，并保留 WaveJSON、DOT、参数与 provenance；
- 测试验证 engine，示例讲述用户故事；两者可以复用输入，但示例不实现第二套 checker。

场景数表示当前发布的可执行样本，不等价于 AXI4 规范覆盖率或 RTL compliance。
