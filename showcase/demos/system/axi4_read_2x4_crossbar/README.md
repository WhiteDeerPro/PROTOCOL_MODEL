# AXI4 read 2×4 crossbar demo

This example instantiates the parameterized AXI4 read-only AR/R crossbar with
two manager-facing ingress ports and four subordinate-facing egress ports:

```text
manager0 ─┐                 ┌─ target0 RAM · 0x1000
          ├─ AXI4 AR/R 2×4 ├─ target1 RAM · 0x2000
manager1 ─┘    crossbar     ├─ target2 RAM · 0x3000
                            └─ target3 RAM · 0x4000
```

The execution covers three relationships that a single-ingress demux cannot
demonstrate:

- two managers use the same RID at one target; the pending-read ledger restores
  responses to managers in downstream acceptance order;
- the same RID on different manager ports remains independent and may complete
  from different targets in either order;
- one manager cannot redirect an active RID to another target until its prior
  `RLAST` retires the destination lock.

Run from the repository root:

```bash
python3 showcase/demos/system/axi4_read_2x4_crossbar/run.py
```

Use `--publish-root <directory>` for a scratch publication.  The stable run
publishes topology, model-step WaveDrom, causal graph, machine-readable state,
provenance, and manifest beneath
`showcase/generated/system/axi4-read-2x4-crossbar/`.

The current `raw-ID-serialized` profile supports ordinary `lock=0` reads.
Source-qualified exclusive identity and optional downstream ID prefix/remap are
separate profiles to add later.  The model consumes accepted transactions; it
does not prescribe a pin-level arbitration or timing implementation.
