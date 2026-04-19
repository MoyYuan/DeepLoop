# Research sanity gates

DeepLoop now has a deterministic preflight layer for research runs and
follow-up-study configs.

## Purpose

The sanity gate exists to block expensive or misleading execution when a
proposal is obviously underspecified. It is intentionally narrow:

- check that the referenced config exists and parses
- check that required manifests or artifacts exist and parse
- cheaply probe whether the selected dataset slice is empty
- require prompt/parser or equivalent output-contract fields when needed
- require explicit metrics or evaluation intent
- require comparable baseline references for follow-up analyses
- emit a structured `pass` / `warn` / `block` verdict with reasons

## Contract

The machine-readable contract lives at
`configs/autonomy/research-sanity-gates.yaml`.

It currently defines bounded sanity checks for:

- `baseline-eval`
- `mechanistic-localization`
- `causal-intervention`

The contract includes prompt-template registry hints, evaluation-contract
anchors, and a cheap power-worthiness threshold.

## Runtime integration

- Standalone runner: `scripts/runtime/run_sanity_gate.py`
- Queue integration: `src/deeploop/runtime/self_healing_runtime.py`
- Durable artifacts:
  - mission-linked: `~/workspaces/runs/deeploop/missions/<mission_id>/research_sanity/`
  - standalone: `~/workspaces/runs/deeploop/research_sanity/`
- Ledger integration:
  - `research-sanity-gate` entries capture verdicts and reasons
  - `autoexec-block` entries record blocked queue jobs

## translation pilot substrate coverage

The first contract explicitly understands the current translation pilot run and
follow-up config shapes:

- baseline eval configs anchored on the promoted dataset manifest
- mechanistic follow-up configs anchored on a behavioral source manifest
- intervention follow-up configs anchored on localization and baseline manifests

This keeps the gate deterministic and useful against real configs already used
by the mission runtime.
