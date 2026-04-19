# Statistical rigor layer

DeepLoop now has a deterministic statistical-rigor pass for bounded studies.

## Purpose

The layer exists to stop tiny local runs from being treated like stable results.
It does not do NHST or invent significance claims. It only emits defensible,
machine-readable skepticism from the evidence that actually exists.

Current behavior:

- read a run manifest, study manifest, or run-output directory
- recover sample size from direct metrics when available
- recover exact binary counts from `predictions.jsonl` when available
- compute bounded uncertainty summaries for proportion metrics with Wilson
  intervals
- flag underpowered totals and tiny slices
- emit promotion guidance capped at `exploratory` or `not-ready`
- write durable artifacts beside mission state and, when possible, beside the
  run output itself
- append a `statistical-rigor` ledger entry for mission-linked runs

## Contract

The machine-readable contract lives at
`configs/autonomy/statistical-rigor.yaml`.

It currently defines:

- artifact locations and co-located report names
- interval method and width warning threshold
- underpowered-run thresholds for totals and slices
- the maximum promotable state (`exploratory`)
- reference-manifest fields that can be used to inherit bounded context for
  follow-up study manifests

## Runtime surface

- module: `src/deeploop/research/statistical_rigor.py`
- runner: `scripts/runtime/run_statistical_rigor.py`

Artifact locations:

- mission-linked: `~/workspaces/runs/deeploop/missions/<mission_id>/statistical_rigor/`
- standalone: `~/workspaces/runs/deeploop/statistical_rigor/`
- co-located copy: `<run_output_dir>/deeploop_statistical_rigor.{json,md}`

## translation pilot first target

The first intended target is the small bounded translation pilot baseline output
under `~/workspaces/runs/translation-pilot/`.

For the current `qwen35-2b-base-real-smoke` baseline, the rigor layer should
surface that:

- the run only has 8 examples
- the accuracy interval is wide
- slice-level estimates are even less stable
- the result is useful for exploratory triage, not robust promotion

That same skepticism should carry through derived mechanistic/intervention prep
artifacts when they inherit their evidence from the same tiny baseline.
