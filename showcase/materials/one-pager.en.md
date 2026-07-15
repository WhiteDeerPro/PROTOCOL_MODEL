# Protocol Model

## From bus rules to explainable micro-systems

**Protocol Model is a compositional semantic modeling and verification research prototype for on-chip communication.**
It explores whether protocol rules, scenario generation, runtime checking, and diagnostic evidence can share one
construction path instead of re-encoding the same knowledge in drivers, monitors, assertions, reference models, and
reports.

### What problem does it address?

The difficult parts of an on-chip protocol such as AXI are rarely isolated fields. They are relationships across
channels, transactions, and modules: how AW, W, and B belong to one write lifecycle; how responses with different IDs
may interleave; or how a burst is split, scheduled, and completed across a bridge. Existing verification workflows can
handle these questions, but the same relationship often appears in several tools and gradually stops meaning exactly
the same thing.

Protocol Model starts with small communication facts and builds upward:

```text
events, relations, and resources
        ↓ compose and refine
LinkProtocol: the language allowed on one logical connection
        ↓ bind to named module ports
VirtualDut: communication-relevant behavior of one virtual module
        ↓ connect and add global contracts
SystemProtocol: a communication system of links and modules
        ↓ observe, execute, and project
replayable scenarios, waveforms, causality, and diagnostics
```

### What exists today?

The current source tree includes compositional semantic units, an `AtomicFrame` observation boundary, ready/valid and
reset handling, and LinkProtocol implementations for AXI4, AXI4-Lite, AXI4-Stream, AHB-Lite/AHB5 profiles,
APB3/APB4/APB5, and an ACE-Lite ordinary-data subset. Non-trivial AXI4 behavior in the current scope includes bursts,
narrow and unaligned transfers, read interleaving, AW/W/B correlation, link-local exclusive eligibility, and
state-driven generation.

The project also provides named `VirtualDut` modules, typed protocol ports, AMBA attachments, address-space endpoints,
synchronous `SystemProtocol` sessions, and bridge witnesses including AXI4-to-APB. A typed transaction translation kernel
already models operation signatures, stage contracts, plan closure, fan-out lifecycle, and serial capacity leases. The
existing full-AXI bridge is still being migrated onto that shared kernel.

These are **engineering results within the current implementation boundary**. They are not evidence of complete AXI
compliance, arbitrary RTL verification, or a formal proof system.

### How does the public story balance breadth and understanding?

The technical preview is organized in two stages. The first has public executable evidence; the second has a bounded
bridge witness today, while its presentation entry is still planned:

1. **One AXI4 introduction set (CURRENT)** — 24 executable scenarios grouped by lifecycle, geometry,
   ordering/interleave, observation/reset, and exclusive/profile behavior. Every case includes a goal, verdict, model
   waveform, causal graph, and machine-readable result. The four-beat narrow/unaligned INCR write and the first-beat
   `WLAST` violation add step-by-step narration while remaining in the same set.
2. **AXI4-to-APB micro-system (PROPOSED presentation)** — a planned story around the current bounded witness, with a
   requester, bridge, and memory/register endpoint connected by two links to show burst splitting, AW/W joining,
   completion folding, route misses, and serial capacity.

The unified navigation first answers “which behaviors are represented,” then lets readers inspect any case; two focused
entries answer “how do I read this evidence?” The bridge story will then test whether the method can explain behavior
across a link boundary clearly.
Scenario count shows breadth but does not replace a requirement catalog. Crossbars, raw RTL/VCD adapters, and
wait-for/deadlock analysis are later milestones rather than launch prerequisites.

### Why is this worth testing together?

The project poses three testable questions rather than assuming their answers:

- Can one compositional protocol construction serve generators, monitors, and evidence while reducing duplicated
  knowledge?
- Can typed operations and translation stages move bridge reuse from protocol-pair code toward codecs plus semantic
  stages?
- Does the LinkProtocol / VirtualDut / SystemProtocol scope split make link-local and network-level responsibilities
  easier to audit?

Answering these questions requires protocol engineers, verification engineers, RTL integrators, and visualization
contributors to supply counterexamples, requirement corrections, and real use cases. The project is currently a
**technical preview with an executable first slice**: scan one 24-case navigation, inspect the waveform
and causal graph for any case, or follow the two focused explanations in depth, then help refine requirements, the bridge
presentation, and the external-DUT path.

Read more: [architecture map](../../docs/architecture/technical-route/README.md) ·
[current implementation boundary](../../docs/architecture/implementation-status.md) ·
[unified AXI4 examples](../generated/axi4/README.en.md) ·
[release notes](../../docs/releases/0.3.0.md)
