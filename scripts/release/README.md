# Release scripts

Release validation now has a repo-owned Docker clean-room harness.

## Canonical entrypoints

- `python scripts/release/docker_validation.py validate-dist`
- `make docker-release-validate`
- `python scripts/release/docker_validation.py validate-pypi --install-spec deeploop==<version>`
- `make docker-release-validate-pypi VERSION=<version>`
- `python scripts/release/real_runtime_validation.py --manual-note '...proof boundary note...' --lane-note 'local-qwen-openai-compatible=...host setup note...' --lane-note 'copilot-cli-gpt-5-mini-coding-agent=...auth note...'`

## Gate mapping

- **Gate 1** baseline release proof:
  - `python scripts/release/docker_validation.py validate-dist`
  - `make docker-release-validate`
  - `python scripts/release/docker_validation.py validate-pypi --install-spec deeploop==<version>`
  - `make docker-release-validate-pypi VERSION=<version>`
- **Gate 2** real-runtime release proof:
  - `python scripts/release/real_runtime_validation.py ...`

Gate 1 proves the clean-room install/bootstrap story. Gate 2 proves the current
approved real LLM-backed runtime lanes. Provider-free smoke, provider-ready
checks, and Docker bootstrap validation do **not** replace Gate 2.

## What the Docker harness proves today

The current harness is intentionally deterministic and provider-free:

1. build the sdist and wheel inside `docker/release-validation.Dockerfile`
2. install the built wheel in a fresh runtime image
3. verify the shipped `deeploop run`, `provider-ready`, `status`, `inbox`, and `resume` surfaces respond
4. walk the zero-start `deeploop run --until-complete` path, select a non-default bundled starter from the installed package, materialize the starter project under the workspace, and confirm DeepLoop stops before kickoff with one provider-readiness next step plus resume/recheck commands
5. bootstrap the canonical `examples/translation-budget-ladder/` plain-folder example and confirm the generated mission state lands under the configured DeepLoop workspace root without mutating the project copy
6. bootstrap the non-translation `literature-gap-map` proof fixture and verify it surfaces the expected blocked operator-readiness contract
7. package that initialized literature mission to prove the release artifact still exposes the lightweight packaging surface cleanly
8. bootstrap the messy-start `forecast-rough-notes` fixture and verify the bounded clarifications/defaults handoff still packages cleanly
9. rerun that messy-start fixture through `--discover` to keep the discovery-first onboarding path honest
10. verify a partial project-folder `deeploop run --project-root ... --until-complete` stops with bounded repair guidance instead of mutating the input project
11. render the `status` / `inbox` / `resume` operator loop from a representative paused mission snapshot so the documented handoff stays honest even before the Docker lane proves a real runtime pause

The separate real-runtime release signoff lanes are defined in
`configs/runtime/gate-2-runtime-lanes.yaml`. In the current approved phase that
means local Qwen via the OpenAI-compatible lane plus Copilot CLI with `gpt-5-mini`
for the coding-agent lane, with durable mission/runtime artifacts recorded for
both.

The repo-owned Gate 2 harness is `scripts/release/real_runtime_validation.py`.
It bootstraps a fresh copied project for each approved lane, checks provider
readiness without hiding the manual/auth boundary, runs the lane-specific real
runtime surface, and writes durable JSON/Markdown evidence under the configured
workspace release-validation root.

Canonical release-signoff shape:

```text
python scripts/release/real_runtime_validation.py \
  --validation-id <release-id> \
  --operator <operator> \
  --machine-label <machine> \
  --manual-note "fresh env + documented install path used for Gate 2" \
  --lane-note "local-qwen-openai-compatible=host-local Qwen/OpenAI-compatible server was started outside DeepLoop" \
  --lane-note "copilot-cli-gpt-5-mini-coding-agent=machine was already authenticated for Copilot CLI before the run"
```

The durable proof bundle lives under the default evidence root from
`configs/runtime/gate-2-real-runtime-validation.yaml`:

```text
~/workspaces/runs/deeploop/release_validation/gate-2/<validation-id>/
```

Review at least:

- `gate_2_real_runtime_validation.json`
- `gate_2_real_runtime_validation.md`
- `<lane-id>/validation_record.json`
- `<lane-id>/validation_record.md`

Those files are the durable release proof. Do not rely on shell output alone.

`validate-pypi` reuses the same smoke helper after install from PyPI so the
post-publish check exercises the published artifact instead of the local wheel.

## Non-goals

- this is not a devcontainer or full interactive development image
- this does not replace the documented conda/uv workflows for contributors
- this does not yet prove provider-backed execution inside Docker; extend the
  in-container smoke helper only when the provider contract is ready to be
  documented and tested cleanly
- the `status` / `inbox` / `resume` handoff check currently validates the
  released operator surfaces on a representative paused mission snapshot, not a
  real provider-backed runtime pause
