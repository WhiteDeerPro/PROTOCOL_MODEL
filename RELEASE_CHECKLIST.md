# Release checklist

This checklist prepares a public GitHub release without making the commit, tag, push, or GitHub Release on
behalf of the maintainer. The candidate version is **0.3.0**.

## Source and metadata

- [ ] Review the complete staged diff; distinguish the intended v0.1 retirement from accidental deletion.
- [ ] Confirm `protocol_model.__version__`, `pyproject.toml`, `CHANGELOG.md`, and the release title all say
      `0.3.0`.
- [ ] Confirm the MIT copyright holder and repository URLs are the intended public identities.
- [ ] Decide whether the distribution name `protocol-model` should also be reserved/published on PyPI; a
      GitHub source release does not require PyPI publication.
- [ ] Confirm the tracked `.vscode` tasks use current public entry points rather than retired v0.1 CLI commands.

## Reproducible public evidence

- [ ] Run each named showcase generator with the documented Python/Node/Graphviz versions.
- [ ] Confirm every published scenario links to its waveform, causality graph, source IR, result, and
      provenance; inspect the small set of expanded examples visually.
- [ ] Confirm the AXI4 set publishes one shared topology image rather than duplicating identical topology per
      case; coverage and evidence-path diagrams must not be labelled as additional topologies.
- [ ] Check that generated manifests report the expected model version and that generators only replace their
      owned subtree under `showcase/generated/`.
- [ ] Run risk-matched directed checks for the current architecture. Do not restore or run the retired v0.1
      regression merely to increase the test count.

## Package and clean-clone check

- [ ] Build both source and wheel distributions in a clean environment with Python 3.10 or newer.
- [ ] Install the wheel into another clean environment and run `python -m protocol_model` plus one documented
      showcase command.
- [ ] Run `npm ci` and check that the documented `dot`/WaveDrom commands work without relying on a developer's
      existing `node_modules/`, `.venv/`, or absolute paths.
- [ ] Check Markdown links and the selected SVG/PNG assets from a clean clone on a case-sensitive filesystem.

## Public repository review

- [ ] Scan tracked files for credentials, personal paths, private email addresses, unpublished customer/IP
      names, and generated traces that should not be public.
- [ ] Review large files and binary assets; keep only deliberately published showcase images.
- [x] Provide [`CONTRIBUTING.md`](CONTRIBUTING.md) and focused issue forms for protocol requirement corrections
      and scenario contributions.
- [ ] Decide whether the public preview needs `CODE_OF_CONDUCT.md`, `SECURITY.md`, and minimal CI. These remain
      deliberately pending rather than being implied by the contribution guide; record the release-time
      decision in the GitHub Release notes.
- [ ] Confirm the known limitations in [`docs/releases/0.3.0.md`](docs/releases/0.3.0.md) still match the code.

## Maintainer-controlled publication

- [ ] Create a focused release commit after the working tree has been reviewed.
- [ ] Tag the reviewed commit as `v0.3.0` and push only after maintainer approval.
- [ ] Create the GitHub Release from [`docs/releases/0.3.0.md`](docs/releases/0.3.0.md); attach source/wheel
      artifacts and their checksums if package artifacts are being distributed.
- [ ] Re-run the unified AXI4 example set from the public tag and record any first-user friction as an issue rather than
      silently changing the published artifacts.
