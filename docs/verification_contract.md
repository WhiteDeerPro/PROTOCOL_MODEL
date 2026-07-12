# Verification Contract

项目不再把测试数量作为完成度指标。任何验证动作必须先声明它在检查哪一条语义要求。

## 单条要求的记录格式

```text
Requirement
  自然语言规则与规范范围

Model element
  哪个 domain / automaton / token / relation 承担规则

Legal witness
  如何构造一个满足规则的有限执行

Mutation
  只破坏哪一个条件

Expected evidence
  transfer、marking、causal edge、verdict 与 rule id

Known blind spot
  本次有限 witness 不能证明什么
```

## 示例：AXI ready/valid stall

```text
Requirement
  VALID=1 且 READY=0 后，直到 handshake，VALID 和 payload 必须保持。

Model element
  ClockedReadyValid(Stalled(saved_event))

Legal witness
  cycle 2: VALID=1 READY=0 payload=A
  cycle 3: VALID=1 READY=1 payload=A

Mutation
  cycle 3 把 payload 改为 B。

Expected evidence
  rule=AW.ready_valid.payload_stability
  verdict=FAIL at cycle 3

Known blind spot
  不能从单条 trace 证明 VALID 的组合逻辑不依赖 READY。
```

## 执行策略

- 开发过程中只运行当前 requirement 的 witness；
- 完成一个语义层时运行一次闭环 smoke；
- 完整 regression 只在用户明确要求或发布里程碑执行；
- 每次汇报优先给出波形、marking、因果图和最小 violation；
- PASS 只说明该有限 witness 被模型接受，不说明协议模型完备。

## 未约束不等于一种统一结论

对任意行为必须区分：

| 分类 | 含义 | 当前例子 |
|---|---|---|
| explicitly allowed | schema 和所有已实现规则都接受 | 合法 INCR burst |
| explicitly forbidden | 某个规则给出 violation | 提前 RLAST |
| open / unconstrained | 能表示，但尚无对应语义规则，因此当前会被过近似接受 | 缺少 exclusive 上下文时的 EXOKAY |
| unrepresentable | alphabet/schema 没有这个对象，不能解释为允许或禁止 | 当前未建模的 USER signal |

constructive generator 只产生 explicitly allowed 集合中的一个子集。没有被随机生成，不表示
协议禁止；validator 接受一个 open/unconstrained 行为，也不表示 AXI 规范允许。报告必须结合
`ProtocolSpec.requirements` 的实现状态阅读。

## 未约束与无关联

“规则尚未实现”和“规范有意不关联两个值或事件”必须分开：

| 分类 | 含义 | AXI 例子 |
|---|---|---|
| constrained | 规范明确规定关系，模型已经实现 | `ARLEN+1` 个 R beat |
| unmodeled | 规范明确规定关系，但模型尚未实现 | exclusive request/EXOKAY 关系 |
| opaque / parametric | 规范只约束类型、宽度和稳定性，不规定具体内容 | WDATA 的数值 |
| independent | 规范允许两个行为无必要因果关系 | AW 与 AR 可以同周期 transfer |
| DUT functional | 关系属于被验证设备功能，不属于总线协议本身 | RAM 读数据等于先前写入数据 |
| out of scope | 当前 schema 尚不能表示 | 尚未加入的 USER signals |

例如 WDATA 并非“毫无规范要求”：AXI 仍规定数据宽度、WSTRB 配合、VALID stall 稳定性和
beat 数；但 AXI 不规定某一拍必须携带数值 `0x1234`。后者由 manager stimulus 或 memory/DUT
功能模型决定。
