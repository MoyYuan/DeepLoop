# DeepLoop stage kernels

DeepLoop now owns the primary runnable kernels for substrate study stages.

## Registry

The machine-readable registry lives at:

- `configs/runtime/stage-kernel-registry.yaml`

Current registered kernels:

1. `baseline-evaluation`
2. `prompt-decode-sweep`
3. `mechanistic-localization`
4. `causal-intervention`

## Adapter contract

DeepLoop kernels do not hard-code substrate facts. Instead, a substrate adapter
supplies:

- promoted-dataset manifest loading and slice resolution
- prompt formatting and label parsing
- metric aggregation
- substrate repo identity and run-root locations

This keeps prompts, metrics, dataset facts, and study contracts in the
substrate repo while moving the generic runnable behavior into DeepLoop.

## Execution semantics

- `baseline-evaluation` is the full generic baseline runner.
- `prompt-decode-sweep` is the shared prompt/decode runtime for benchmark-bound
  prompt ladders, baseline-anchor replays, and promotion decisions.
- `mechanistic-localization` is a runnable deterministic proxy kernel. It emits
  localization observations, ranked candidate units, a study summary, and a
  DeepLoop-owned manifest instead of only preparing a bundle.
- `causal-intervention` is a runnable deterministic proxy kernel. It consumes
  localization output, emits post-intervention predictions and metrics, and
  keeps blocked semantics only when the required upstream localization artifact
  is missing.

These proxy kernels are intentionally bounded. They are the new DeepLoop-owned
runnable paths until model-internal localization/intervention execution is
added.

## Direct CLI surface

DeepLoop exposes a generic runner at:

- `scripts/runtime/run_stage_kernel.py`

Substrates may keep thin wrappers for compatibility, but those wrappers should
call into the registry rather than re-implement the generic stage behavior.
When they need a stable machine interface, prefer
`scripts/runtime/run_stage_kernel.py --json` instead of importing
`deeploop.runtime.stage_kernels` directly.
