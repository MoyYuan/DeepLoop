# Multi-substrate proof

This page defines what DeepLoop must prove before it can claim to be more than
an translation pilot-shaped runtime.

## Goal

Show that the same DeepLoop runtime and operator contracts work across multiple
materially different substrates, not just across multiple configs for one
project.

## Why this matters

A generic architecture is not enough. Public trust needs demonstrated reality.

Without multi-substrate proof, DeepLoop risks being:

- generic in abstraction
- narrow in practice

## Minimum proof bar

DeepLoop should validate at least **2-3 non-trivially different substrates**
before making a stronger public generality claim.

Those substrates should vary in meaningful ways, such as:

- task shape
- artifact structure
- evaluation contract
- follow-up planning needs
- optional adaptation or intervention flows

## Required evidence

For each candidate substrate, DeepLoop should show:

1. the substrate boundary is respected
2. the same mission/operator surfaces remain valid
3. tiny-real smoke tests pass on real substrate artifacts
4. bounded-real proofs exercise production-like flow without hidden substrate
   runtime fallback

## Current plain-folder proof matrix

The current reusable bounded-real matrix lives in the repository as:

- fixtures:
  - `tests/_proof_fixtures/plain_folder/`
- runner:
  - `python scripts/testing/run_plain_folder_proof_matrix.py --list`
  - `python scripts/testing/run_plain_folder_proof_matrix.py --case <case-id>`
  - `python scripts/testing/run_plain_folder_proof_matrix.py`

Initial matrix cases:

| Case id | Workflow shape | Why it is different |
| --- | --- | --- |
| `translation-budget-ladder` | benchmark-heavy | pushes dataset/slice/metric narrowing under explicit budget constraints |
| `literature-gap-map` | literature-heavy | pushes prior-art synthesis and hypothesis narrowing before execution |
| `replication-heavy-redteam` | execution-heavy | pushes repeatability, replication posture, and repeated-run comparisons |

Each run materializes a fresh researcher folder from the fixture, launches the
canonical `run_project.py --until-complete --force` path, and records whether:

- the mission completed
- the operator inbox stayed clear
- the final phase reached `final-report`
- the project folder remained unchanged

Campaign outputs are written under:

- `~/workspaces/runs/deeploop/proof_matrix/`

Each campaign now also emits a promotion-style review surface:

- `proof_matrix_review.json`
- `proof_matrix_review.md`

That review is where the matrix graduates from "raw bounded-real run logs" to a
milestone-grade proof artifact.

Historical campaign summaries can also be recombined through
`scripts/testing/review_plain_folder_proof_matrix.py`. The review loader prefers
captured campaign snapshot evidence over reopening live mission-state paths, so
older proofs remain reviewable even after mission roots are reused later.

## What counts as success

Success is not just "the run completed."

The proof should show:

- DeepLoop-owned behavior stayed in DeepLoop
- substrate-owned minimal facts and contracts stayed in the substrate
- DeepLoop-owned build code, runtime scripts, generated configs, and experiment
  implementation surfaces did **not** leak back into the substrate repo
- operator requests were truthful
- follow-up generation remained runnable or explicitly deferred
- release/package artifacts remained coherent
- final-report outputs were actually present for every passing case

## Campaign review surface

The canonical proof-matrix runner now writes two layers of output:

1. **raw campaign output**
   - `campaign_summary.json`
   - per-case `proof_summary.json`
2. **promotion review**
   - `proof_matrix_review.json`
   - `proof_matrix_review.md`

The promotion review makes the multi-substrate claim legible by showing:

- which workflow shapes were covered
- whether every case passed
- whether the substrate tree stayed unchanged
- whether the operator inbox stayed clear
- whether final-report outputs were present
- which failures still look like hard boundaries versus temporary gaps

## Promotion rule

Do not claim **portable multi-substrate** or stronger until at least 2-3
substrates have passed the relevant smoke and bounded-real proof surfaces **and**
the campaign review says the proof matrix is eligible for promotion.

## Related docs

- [Public autonomy roadmap](public-autonomy-roadmap.md)
- [Substrate boundary](../design/substrate-boundary.md)
- [Testing strategy](../reference/testing-strategy.md)
