# DeepLoop rollout plan

DeepLoop should land in stages so control contracts become usable before a full
autonomous runtime exists.

## Stage 1: control contracts

- operating modes
- autonomy gates
- state machine
- execution profiles
- resource tiers
- manifest and memory schemas

## Stage 2: substrate integration

- wire run manifests into `translation-pilot`
- wire run manifests into `forecast-lab`
- add the first profile-resolving helpers

## Stage 3: bounded executor

- implement a small manifest-driven executor
- support single-GPU inference and bounded retries
- record resolved execution details automatically

## Stage 4: memory and evidence loop

- persist hypotheses, critiques, and decisions
- add evidence-state promotion checks

## Stage 5: DeepLoop evaluation

- compare sandboxed-yolo against human-directed first, then managed as the expert tier
- measure useful-findings rate, reproducibility, and stability
