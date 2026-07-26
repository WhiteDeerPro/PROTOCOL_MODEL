# AXI4 single-manager read-demux demo

This example executes the currently supported Full AXI4 fabric slice:

```text
scenario-driven manager
          |
          v
AXI4 AR decoder / RID owner table / R return mux
          |                         |
          v                         v
     target0 RAM               target1 RAM
```

The scenario deliberately separates two ordering cases:

1. RID 1 and RID 2 access different targets.  Target 1 is serviced first, so
   the later RID 2 response returns before RID 1.  This is legal because the
   IDs are independent.
2. RID 3 first accesses target 0 and then attempts to access target 1.  The
   second AR is blocked by the fabric's destination lock.  It succeeds when
   retried after the first transaction's `RLAST` releases the table entry.

Run from the repository root:

```bash
python3 showcase/demos/system/axi4_single_manager_read_demux/run.py
```

Use `--publish-root <directory>` to build a scratch publication without
changing the maintained `showcase/generated/` tree.  The publication contains
the canonical system topology, a WaveDrom model-step view, the recorded causal
graph, machine-readable results, provenance, and a manifest.

This is a one-manager, read-only `AR/R` fabric slice.  It is not yet an AXI4
N-by-M crossbar, an `AW/W/B` fabric, a pin-level waveform generator, or an RTL
microarchitecture prescription.
