# AXI4 Constraint Provenance Audit

本审计不只问“代码拒绝了什么”，还问拒绝行为来自哪一层。否则测试配置、观测缺口和
AXI 规范会被混成同一种 violation。

## 四类来源

| 来源 | 含义 | 能否判 DUT protocol violation |
|---|---|---|
| `SPEC` | AXI 规范对接口行为的要求 | 可以 |
| `PROFILE` | 当前 endpoint 实现了哪些可选信号和能力 | 只有违反已声明 profile 时可以 |
| `OBSERVATION` | probe/adapter 提供了哪些端口和时钟 | 不可以；缺失意味着未覆盖或采集错误 |
| `TEST` | generator 的长度、概率、payload 分布 | 不可以；只影响激励空间 |

## 当前约束审计

| 当前行为 | 来源 | 判断 |
|---|---|---|
| VALID/READY rising-edge transfer | SPEC | 合理 |
| stalled 时 VALID 和 payload 保持 | SPEC | 合理 |
| RVALID 必须响应先前 AR | SPEC | 合理 |
| BVALID 等待 AW handshake 和最后一个 W handshake | SPEC | 合理 |
| WSTRB 只能标记当前 transfer 的合法 byte lanes | SPEC | 合理；允许合法 mask 的任意子集，包括零 |
| WRAP 长度/对齐、FIXED 最大16 beat、4KB boundary | SPEC | 合理 |
| 相同 ID 使用最老 pending transaction | SPEC | 合理的 AXI4 ordering 子集 |
| 每个 cycle 必须同时提供 AW/W/B/AR/R 五份 sample | OBSERVATION | 对完整接口采集合理；对 read-only、write-only 或 partial probe 过紧 |
| 每个地址事件都显式包含 LOCK/CACHE/PROT/QOS/REGION | PROFILE/normalization | 对 canonical full event 合理；直接接收省略可选引脚的 raw trace 时过紧，adapter 应填规范默认值 |
| 时钟字符串必须恰好为 `aclk` | OBSERVATION | 当前 adapter 命名假设，不是 AXI violation |
| `id_width > 0`、固定五通道 | PROFILE | 当前只描述 full AXI4 profile，不代表所有合法 AXI endpoint |
| generator 默认 `max_beats=4` | TEST | 只缩小随机覆盖，不缩小 checker 接受空间 |
| generator 为 WSTRB 选择完整 allowed mask | TEST | 生成分布过窄；checker 仍接受合法子集 |

## 尚未约束，不能误报为通过

- `AxLOCK` exclusive request 与 `EXOKAY` response 的对应关系；
- endpoint 对 burst、outstanding、ID 和 exclusive 的 capability；
- USER 信号及实现自定义语义；
- RDATA/WDATA 与 memory 功能状态的一致性；
- 完整 AXI ordering model、barrier/atomic 扩展；
- input-to-output 无组合路径的结构证据；
- progress、fairness、deadline 和最终响应。

协议本身把数据值视为不透明 payload。当前 dumb responder 只产生确定性测试数据，因此
检查器可以证明一次 R transfer 在位宽、握手、ID、beat 数和 RLAST 上符合协议，但不能
证明它读出了正确的 memory 内容；这需要带 memory 状态的 VirtualDut contract。

## Quiet 的使用边界

`QuietConstraint(IGNORE)` 用于明确投影掉未观测端口，它必须在覆盖结果中保留
“未检查”的含义；不能把缺失端口补成“协议正确”。`STABLE` 和 `TIED` 才是可失败的
接口/profile 约束。未来 `InterfaceProfile` 应先将 raw pin set 归一化为 canonical AXI
event，再交给协议 monitor：

```text
raw pins
  → profile defaults / Quiet policy / coverage
  → canonical five-channel observations
  → AXI signal and transaction monitors
```

依据：Arm IHI 0022H 的 A3 channel handshake/dependency、A9 default signaling and
interoperability，以及 burst/write-strobe章节。
