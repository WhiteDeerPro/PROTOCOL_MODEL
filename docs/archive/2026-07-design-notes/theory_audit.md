# Theory Audit

本文审计当前实现与五组理论的真实关系。判定标准不是“术语相似”，而是：

1. 是否明确定义了该理论的基本对象；
2. 是否实现了该理论规定的运算或组合；
3. 是否复用了判定算法、不变量或定理；
4. 是否用性质测试验证相应代数律。

## 1. 总结

| 理论 | 当前映射 | 使用程度 | 结论 |
|---|---|---:|---|
| 形式语言与自动机 | `SemanticComponent`、step/emission/fault、PortSpec | 高 | signal、transaction 与 session 已统一为一个可执行 LTS 接口；port routing/ownership 尚未进入执行器 |
| Petri 网 | `CardinalityObligation`、`CorrelatedCardinalityObligation` keyed token | 中等 | multibeat 与 join 已采用有色 marking 语义；尚无通用 Place/Transition 与不变量分析 |
| Hoare 逻辑 | reject 类似 precondition，transition 类似 command | 很低 | 尚未定义 Hoare triple、断言或组合证明规则 |
| 时序逻辑 | complete/end-of-trace 检查 | 几乎没有 | 没有 LTL/TLA 的 always/eventually/until、公平性和无限行为 |
| 范畴论 | component/network 的“组合”愿望 | 没有 | OOP aggregation 不是范畴组合 |
| 关系代数/KAT | guard、transition、sequence/choice 的潜在对应 | 很低 | 没有关系并、复合、逆、闭包或等式推理 |
| 偏序/拓扑排序 | `CausalGraph`、可达性、并发、linear extension | 较高 | 当前最扎实的数学部分 |
| Mazurkiewicz trace/pomset | 文档中的 independence 与交换等价 | 较低 | 代码没有 independence relation、商集或交换不变性测试 |

粗略判断：

- **思想原料大多来自既有理论**，事件、状态迁移、token、义务、偏序、guard 都不是新数学；
- **当前 API 和组合规则大多是我们自行设计的工程语义**；
- **真正复用的理论结果很少**，目前主要是 DAG/偏序性质和拓扑排序；
- 因此当前更准确的描述是“受经典理论启发的可执行原型”，而不是“由这些理论推导出的框架”。

## 2. 形式语言与自动机理论

### 2.1 当前代码的精确映射

`SemanticComponent` 可以形式化为：

\[
A=(S,\Sigma,\rightarrow,s_0,F)
\]

其中：

- `S`：component-local state 集合；
- `Σ`：引脚 observation 或 `CanonicalEvent` action 字母表；
- `s0`：`initial_state()`；
- `s --a/o→ s'`：`step(s,a)` 接受 action、产生 emission `o` 并到达 `s'`；
- `F`：`is_quiescent(s)` 为真的静止状态。

generator 构造候选 action，validator 接收外部 action，但二者都必须调用同一个 `step`。
对固定 `(state,action)` 当前 transition 是确定的；非确定性来自 scheduler 和 payload 采样。

`ProtocolSession` 的全局状态是 transaction component 局部状态的直积：

\[
S = \prod_i S_i
\]

早期 `proposal union + reject conjunction + broadcast transition` 体系已经删除。逐周期观察、
transaction token 与 session 现在都使用确定性 `SemanticComponent.step(state, action)`，产生
新状态、零或多个 emission，或一个不可修复 safety fault。
`ClockedReadyValid` 是具体 Mealy 转导器，其状态为 idle/stalled，输出函数在且仅在
`VALID ∧ READY` 时产生 transfer。这里已经真正采用自动机的状态、转移、输出和接受/静止
语义，而不只是借用名称。

### 2.2 没有利用的理论能力

- 已声明 input/output/internal `PortSpec`，但尚未用于自动 routing；
- 没有环境 assumption 与组件 guarantee；
- 没有兼容性和非法状态计算；
- 没有 simulation、bisimulation、refinement；
- 没有自动机最小化或等价判定；
- 没有符号 alphabet，仍依赖有限 concrete event 枚举。

