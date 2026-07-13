# Protocol Model Project 功能导览

五个内建 Project 按简单到复杂排列。每个 case 的波形图与因果事件图均由同一次 `run-all` 生成。
负例的预期结果为 `FAIL`，表示对应约束被成功触发。

| Project | 测试内容 | Cases | 结果 |
|---|---|---:|---|
| `prj_ready_valid_sink` | 最小 ready-valid 链路：握手、stall 与 payload stability。 | 2 | PASS |
| `prj_apb_compare` | APB3/APB4 两阶段传输、wait state 与请求保持。 | 3 | PASS |
| `prj_axi4_read_bridge` | 两个 AXI4 实例之间的 read bridge、转发因果与 4KB 拒绝。 | 2 | PASS |
| `prj_axi4_read_interleave` | 跨 ID read-data 交织、同 ID 顺序与 Project profile。 | 5 | PASS |
| `prj_axi4_scenarios` | 无 bridge 的 AXI4 source/responder 批量场景，覆盖五通道事务、并发、ordering 与 reset。 | 37 | PASS |
## `prj_ready_valid_sink`

最小 ready-valid 链路：握手、stall 与 payload stability。

结果：**PASS**；2 个 case。

### Project 图

#### Project 组网 · network.svg

![Project 组网 · network.svg](project-guide-assets/prj_ready_valid_sink/network.svg)

### `legal_stall`

legal_stall

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_ready_valid_sink/cases/legal_stall/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_ready_valid_sink/cases/legal_stall/causality.svg)

### `changed_while_stalled`

changed_while_stalled

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_ready_valid_sink/cases/changed_while_stalled/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_ready_valid_sink/cases/changed_while_stalled/causality.svg)


## `prj_apb_compare`

APB3/APB4 两阶段传输、wait state 与请求保持。

结果：**PASS**；3 个 case。

### Project 图

#### 协议状态图 · state.svg

![协议状态图 · state.svg](project-guide-assets/prj_apb_compare/state.svg)

#### Project 组网 · network.svg

![Project 组网 · network.svg](project-guide-assets/prj_apb_compare/network.svg)

### `legal_apb3`

legal_apb3

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_apb_compare/cases/legal_apb3/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_apb_compare/cases/legal_apb3/causality.svg)

### `legal_apb4`

legal_apb4

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_apb_compare/cases/legal_apb4/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_apb_compare/cases/legal_apb4/causality.svg)

### `request_stability_mutation`

request_stability_mutation

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_apb_compare/cases/request_stability_mutation/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_apb_compare/cases/request_stability_mutation/causality.svg)


## `prj_axi4_read_bridge`

两个 AXI4 实例之间的 read bridge、转发因果与 4KB 拒绝。

结果：**PASS**；2 个 case。

### Project 图

#### Project 组网 · network.svg

![Project 组网 · network.svg](project-guide-assets/prj_axi4_read_bridge/network.svg)

### `legal_4kb_edge`

legal_4kb_edge

预期：`PASS`；观察到：`PASS`。

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_read_bridge/cases/legal_4kb_edge/causality.svg)

#### AXI-A 波形图 · waveform.axi-a.svg

![AXI-A 波形图 · waveform.axi-a.svg](project-guide-assets/prj_axi4_read_bridge/cases/legal_4kb_edge/waveform.axi-a.svg)

#### AXI-B 波形图 · waveform.axi-b.svg

![AXI-B 波形图 · waveform.axi-b.svg](project-guide-assets/prj_axi4_read_bridge/cases/legal_4kb_edge/waveform.axi-b.svg)

### `crossing_4kb`

crossing_4kb

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_read_bridge/cases/crossing_4kb/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_read_bridge/cases/crossing_4kb/causality.svg)


## `prj_axi4_read_interleave`

跨 ID read-data 交织、同 ID 顺序与 Project profile。

结果：**PASS**；5 个 case。

### Project 图

#### Project 组网 · network.svg

![Project 组网 · network.svg](project-guide-assets/prj_axi4_read_interleave/network.svg)

### `cross_id_out_of_order`

cross_id_out_of_order

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_read_interleave/cases/cross_id_out_of_order/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_read_interleave/cases/cross_id_out_of_order/causality.svg)

### `same_id_cannot_overtake`

same_id_cannot_overtake

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_read_interleave/cases/same_id_cannot_overtake/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_read_interleave/cases/same_id_cannot_overtake/causality.svg)

### `rid_must_be_active`

rid_must_be_active

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_read_interleave/cases/rid_must_be_active/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_read_interleave/cases/rid_must_be_active/causality.svg)

### `arcache_tied_zero`

arcache_tied_zero

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_read_interleave/cases/arcache_tied_zero/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_read_interleave/cases/arcache_tied_zero/causality.svg)

### `write_valid_tied_low`

write_valid_tied_low

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_read_interleave/cases/write_valid_tied_low/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_read_interleave/cases/write_valid_tied_low/causality.svg)


## `prj_axi4_scenarios`

无 bridge 的 AXI4 source/responder 批量场景，覆盖五通道事务、并发、ordering 与 reset。

结果：**PASS**；37 个 case。

### Project 图

#### Project 组网 · network.svg

![Project 组网 · network.svg](project-guide-assets/prj_axi4_scenarios/network.svg)

### `read_single_incr`

