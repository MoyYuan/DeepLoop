# Mandatory experiment ledger

DeepLoop should treat experiment, inference, and findings tracking as a hard
system rule, not as an optional habit.

## Required records

Every non-trivial run should leave behind:

- a run manifest
- metrics or a failure record
- a durable ledger entry
- a mission-level append-only record in `mission_experiments.jsonl`

Every promoted findings summary should leave behind:

- links to source manifests
- a durable findings artifact
- an explicit claim state
- a compact mission-memory update in `mission_memory.json`

## Why this matters

- it prevents shell output from becoming the only record
- it makes autonomous work auditable
- it enables DeepLoop to continue reasoning from prior evidence
