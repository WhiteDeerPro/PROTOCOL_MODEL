# Protocol Model: From Bus Rules to Explainable Micro-Systems

We are preparing the first technical preview of Protocol Model and have completed its first executable slice. It is a
compositional semantic modeling and verification research prototype for on-chip communication. The project asks whether protocol rules, scenario generation, runtime
checking, and diagnostic evidence can share one construction path instead of re-encoding the same relationships in
drivers, monitors, assertions, reference models, and reports.

**CURRENT — what exists today.** The main line builds LinkProtocol models from typed events, constraints, resources,
and reusable patterns, then attaches those protocols to named VirtualDut modules through typed ports. Its current AXI4
scope includes bursts, narrow and unaligned transfers, read interleaving, AW/W/B correlation, link-local exclusive
eligibility, and state-driven generation. The repository also contains synchronous SystemProtocol execution,
AXI4-to-APB bridge witnesses, causal-graph support, and managed artifact storage. Other executable AMBA work includes
AXI4-Lite, AXI4-Stream, AHB-Lite/AHB5 profiles, APB3/4/5, and an ACE-Lite ordinary-data subset.

Those are scoped engineering results, not a claim of complete AXI compliance, arbitrary RTL verification, automatic
construction of every bridge, or a formal proof system. Raw VCD/FST, simulator adapters, a requirement-by-requirement
catalog, and asynchronous network progress remain outside the current public path.

**CURRENT — one introduction set.** Twenty-four named AXI4 scenarios span lifecycle, geometry,
ordering/interleave, observation/reset, and exclusive/profile themes. Ten legal inputs and fourteen expected violations
all met their declarations. Every case includes its goal, verdict, model waveform, causal graph, and machine-readable
result. Scenario count is not presented as specification coverage.

**CURRENT — focused entries in the same set.** The four-beat narrow/unaligned INCR write and the first-beat `WLAST`
violation add step-by-step explanation within those 24 scenarios. Six frame-input cases use `AtomicFrame` waveforms
with `ARESETn`, while eighteen event-input cases use clearly labelled `CanonicalEvent` sequences; the two deep dives
belong to the former group. Both are model projections rather than RTL/VCD.

**PROPOSED — the next story.** A second story will connect an AXI4 requester, a
bridge VirtualDut, and an APB4 memory/register endpoint to explain burst splitting, AW/W joining, completion folding,
route misses, and serial capacity.

We are looking for protocol engineers, verification engineers, and visualization contributors who are willing to
challenge the method rather than endorse a slogan. Does a shared construction actually reduce semantic drift between
generators, monitors, and reports? Which AXI corner cases deserve a public, teachable scenario? A useful first
contribution can be one requirement correction, one replayable case, or one clearer diagram.

Read more: [unified AXI4 examples](../generated/axi4/README.en.md) · [project one-pager](one-pager.en.md) · [demo editorial strategy](../strategy/demo-program.md) ·
[claims and evidence](../strategy/claims-and-evidence.md)
