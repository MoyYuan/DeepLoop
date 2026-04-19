# Sandboxed agent execution

DeepLoop should prefer isolated specialist workers over one omnipotent process.

## Rule-ingestion order

Every spawned agent should ingest:

1. machine-wide rules
2. DeepLoop shared rules
3. target-repo local rules

before it acts.

## Isolation target

- one sandbox root per mission and role
- explicit input/output directories
- role-specific environment selection
- minimal permissions needed for the assigned task

## Why this matters

- protects global environment hygiene
- reduces agent cross-talk
- keeps full permissions from becoming uncontrolled host mutation
