# AMBA LinkProtocol variants

AXI4-Lite 与 AXI4-Stream 都位于 `LinkProtocol` 层，但它们和 AXI4 的关系不同：

```text
AXI4 memory-mapped semantics
            │ semantic restriction + schema projection
            ▼
       AXI4-Lite ── explicit embedding ──► AXI4 canonical events

ready-valid observation
            │ reused encoding
            ▼
       AXI4-Stream
```

AXI4-Lite 是 memory-mapped 协议的受限 variant；AXI4-Stream 是独立的单向数据流协议。后者共享
ready-valid observation，但不继承 address、response、outstanding transaction 或 exclusive 语义。

## AXI4-Lite

代码位于 `protocol_model/link/amba/axi/axi4_lite/`。原生 schema 只包含规范允许的五通道字段：

- AW/AR：`addr, prot`；
- W：`data, strb`；
- B：`resp`；
- R：`data, resp`。

缺失字段不是“生成时暂不填写”，而是具有固定含义：burst length 为 1、transfer size 为 data bus
width、LOCK/CACHE 为零、LAST 为真、所有事务使用一个固定 ID。`Axi4LiteToAxi4` 显式补入这些含义，
使 Lite trace 可以进入 AXI4 LinkSession；它不是 adapter 兼容旧 API。

当前可执行语义包括：

- 32/64-bit data width；
- 单 beat AR/R；
- AW 与 W 独立握手并按 acceptance order FIFO join，W 可以早于 AW；
- 多 outstanding、无 ID、response in-order；
- `OKAY/SLVERR/DECERR`，不接受 `EXOKAY`；
- full-width 隐含 transfer container 与 WSTRB byte-lane 校验；
- read、pending AW、pre-AW W 和 pending B completion 的资源生命周期；
- 复用五通道 AtomicFrame ready-valid/reset observation；
- `with_resource_capacities()` 可按具体 profile 收紧 outstanding 资源。

后续若需要 full AXI master 到 Lite subordinate 的 burst 拆分、ID reflection 和 response combine，应建成
bridge `VirtualDut`。它们改变 transaction 数量并持有转换状态，不属于 Lite 单 link 的事件 embedding。

## AXI4-Stream

代码位于 `protocol_model/link/amba/axi/axi4_stream/`。基础协议只有一个 transmitter → receiver 的 `T` channel。
`TVALID/TREADY` 留在 observation；accepted transfer 的 canonical event 按配置包含 TDATA、TKEEP、
TSTRB、TLAST、TID、TDEST 和 TUSER 对应字段。

当前可执行语义包括：

- TDATA width 为正整数个 byte，不沿用 AXI4 memory-mapped 的 power-of-two 限制；
- TKEEP 缺失时按全一处理，TSTRB 缺失时按 TKEEP 处理；
- 拒绝 `TKEEP=0, TSTRB=1` 的 reserved byte qualification；
- `(TID,TDEST)` 标识 stream/packet，基础协议允许不同 stream 的 transfer interleave；
- TLAST 显式存在时记录 open packet；trace 停在 packet 中间时是 inconclusive；
- accepted transfer 的全局顺序进入 causal edges；
- packet generator 与单 lane AtomicFrame ready-valid/reset observation。

`build_axi4_stream_continuous_profile()` 是基础 Stream 的单调收窄：禁止 packet interleave，不支持
TSTRB position byte，非 final transfer 的 TKEEP 必须全一，final transfer 的 null byte 只能形成高位
suffix。这一 profile 对应规范的 `Continuous_Packets` 属性，不替所有 Stream 接口选择该行为。

当前实现范围尚未包含 TDATA 缺失接口、width converter/packer、TUSER 每 byte 位置保持以及 AXI5-Stream
wakeup/parity。前两项需要先定义输入输出 stream 间的转换关系，后两项分别涉及 sideband layout 和
AXI5-Stream variant。

## 规范依据

- Arm IHI 0022H，B1：AXI4-Lite definition、interoperability 和 conversion；
- Arm IHI 0051B，Chapter 2-4：AXI-Stream signals、defaults、packet interleaving 和 ordering。
