# DeepLoop research memory

DeepLoop should remember more than just the latest successful run.

## What to preserve

- missions and constraints
- hypotheses and why they were proposed
- experiment manifests
- negative results and crashes
- critique notes and confounds
- branching decisions

## Why this matters

Without memory, DeepLoop risks:

- rediscovering the same failed ideas
- losing context on why an experiment mattered
- repeating shallow hill climbing without scientific accumulation

## Indexed runtime surface

The runtime now maintains:

- an append-only `research_memory_entries.jsonl` event log
- a materialized `research_memory_index.json` inverted index under
  `~/workspaces/runs/deeploop/ledger/research_memory/`
- schema-validated entries with provenance, retrieval terms, promotion status,
  and retention metadata

Mission memory sync promotes grounded summaries, decisions, experiment runs,
and promoted findings into the shared index so future missions can retrieve
relevant evidence before repeating work.

## Retention rules

- promoted findings remain active
- failed and blocked experiments remain active
- branching and reroute decisions remain active
- non-protected entries roll forward in a bounded per-mission window while the
  append-only event log preserves the full audit trail
