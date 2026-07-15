# AXI4 executable example source

This is the single source and runner for the public AXI4 introduction. It
contains 24 named scenarios organized by semantic theme:

- `cases/lifecycle.py`: request, join, completion, and orphan behavior;
- `cases/geometry.py`: 4KB, FIXED/WRAP, narrow, and byte-lane geometry;
- `cases/ordering.py`: cross-ID interleave and same-ID ordering;
- `cases/observation.py`: `AtomicFrame`, ready/valid, and reset;
- `cases/exclusive_profile.py`: exclusive access and bounded resources.

`write-narrow-unaligned-incr` and `write-early-wlast` are the two narrated
deep dives. They are not extra scenarios: `hero_cases.py` replaces the two
equivalent catalog inputs with richer `AtomicFrame` observations before the
same executor runs them. The total remains 24.

The executor calls the repository's `LinkSession` or
`Axi4ObservationSession`; there is no example-specific AXI checker. The
presentation code derives JSON, waveforms, and causality graphs from those run
results. Event-level waveforms explicitly represent sequential
`CanonicalEvent` inputs, while frame-level waveforms project ready/valid lanes
and AXI `ARESETn`.

Run from the repository root with Python 3.10 or newer:

```bash
python3 showcase/demos/axi4/run.py
```

Graphviz `dot` and the repository's WaveDrom dependency are required. The
runner stages the complete publication before atomically replacing only
`showcase/generated/axi4/`; it does not use `out/`.

Each case owns exactly these primary artifacts:

- `cases/<name>/result.json`
- `cases/<name>/waveform.svg`
- `cases/<name>/causality.svg`

Their WaveJSON and DOT sources are retained under `sources/cases/<name>/`.
The full set shares one `topology.svg`; `evidence-path.svg` explains the
projection path and is not a second topology. The generated bilingual README
is the public navigation page. Expected `FAIL` scenarios are successful model
evidence when the observed rule matches the scenario declaration.

Scenario count reports executable examples, not AXI4 specification coverage
or RTL compliance.
