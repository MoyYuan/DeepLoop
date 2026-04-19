# Self-correction engine

DeepLoop now has a post-run self-correction surface that complements the
pre-run sanity gate.

## Purpose

The engine consumes durable mission artifacts and run manifests, classifies
bad or weak outcomes, and emits deterministic branch decisions:

- `continue`: keep the branch as a usable anchor
- `reroute`: redirect the next experiment toward a better prerequisite or slice
- `stop`: stop investing in the branch as an active anchor

## Contract

The machine-readable contract lives at
`configs/autonomy/self-correction.yaml`.

The first taxonomy covers:

- insufficient evidence
- accuracy collapse
- weak but usable accuracy signal
- lexicalization instability
- rule-family collapse
- blocked or failed execution
- preparation-only artifacts

## Runtime integration

- module: `src/deeploop/research/self_correction.py`
- runner: `scripts/mission/run_self_correction.py`
- durable artifacts:
  - mission-linked: `~/workspaces/runs/deeploop/missions/<mission_id>/self_correction/`
  - standalone: `~/workspaces/runs/deeploop/self_correction/`
- ledger integration:
  - `self-correction` entries capture the synthesized mission decision
  - mission state gains a `self_correction` summary block for later agents

## First substrate: translation pilot

The initial collector auto-discovers `run_manifest.json` and
`study_manifest.json` files under `~/workspaces/runs/translation-pilot`, then
filters them down to DeepLoop mission-linked artifacts. This lets the engine
classify real baseline, localization-prep, and intervention-prep artifacts
from the current translation pilot mission.
