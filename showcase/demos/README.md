# 可执行示例源码

本目录保存公开场景的确定性输入、系统装配、runner 与展示投影。协议规则继续由
`protocol_model/protocols/` 拥有，attachment、backend 和 recipe 继续由 `protocol_model/integrations/`
与 `protocol_model/virtual_dut/` 拥有；示例不维护第二套 checker。

## 目录

```text
showcase/demos/
├── axi4/                              # 24 个统一 AXI4 场景
├── link/
│   └── four_phase_handshake/          # 四相握手、频差与有限 FIFO
├── chi/
│   └── issue_h_flow_gallery/           # 五个 Issue H 流程的四视图
├── system/
│   ├── axi4_lite_single_manager_fabric/
│   ├── axi4_single_manager_read_demux/
│   ├── axi4_read_2x4_crossbar/
│   └── chi_issue_h_topology_shapes/    # 两个独立发布 leaf 的共享装配
└── vdut/
    ├── apb4_queued_responder/
    ├── axi_ahb_apb_chain/
    ├── axi4_lite_2x2_crossbar/
    ├── sensor_dma_capture/
    └── interrupt_control_plane/
```

`link/`、`chi/` 和 `vdut/` 是按观察目标组织的局部示例；以多节点 `SystemProtocol` 为主体的故事位于
`system/`。目录位置不改变对象的架构职责。

## 精选场景

### 接口与 observation

- [`axi4/`](axi4/README.md) 统一维护 24 个具名场景，覆盖事务生命周期、burst/字节几何、
  ordering/interleave、观察/复位和 exclusive/profile；每案生成结果、波形与因果图。
- [`link/four_phase_handshake/`](link/four_phase_handshake/README.md) 展示合法 RTZ、ACK 抢跑、
  payload 覆盖，以及有限 FIFO 面对频率差的边界。
- [`chi/issue_h_flow_gallery/`](chi/issue_h_flow_gallery/README.md) 让每个场景从自身的一次实际执行投影
  resolved XP topology、transaction 时空图、显式因果图和语义事件时间线，覆盖 clean
  `ReadUnique`、dirty-peer
  `CleanUnique`、`MakeUnique`、clean `Evict` Retry，以及 `WriteBackFull` 遇同址 invalidating Snoop。

### System 与互连

- [`system/axi4_lite_single_manager_fabric/`](system/axi4_lite_single_manager_fabric/README.md)
  把同一显式星形 topology 投影为传统 bus strip，展示地址译码和响应 mux。
- [`system/axi4_single_manager_read_demux/`](system/axi4_single_manager_read_demux/README.md)
  展示 AR/R 单 manager、多 subordinate、RID return ownership 与 destination lock。
- [`system/axi4_read_2x4_crossbar/`](system/axi4_read_2x4_crossbar/README.md)
  展示两个 manager、四个 target、raw-ID return-owner FIFO 和 manager-local RID namespace。
- [CHI 异构 ring + star 发布页](../generated/system/chi-issue-h-heterogeneous-ring-star/README.md)
  使用非均匀环形骨干加星形叶节点检查异构构造和方向化路由。
- [CHI 4×4 mesh 发布页](../generated/system/chi-issue-h-four-by-four-mesh/README.md)
  检查 16-router 规模、角到角长路径、route table closure 与最终静止。两案共享
  [`system/chi_issue_h_topology_shapes/`](system/chi_issue_h_topology_shapes/README.md) 中的装配与 runner。

flow gallery 负责协议流程与状态/因果见证；两个 topology leaf 增加的是 topology/route 压力，不替代
前者，也不因 4×4 mesh 的规模而形成更多 opcode 覆盖。

### VirtualDut 组合

- [`vdut/apb4_queued_responder/`](vdut/apb4_queued_responder/README.md)：
  attachment、有限队列、显式 service 与 APB4 响应。
- [`vdut/axi_ahb_apb_chain/`](vdut/axi_ahb_apb_chain/README.md)：
  两级 bridge、APB fabric、两个 endpoint 和完整 completion lineage。
- [`vdut/axi4_lite_2x2_crossbar/`](vdut/axi4_lite_2x2_crossbar/README.md)：
  双入口/双出口、仲裁、返回 owner 与 trace-conformance。
- [`vdut/sensor_dma_capture/`](vdut/sensor_dma_capture/README.md)：
  Sensor FIFO、DMA、crossbar、memory 与 overrun/read-to-pop 行为。
- [`vdut/interrupt_control_plane/`](vdut/interrupt_control_plane/README.md)：
  edge notification、priority delivery 与显式 EOI。

## 发布合同

- 普通 case 应有一个主要学习目标和确定性输入；
- 预期 verdict 与实际 verdict 分开记录；
- 图、机器结果、source IR、manifest 和 provenance 来自同一次运行；
- 具名 runner 先在 staging tree 完成构建，再替换自己拥有的 `showcase/generated/` 子树；
- 测试可以调用示例模型检查其仍可执行，但 scenario 装配和展示投影保留在本目录。

AXI4 的公开结果入口是[中文导航](../generated/axi4/README.zh-CN.md)和
[English guide](../generated/axi4/README.en.md)。全部生成资产见
[`showcase/generated`](../generated/README.md)。
