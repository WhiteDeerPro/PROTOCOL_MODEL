# 第一章：从一次采样到通信事实

[返回全书路线](../README.md) · [本章术语](../glossary.md)

验证环境在某个时刻看到一组 pin 值：`PSEL=1`、`PENABLE=1`、`PREADY=1`。这组数值可以表示一次完成的
APB transfer，也可能缺少前一拍 SETUP 所建立的上下文。协议模型需要保存观察历史，才能把电平解释成
通信事实。

本章建立第一条处理路径：

```text
pin / cycle sample
        │
        ▼
   AtomicFrame
        │  observation adapter
        ▼
  CanonicalEvent
        │  InterfaceSession + monitor
        ▼
 state / verdict / causal evidence
```

## 1.1 采样值提供材料，观察层完成解释

信号值描述某个采样边界上的电气接口状态。协议动作还依赖握手条件、前序 phase、reset epoch 和稳定性
要求。观察层保存这些必要上下文，并在条件满足时产生离散 event。

以 APB read 为例，观察层依次处理：

1. SETUP phase 保存地址、方向和控制字段，并产生 request event；
2. ACCESS phase 检查请求字段保持稳定；
3. `PREADY` 为低时继续保留 pending request；
4. `PREADY` 在 ACCESS phase 被采样为高时产生 completion event，`PRDATA` 与 `PSLVERR` 进入其 payload。

这段处理把多拍 pin 行为压缩成协议 monitor 可以消费的事实，同时保留违反 phase 关系时的 fault 位置。

## 1.2 AtomicFrame 保存共同解释边界

一次 transfer 往往由同一采样点上的多个条件共同决定。ready-valid 接口需要同时查看 ready 和 valid；
reset 也会改变当前 observation 应归属的 epoch。`AtomicFrame（一次共同解释的采样边界）`将这些 observation
一起交给 lowering。

AtomicFrame 的作用范围覆盖一次 lowering 输入。请求到 completion 的事务生命周期可以跨越多个 frame，
其未完成工作由 obligation、correlation state 或 backend state 继续保存。

这个边界带来两个直接收益：

- 同一采样点产生的 event 可以共享明确的来源；
- adapter 可以在提交状态前完成整组检查，避免只解释了一半的输入。

## 1.3 CanonicalEvent 进入协议语义层

观察层确认协议动作后，产生 `CanonicalEvent（协议可见的通信事实）`。一个 event 通常包含：

- `kind`：动作种类，例如 `READ` 或 `READ_RESPONSE`；
- `key`：用于 ID、tag 或 transaction key 关联的值；
- `payload`：地址、数据、响应码等 typed 字段；
- `trace_index`：session 接受后分配的证据位置。

CanonicalEvent 让后续 monitor 关注事务关系。APB、AXI 和 TileLink 可以保留各自的 event alphabet，通用
Pattern 则复用 request/completion 配对、cardinality、FIFO join 等关系。

## 1.4 一个最小 APB read trace

下面用语义视图表示一次成功读取：

```text
event 0  READ           payload={addr: 0x1000, prot: 0b010}
event 1  READ_RESPONSE  payload={data: 0x12345678, error: false}
causal   0 -> 1
```

`READ` 打开一项尚待完成的工作，`READ_RESPONSE` 与它配对并关闭该工作。有限 trace 在 event 0 结束时仍有
pending obligation，验证结论通常为 inconclusive；加入 event 1 后，该笔 read 生命周期闭合。

pin 波形和语义 trace 服务不同的阅读目的。波形便于核对 phase 与握手，语义 trace 便于核对 correlation、
ordering 和资源生命周期。展示工具可以把两者链接到同一 provenance。

## 1.5 状态由谁保存

| 信息 | 状态所有者 | 更新时机 |
|---|---|---|
| APB SETUP 中暂存的请求字段 | APB observation state | 进入 SETUP、等待 ACCESS 完成 |
| request/completion 配对 | 该 interface connection 的 monitor state | session 接受 event |
| 模块寄存器或 memory 内容 | VirtualDut backend state | operation 执行 |
| 系统中的全局 event 编号与因果边 | SystemSessionState | event 穿过具体 InterfaceConnection |

清晰的所有权使每个事实拥有一个可变权威来源。其他层可以保存只读 projection、索引或 verdict，用于展示和
系统级检查。

## 1.6 本章边界

本章处理 observation 到 event 的入口。后续章节继续回答三类问题：InterfaceProtocol 怎样判断 event 序列，
VirtualDut 怎样处理 operation，SystemProtocol 怎样把多个局部生命周期放入同一网络。

## 练习

1. 某 ready-valid 接口在同一 frame 中观察到 `valid=1, ready=0`。列出 observation state 需要保留的信息，
   并说明何时产生 transfer event。
2. 一笔 AXI read request 已经进入 InterfaceSession，但 R completion 尚未出现。分别指出 protocol obligation、
   VirtualDut 内部执行状态和波形采样历史的所有者。
