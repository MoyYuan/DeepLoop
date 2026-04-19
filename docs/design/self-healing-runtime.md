# Self-healing runtime

DeepLoop should not stop at a raw stage failure if a bounded recovery or reroute is available.

## Goal

Provide a deterministic wrapper around stage kernels that can:

1. resume from existing manifests
2. classify technical failures
3. apply bounded fallback edits
4. reroute blocked stages to prerequisites
5. write durable recovery artifacts and ledger entries

## Current bounded scope

The first implementation is intentionally narrow:

- wraps stage-kernel execution
- retries at most a fixed number of times
- supports backend fallback repair for unsupported or dependency-missing model backends
- records blocked prerequisite states for stages like causal intervention
- preserves recovery history for later packaging

This is not yet a full long-horizon autonomous debugger. It is the runtime-safe first layer.

## Durable artifacts

For each wrapped stage run, DeepLoop writes:

- `recovery-report.json`
- `recovery-history.jsonl`

These live under the stage output directory in `runtime_recovery/`.

## Recovery rules

- **resume**: if the expected manifest already exists, return the existing stage result
- **fallback-backend**: patch the stage config to a deterministic fallback backend and retry
- **reroute-prerequisite**: do not retry; record that a prerequisite stage must be satisfied first
- **stop**: persist failure and stop the bounded loop
