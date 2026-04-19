# AGENTS.md

Contract for future agents working on `deeploop`.

## Project overview

- Purpose: define the control-plane contracts for autonomous research in the
  local workspace
- Primary modes:
  - **sandboxed-yolo**: default autopilot-like mode inside explicit sandbox and policy gates
  - **managed**: expert mode with broader permissions and intervention hooks
  - **human-directed**: humans approve designs and major changes
- Default environment name: `deeploop`

## Environment rules

- Use `environment.yml` for planning/control-plane work.
- Use `environment.llm.yml` for real local inference work when a mission or
  runtime policy resolves `env_name: llm`.
- Do not install into system Python.
- Prefer deterministic execution with `conda run -n deeploop <command>`.
- Prefer deterministic inference execution with `conda run -n llm <command>`
  once the local inference env is provisioned.
- Keep data, checkpoints, runs, and scratch outputs outside the repo.
- Do not assume GitHub-hosted agents can see `~/workspaces`; local-only paths stay
  scoped to the local workspace.
- DeepLoop-spawned agents must ingest rules in order:
  1. machine-wide rules
  2. DeepLoop shared rules
  3. target-repo local rules

## Stable commands

- Setup: `make setup`
- Repo contract validation: `make repo-check`
- Tests: `make test`
- Smoke manifest: `make smoke-manifest`

## Policy placement hierarchy

When deciding where a new rule or abstraction belongs:

1. machine-wide stable defaults:
   - `~/.copilot/copilot-instructions.md`
   - `~/workspaces/AGENTS.md`
2. DeepLoop shared control contracts:
   - `configs/`
   - `schemas/`
   - `docs/design/`
3. repo-specific overrides:
   - target repo `AGENTS.md`
   - target repo `.github/copilot-instructions.md`
   - target repo `configs/`
4. deterministic implementations:
   - repo scripts / Make targets
5. integrations:
    - MCP only when local and GitHub-native tooling are insufficient
    - skills only for repeated high-level workflows that deserve a named interface

## Mandatory experiment ledger

- Every non-trivial experiment, inference run, and promoted findings summary
  must be:
  - manifest-linked
  - metrics-linked where applicable
  - recorded in durable mission or findings artifacts
- Shell output alone is never the system of record.

## Optimization policy

- Do not guess inference or training settings from memory when a profile can be
  resolved from `configs/execution-profiles/`.
- Use resource tiers from `configs/resource-tiers/tiers.yaml`.
- If a job OOMs or is unstable, follow the documented fallback ladder and record
  the downgrade in the run manifest.
- Treat throughput, peak VRAM, crash rate, and reproducibility as first-class
  signals, not afterthoughts.

## Autonomy policy

- Honor `configs/autonomy/gates.yaml` before launching long or expensive jobs.
- Do not promote findings to paper-candidate status without meeting the evidence
  requirements.
- Do not mutate evaluation metrics or benchmark definitions silently.
- Do not create public-facing artifacts unless the gate policy allows it.
- Prefer sandboxed or isolated per-agent execution whenever possible.
- Treat full host-level access as the exception, not the default, for spawned agents.

## Current non-goals

- Do not pretend the highest-autonomy runtime already exists.
- Do not invent hidden memory stores or services that are not registered in mission artifacts.
- Do not overwrite repo-specific scientific contracts in the substrate labs.
