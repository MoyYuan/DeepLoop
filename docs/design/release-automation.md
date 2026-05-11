# Release automation

DeepLoop release automation extends mission packaging into a deterministic
promotion workflow.

## Scope boundary

This document covers **mission/package promotion automation**, not the entire
public-release story for DeepLoop.

That distinction matters:

- mission/package promotion answers whether a specific mission artifact package
  is promotable
- public-release posture answers whether the repo can honestly be published as a
  public alpha, portable multi-substrate system, or eventually a more fully
  automatic platform

Use these together:

- `docs/release/README.md` for release-facing posture
- `docs/release/public-autonomy-roadmap.md` for the broader roadmap and
  checklist
- this document for the concrete package promotion contract

## Contract surfaces

- `configs/runtime/release-candidate-policy.yaml` — machine-readable policy for
  release-candidate gates
- `configs/runtime/gate-2-runtime-lanes.yaml` — machine-readable description of
  the current approved Gate 2 real-runtime lanes and proof boundary
- `schemas/release-candidate-review.schema.json` — schema for generated release
  review artifacts
- `scripts/release/review_release_candidate.py` — canonical CLI for re-running
  release review and optional promotion

## Promotion gates

The release-candidate policy currently enforces:

1. package integrity checks are green
2. package claim state is at least `paper-candidate`
3. required artifact categories are present
4. operator / paper / release summary surfaces are present
5. release-candidate blockers are empty
6. required human approvals are recorded

Packaging always emits a blocked-or-promotable review artifact so operators can
see exactly which gates remain open before release.

Release review artifacts now also snapshot the current Gate 2 runtime-lane
contract so package-level promotion records stay aligned with the broader
release proof boundary, even though package promotion alone does not satisfy
Gate 2.

## Broader public release gates

Mission package promotion is necessary but not sufficient for stronger public
claims. Before DeepLoop should claim **public alpha** or **fully automatic**
status, the broader repo must also satisfy release-facing gates such as:

1. OSS license and packaging/install metadata exist
2. public CI validates the supported fast and smoke paths
3. setup and quickstart are portable across supported installations
4. multiple substrates prove the runtime boundary in practice
5. remaining operator boundaries are justified as safety, authority, or
   governance gates rather than hidden product gaps

Those broader gates belong in the public roadmap and release docs, not only in
package-level promotion logic.

In the current release story, keep the split explicit:

- **Gate 1** is the baseline install/bootstrap/docs proof (`make public-bootstrap-check`,
  `make docker-release-validate`, `make docs-build`)
- **Gate 2** is the separate real-runtime proof on the approved local Qwen
  OpenAI-compatible lane plus the Copilot CLI `gpt-5-mini` coding-agent lane,
  as defined by `configs/runtime/gate-2-runtime-lanes.yaml`
- package promotion artifacts and approvals contribute to the release bundle,
  but they do not replace Gate 2 durable runtime evidence

## Approvals

`review_release_candidate.py` accepts a JSON or YAML approvals file with this
shape:

```yaml
approvals:
  - approval_id: provenance-review
    approved: true
    approved_by: operator-name
    note: provenance links checked
  - approval_id: licensing-review
    approved: true
    approved_by: operator-name
  - approval_id: release-operator
    approved: true
    approved_by: operator-name
```

When all gates pass, `--promote` writes `release_candidate_promotion.json` into
the package root as the durable promotion marker.
