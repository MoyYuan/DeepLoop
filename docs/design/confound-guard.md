# Confound / contamination / comparability guard

DeepLoop now has a dedicated deterministic guard for invalid comparisons and
suspicious study setups.

## Purpose

The guard is narrower than a full reviewer. It exists to stop promotion or
execution when DeepLoop can already tell that a comparison is contaminated,
confounded, or weakly anchored.

The current contract checks for:

- prompt / parser mismatches against registered templates or reference manifests
- missing or drifting evaluation anchors in follow-up configs
- unfair runtime fallback surfaces when manifests reveal different execution modes
- weak follow-up references such as analysis-prep placeholders instead of real evidence
- manifest comparability mismatches across candidate comparisons

## Contract

The machine-readable policy lives at `configs/autonomy/confound-guard.yaml`.

It is substrate-aware for the first target, translation pilot, and currently covers:

- `baseline-eval`
- `mechanistic-localization`
- `causal-intervention`

## Runtime integration

- module: `src/deeploop/research/confound_guard.py`
- standalone runner: `scripts/runtime/run_confound_guard.py`
- sanity-gate integration: `src/deeploop/research/sanity_gates.py`
- durable artifacts:
  - mission-linked: `~/workspaces/runs/deeploop/missions/<mission_id>/confound_guard/`
  - standalone: `~/workspaces/runs/deeploop/confound_guard/`
- ledger integration:
  - `confound-guard` entries capture verdicts and reasons
  - `research-sanity-gate` entries link back to confound artifacts

## translation pilot behavior

The first concrete behavior is intentionally conservative:

- real baseline manifests are accepted as usable references
- mechanistic follow-up prep can proceed when it stays anchored to a real baseline
- intervention prep is blocked when its localization source is only an
  `analysis-prep` placeholder or when its comparison set is visibly not
  comparable enough to trust