legal 1-beat INCR read

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_single_incr/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_single_incr/causality.svg)

### `read_16_incr`

legal 16-beat INCR read

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_16_incr/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_16_incr/causality.svg)

### `read_fixed_16`

legal 16-beat FIXED read

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_fixed_16/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_fixed_16/causality.svg)

### `read_wrap_4`

legal 4-beat WRAP read

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_wrap_4/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_wrap_4/causality.svg)

### `read_fixed_17_rejected`

FIXED exceeds 16 beats

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_fixed_17_rejected/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_fixed_17_rejected/causality.svg)

### `read_wrap_3_rejected`

WRAP uses an illegal three-beat length

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_wrap_3_rejected/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_wrap_3_rejected/causality.svg)

### `read_4kb_edge`

burst ends at 0x0FFF immediately before the 0x1000 boundary

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_4kb_edge/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_4kb_edge/causality.svg)

### `read_cross_4kb`

full-width INCR burst crosses 4KB

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_cross_4kb/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_cross_4kb/causality.svg)

### `read_early_rlast`

RLAST asserted on the first of two beats

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_early_rlast/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_early_rlast/causality.svg)

### `read_missing_rlast`

final beat omits RLAST

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_missing_rlast/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_missing_rlast/causality.svg)

### `read_extra_beat`

R beat follows a completed burst

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_extra_beat/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_extra_beat/causality.svg)

### `read_orphan_r`

R arrives without an AR obligation

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_orphan_r/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_orphan_r/causality.svg)

### `read_unknown_rid`

R uses a different ID from the pending AR

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_unknown_rid/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_unknown_rid/causality.svg)

### `read_slverr`

SLVERR completes an ordinary read

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_slverr/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_slverr/causality.svg)

### `read_decerr`

DECERR completes an ordinary read

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_decerr/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_decerr/causality.svg)

### `write_single`

ordinary single-beat write

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_single/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_single/causality.svg)

### `write_data_before_address`

complete W burst precedes AW

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_data_before_address/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_data_before_address/causality.svg)

### `write_aw_w_same_cycle`

AW and W handshake together

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_aw_w_same_cycle/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_aw_w_same_cycle/causality.svg)

### `write_two_outstanding`

two AW descriptors join two FIFO W bursts

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_two_outstanding/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_two_outstanding/causality.svg)

### `write_early_wlast`

WLAST asserted before AWLEN beats

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_early_wlast/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_early_wlast/causality.svg)

### `write_missing_wlast`

final W beat omits WLAST

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_missing_wlast/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_missing_wlast/causality.svg)

### `write_wrong_bid`

BID does not name a completed write

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_wrong_bid/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_wrong_bid/causality.svg)

### `write_b_before_join`

B arrives before AW/W join

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_b_before_join/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_b_before_join/causality.svg)

### `write_slverr`

SLVERR completes an ordinary write

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_slverr/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_slverr/causality.svg)

### `write_decerr`

DECERR completes an ordinary write

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_decerr/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_decerr/causality.svg)

### `read_cross_id_later_first`

later ID2 request completes before ID1

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_cross_id_later_first/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_cross_id_later_first/causality.svg)

### `read_cross_id_interleave`

R beats alternate across two IDs

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_cross_id_interleave/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_cross_id_interleave/causality.svg)

### `read_same_id_overtake`

second same-ID burst attempts to complete first

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_same_id_overtake/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_same_id_overtake/causality.svg)

### `write_cross_id_b_reverse`

different BID responses complete in reverse request order

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_cross_id_b_reverse/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_cross_id_b_reverse/causality.svg)

### `write_burst_fifo_mismatch`

short W burst cannot skip the oldest longer AW

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/write_burst_fifo_mismatch/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/write_burst_fifo_mismatch/causality.svg)

### `read_write_parallel`

read and write requests overlap and R/B complete together

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/read_write_parallel/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/read_write_parallel/causality.svg)

### `five_channel_concurrency`

all five channels handshake in one cycle after obligations exist

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/five_channel_concurrency/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/five_channel_concurrency/causality.svg)

### `stall_aw_payload_mutation`

AW payload changes while VALID is stalled

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/stall_aw_payload_mutation/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/stall_aw_payload_mutation/causality.svg)

### `stall_r_valid_drop`

RVALID drops before a stalled transfer is accepted

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/stall_r_valid_drop/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/stall_r_valid_drop/causality.svg)

### `reset_discards_outstanding_read`

response from the pre-reset epoch becomes orphaned

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/reset_discards_outstanding_read/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/reset_discards_outstanding_read/causality.svg)

### `reset_clears_stalled_valid`

reset cancels a stalled AW and a new write completes afterward

预期：`PASS`；观察到：`PASS`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/reset_clears_stalled_valid/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/reset_clears_stalled_valid/causality.svg)

### `inconsistent_channel_reset`

one AXI channel observes a different reset level

预期：`FAIL`；观察到：`FAIL`。

#### 波形图 · waveform.svg

![波形图 · waveform.svg](project-guide-assets/prj_axi4_scenarios/cases/inconsistent_channel_reset/waveform.svg)

#### 因果事件图 · causality.svg

![因果事件图 · causality.svg](project-guide-assets/prj_axi4_scenarios/cases/inconsistent_channel_reset/causality.svg)
