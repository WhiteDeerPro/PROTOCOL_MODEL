# Contributing to Protocol Model

Protocol Model is currently a pre-1.0 technical preview. Small, reviewable
contributions are especially useful: correcting one protocol requirement,
adding one reproducible scenario, or making one generated view easier to
understand. You do not need to understand the whole architecture first.

## Good contribution paths

| Perspective | A useful first contribution | Evidence to include |
|---|---|---|
| Protocol engineer | Correct a rule, profile boundary, or counterexample | Specification document, revision and section; a short paraphrase of the requirement |
| Verification engineer | Add one deterministic legal or expected-violation scenario | Input, expected verdict/rule, observed verdict/fault, waveform and causal graph |
| Documentation or visualization contributor | Improve navigation, terminology, waveform layout, graph labels, or accessibility | Before/after intent and the named generator used to rebuild the asset |

Use the two focused GitHub issue forms to discuss a requirement correction or
scenario before making a larger change. A narrowly scoped pull request is also
welcome when the intended result is already clear.

## Local setup

The Python package requires **Python 3.10 or newer**. The showcase renderers
also use the repository-pinned WaveDrom package and the Graphviz `dot` command.

```bash
python3 --version
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
npm ci
dot -V
```

`npm ci` installs the pinned WaveDrom dependency from `package-lock.json`.
Graphviz is a system dependency and must be installed separately if `dot -V`
is unavailable.

Run the unified AXI4 introduction from the repository root:

```bash
python3 showcase/demos/axi4/run.py
```

This is an explicit publication command: it may replace the generated subtree
owned by that demo. Do not edit generated SVG, Markdown, JSON, WaveJSON, or DOT
files by hand; edit their source or renderer and run the named generator.

## Scenario contract

Every public scenario should remain a small, inspectable statement with one
primary learning goal. Its generated evidence must keep these views connected
to the same execution:

1. deterministic inputs and the applicable protocol/profile;
2. an **expected** verdict and, for an expected violation, the expected rule;
3. the **observed** verdict and fault/rule produced by the current model;
4. a model-generated waveform, with its WaveJSON or equivalent source;
5. a causal graph, with its DOT or equivalent source;
6. provenance sufficient to reproduce the result.

`PASS` and `FAIL` describe the scenario's protocol verdict. A runner succeeds
when observed evidence matches the declared expectation, so a deliberately
invalid scenario that observes the expected `FAIL` is a successful
reproduction—not a protocol pass. Do not add a second checker inside showcase
code merely to make the expected and observed columns agree.

Ordinary scenarios need only a concise navigation entry. Add longer prose or
step-by-step figures when a case introduces a new semantic boundary, an
unfamiliar relation, or a diagnosis that is otherwise hard to read.

## Risk-matched validation

Validate the path you changed rather than using test volume as evidence of
architectural progress.

- For a scenario or renderer change, run the unified AXI4 command and inspect
  the affected waveform, causal graph, machine result, and navigation entry.
- For protocol runtime changes, run the relevant focused `unittest` modules in
  `tests/`, then run the affected named showcase generator.
- For documentation-only changes, check links and terminology in the pages you
  touched; regenerate an asset only when its source changed.

Do not restore or run the retired v0.1 regression for a current-architecture
change. In a pull request, list the directed commands you ran and the evidence
you inspected.

## Protocol and documentation claims

Protocol specifications remain the authority. For a requirement correction,
name the document, revision and section, paraphrase the relevant rule, and
avoid pasting long copyrighted extracts. State the applicable profile and
whether the point is a protocol requirement, an architecture boundary, or a
current implementation choice.

Executable scenarios are evidence for those inputs and the modeled boundary.
They are not, by themselves, proof of RTL behavior or clause-by-clause
specification compliance. Scenario counts describe the breadth of the public
examples, not specification coverage. Keep **current implementation**,
**proposed work**, and **research questions** visibly separate, and avoid broad
comparative claims that cannot be traced to a case, constraint, or status page.

The repository working agreement in [`AGENTS.md`](AGENTS.md) gives the current
layering, output, and documentation rules. Architecture definitions belong in
[`docs/architecture`](docs/architecture/README.md); publication-ready assets
and text belong under [`showcase`](showcase/README.md).

## Pull request shape

Keep each pull request centered on one reviewable change. Include:

- what protocol/profile or presentation boundary changed;
- why the new behavior or wording is preferable;
- the directed commands run and relevant generated artifacts;
- remaining limitations or follow-up work.

Do not mix unrelated compatibility layers, broad formatting rewrites, or
generated-file edits into a requirement or scenario contribution.