Interface Automata 明确区分 input/output，并把接口描述为环境假设和组件保证，还支持自动兼容性检查。这比当前所有 component 都共同 `reject()` 更适合未来 ProtocolSpec、VirtualDut 和 Port。[de Alfaro & Henzinger, *Interface Automata*](https://doi.org/10.1145/503209.503226)

### 2.3 建议

选择 **I/O labeled transition system / interface automata** 作为协议核心的正式脊柱：

```text
ProtocolSpec = IO alphabet + state + transition relation + invariants
VirtualDut   = strategy/policy that chooses owned output actions
Environment  = supplies input actions
```

这会正式解决“协议本身不应扮演通信两端”的问题。

## 3. Petri 网

### 3.1 当前映射

| 当前对象 | Petri 网解释 |
|---|---|
| cardinality remaining | 带权 obligation place 中的 token 数 |
| pending obligation | 以 transaction key 着色的 token |
| request event | 消耗 credit、产生 pending token 的 transition |
| response event | 消耗 pending、归还 credit 的 transition |
| enabled event | transition firing condition |

这非常接近 **有色 Petri 网**，因为 obligation token 携带 key/payload/attempt。

### 3.2 为什么现在还不算真正使用 Petri 网

- marking 不是统一 multiset；
- place、transition、input/output arc 没有显式对象；
- 没有 arc weight、inhibitor/read arc；
- 没有 P-invariant/T-invariant；
- 没有 reachability、boundedness、deadlock 分析；
- cardinality 与 correlation 仍是专用 token state，尚未下降为统一 Place/Transition 图。

新增的 `CardinalityObligation` 已修正这一类问题：begin 产生带 key、serial、total、remaining
的 token；beat 只消费相同 key 的最老 token一次；final marker 必须与 remaining 是否为 1
一致。AXI read 使用它表达 `ARLEN+1` 个 R beat。它是一个受限的有色 FIFO place，仍不是
具备任意弧、可达性与 P-invariant 分析的完整 Petri 网。

### 3.3 建议

不要把整个系统改写成 Petri 网；将 resource/obligation 子系统正式化为小型有色网：

```text
Place[T]
Marking = Counter[T]
Transition
├── consume(place, pattern, count)
├── read(place, predicate)
├── inhibit(place, predicate)
└── produce(place, expression, count)
```

优先获得三个理论收益：

1. token/cardinality 语义正确；
2. `credits + pending == capacity` 等 P-invariant 可检查；
3. bounded state 下可做 deadlock/reachability exploration。

开放 Petri 网把输入/输出 place 作为边界，并通过粘合边界组合小网；其 reachability 和 operational semantics 可以组合研究。这与未来 Port/Link/Bridge 很契合，但应在网络对象稳定后再引入。[Baez & Master, *Open Petri Nets*](https://arxiv.org/abs/1808.05415)

## 4. Hoare 逻辑与时序逻辑

这两者不应混为一层。

### 4.1 Hoare 逻辑

当前可以把一次 transition 非正式写成：

\[
\{ enabled(s,e) \}\; apply(e)\; \{ state=s' \land invariant(s') \}
\]

但代码没有：

- `Precondition` / `Postcondition` 对象；
- Hoare triple；
- sequence、choice、loop 的证明规则；
- weakest precondition；
- invariant preservation proof。

所以 `reject()` 只是 executable guard，不等于使用 Hoare 逻辑。Hoare 原始工作提供的是关于程序正确性的公理和推理规则，而不只是“有前置条件”这个编程习惯。[Hoare, *An Axiomatic Basis for Computer Programming*](https://doi.org/10.1145/363235.363259)

Hoare 风格最适合未来 VirtualDut 的功能行为：

```text
{address aligned ∧ fifo not empty}
read_data()
{result = old(fifo.head) ∧ fifo = old(fifo.tail)}
```

### 4.2 时序逻辑

当前 `is_complete()` 和 trace-end obligation 检查只处理有限执行，没有真正的时序算子。尚不能表达：

```text
G(request -> F response)          # 每个请求最终有响应
G(valid && !ready -> X stable)   # stall 下一拍保持稳定
G F grant                        # 公平条件下反复获得仲裁
```

TLA 将 action 表达为前后状态关系，并用时序公式描述整个 behavior；它强调 safety、liveness 和 stuttering invariance。这些都尚未出现在实现中。[Lamport, *The Temporal Logic of Actions*](https://lamport.org/pubs/lamport-actions.pdf)

建议分阶段：

1. 先支持 finite-trace monitor property；
2. safety property 编译为 monitor automaton；
3. deadline/finite liveness 用 obligation 处理；
4. 只有开始讨论无限运行、公平性和 stuttering 时再引入 LTL/TLA 层。

不要用一次随机 trace 的 PASS 冒充 `G`/`F` 性质证明。

## 5. 范畴论

### 5.1 当前真实情况

当前没有使用范畴论。

以下内容都不构成范畴论使用：

- Python 对象叫 component；
- 把对象放进 tuple；
- 网络中计划连接 ports；
- 笼统地说“可组合”。

我们尚未定义：

- objects 和 morphisms；
- identity；
- composition operator；
- associativity；
- monoidal product；
- functorial semantics。

### 5.2 未来可能的正确用途

范畴论适合审计 **开放系统组合是否保持语义**，而不是直接作为 Python runtime API。

可能的映射是：

```text
object       = typed protocol boundary / port set
morphism     = open protocol network from input boundary to output boundary
composition  = glue compatible boundaries
tensor       = disjoint parallel composition
semantics    = network → accepted traces / reachability relation
```

真正需要证明的是：

\[
Semantics(B \circ A)=Semantics(B) \circ Semantics(A)
\]

开放 Petri 网通过 cospan、对称幺半双范畴和函子语义给出了这种组合的严谨实例。[Baez & Master, *Open Petri Nets*](https://arxiv.org/abs/1808.05415)

建议：在 Link/Port/Bridge 已实现且有两个以上组合案例前，不把范畴论放进核心实现承诺。

## 6. 关系代数、偏序和 trace 理论

### 6.1 偏序与拓扑排序

这是当前利用最充分的部分：

- DAG 直接边；
- reachability 作为严格 happens-before；
- 反自反和环拒绝；
- incomparability/concurrency；
- ancestor；
- topological order 作为一个 linear extension。

但 `CausalGraph.concurrent()` 目前只表示不可比较，不证明语义独立；文档对此区分是正确的。

### 6.2 Mazurkiewicz trace/pomset

理论上，若独立关系 `I` 满足某些动作可以交换，则 word 在相邻独立动作交换生成的等价关系下形成 trace。Trace theory 正是为了协调线性观察和非线性因果，可等价地从字符串的部分交换或带标签偏序图理解。[Mazurkiewicz, *Theory of Traces*](https://doi.org/10.1016/0304-3975(88)90051-5)

当前代码没有：

- `IndependenceRelation`；
- dependence alphabet；
- word quotient；
- canonical normal form；
- 相邻独立事件交换后 verdict 不变的性质测试；
- 验证一个 trace 是否是同一 pomset 的 linearization。

因此目前是“偏序 trace 容器”，还不是 trace theory engine。

### 6.3 关系代数/Kleene Algebra with Tests

若把事件转换视为状态关系：

```text
choice       = relation union
sequence     = relational composition
guard        = identity relation restricted by predicate
repeat       = reflexive transitive closure / Kleene star
```

那么 Scenario DSL 和 protocol path grammar 可以采用 KAT。KAT 把正则代数与布尔 tests 结合，并有 relational、language 和 trace model，以及等式推理与可判定性结果。[Kozen, *Kleene Algebra with Tests*](https://www.cs.cornell.edu/~kozen/Papers/kat.pdf)

当前 `EventSpace` predicates 和 Project case 顺序只是具备这种解释潜力，并没有实现代数运算或使用任何 KAT 定理。

建议把 KAT 用于未来 Scenario/phase expression：

```text
setup ; wait* ; complete
(read + write) ; response
guard(has_credit) ; issue
```

不要用关系代数替代携带丰富 token 的 Petri 网，也不要用它替代 partial-order execution。

## 7. 推荐的理论分工

不要追求“一种数学统一一切”。推荐每层选择最合适的理论：

| 工程层 | 主理论 | 用途 |
|---|---|---|
| Protocol/Port | I/O automata | input/output ownership、compatibility、refinement |
| resource/obligation | colored Petri net | token、credit、cardinality、deadlock |
| finite execution | event structure/pomset/trace theory | causality、conflict、independence、linearization |
| stateful VirtualDut | Hoare-style contracts | pre/post、功能状态不变量 |
| temporal properties | monitor automata，后续 LTL/TLA | safety、deadline、liveness、公平性 |
| Scenario expression | KAT/regular algebra | sequence、choice、guard、repeat |
| open network composition | category/open systems（后期） | 边界粘合、组合律、语义保持 |

## 8. 下一步：从“相似”变为“基于”

### M1：自动机脊柱（已完成首版）

当前已经实现：

```text
ProtocolSpec = (States, Inputs, Outputs, Internal, Init, Transition)
ProtocolSession = one runtime state of ProtocolSpec
```

`SemanticComponent` 已统一 signal、transaction 和 session 的 step 语义；`PortSpec` 已声明，
但 output ownership 和自动 routing 仍待 Project topology elaboration。

### M2：将 obligation/resource 改为 multiset token model

- 重复 key 不会被一次 response 全部删除；
- cardinality 是显式弧权；
- 检查 token conservation invariant；
- bounded configuration 可探索 deadlock。

### M3：补齐 true-concurrency 对象

```text
causality ≤
conflict #
independence I
configuration
linearization
```

加入性质测试：所有合法 linearization verdict 相同，交换独立相邻事件不改变最终状态。

### M4：属性语言

先定义有限 trace safety/obligation property；之后再决定是否嵌入 LTLf、调用外部 model checker，或导出 TLA+。

### M5：组合律

为 Port/Link/Bridge 定义 identity、sequential composition 和 parallel composition，并通过测试验证 associativity。只有到这里，才有理由声称范畴化组合影响了实现。

## 9. 最终判断

当前项目的创新不在发明新数学，而可能在于：

> 把自动机、token/resource、partial-order trace、虚拟 DUT 和 UVM evidence 组织成一个工程师可执行、可诊断的统一工作流。

这个“组织方式和诊断工作流”可以是项目自己的贡献；底层数学应尽量回到已有理论，以获得正确性、组合性和现成算法，而不是重新发明一个没有证明的近似版本。
