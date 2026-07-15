# Project overview artwork

This directory contains the hand-authored, presentation-oriented overview of Protocol Model:

- [`protocol-model-overview.zh.svg`](protocol-model-overview.zh.svg) — Chinese;
- [`protocol-model-overview.en.svg`](protocol-model-overview.en.svg) — English.

Web-uploadable derivatives are available as
[`protocol-model-overview.zh.png`](protocol-model-overview.zh.png) and
[`protocol-model-overview.en.png`](protocol-model-overview.en.png). The SVGs remain the maintained sources.

The two files are self-contained 1600 × 900 SVGs. They use only system fonts and SVG primitives, so they can be embedded in
a project page, article, slide deck, or social post without a build step. They are intentionally separate from
`docs/architecture/technical-route/overview.svg`: that document is a detailed navigation map, while these assets are a
single-slide explanation for readers who do not yet know the project's terminology.

## Narrative and claim boundary

The image follows one reading path:

```text
common verification friction
  → separate link rules, module behavior, and system composition
  → reconnect them through explicit port/translation boundaries
  → run a scenario and project waveform, path, and causal evidence
  → state the current implementation boundary
```

The artwork describes Protocol Model as a research prototype and a model-level communication-semantics workbench. It does
not claim RTL sign-off, complete protocol compliance, a finished protocol-independent bridge executor, or finished
network-scale time/deadlock analysis.

## Maintenance

- Keep the Chinese and English layouts structurally aligned; wording may differ to remain natural in each language.
- Prefer plain-language questions in the main reading path. Keep project-specific type names in secondary labels or nearby
  documentation.
- Update the “demonstrable today” and “under construction” sections only after the corresponding scenario or artifact can
  substantiate the claim.
- These are manually authored explanatory illustrations, not output from a model run. Scenario-derived waveforms, network
  paths, and causal graphs should record their generator command and source scenario separately.

To rebuild both 1600 × 900 PNGs explicitly:

```bash
python3 showcase/materials/assets/overview/render_png.py
```

The script requires Firefox, renders into a temporary staging directory, checks the PNG dimensions, and only then
replaces the two derivatives. Treat the SVGs as the maintained source.
