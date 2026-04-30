# DeepLoop mission artifact package

DeepLoop packages a mission into a deterministic bundle under
`~/workspaces/runs/deeploop/packages/<mission-id>/` so operators do not need to
chase scattered manifests, findings, and critique outputs across repos and run
roots.

## Package contract

The machine-readable contract lives at:

- `configs/runtime/artifact-package-contract.yaml`

The package manifest schema lives at:

- `schemas/mission-artifact-package.schema.json`

## Collected surfaces

The packager copies the mission's durable artifacts into the package and emits a
cross-linked artifact map covering:

1. **mission specs**
   - mission state
   - mission summary
   - mission decision and branch logs
   - mission next-actions summaries
   - substrate research briefs and design docs declared by the mission
2. **mission configs**
   - substrate configs declared by the mission
   - DeepLoop support contracts such as evidence-policy and stage-kernel registry
   - generated follow-up configs referenced by mission next-actions
3. **ledgers**
   - mission ledger JSONL
4. **findings**
   - mission findings markdown
5. **manifests**
   - baseline `run_manifest.json` files
   - kernel `study_manifest.json` files
6. **kernel outputs**
   - predictions, metrics, summaries, localization candidates, intervention metrics
7. **critique reports**
   - statistical-rigor reports
   - self-correction, confound-guard, redteam, and self-optimization outputs when present
8. **runtime metadata**
   - role handoffs
   - current focus handoffs
   - runtime queue configs
   - mission meta-eval outputs

## Determinism

Package metadata is deterministic:

- the package root is stable per mission id
- artifact ordering is sorted by source path
- the package digest is derived from copied artifact paths and file bytes
- the packager does not append package events into the mission ledger

This keeps repeated packaging runs stable when the input artifacts have not
changed.

## Claim-state awareness

The package manifest computes a conservative package claim state from:

- manifest claim states
- package-level follow-up replication signals when at least two related manifests
  are present and one is explicitly marked as a replication/follow-up run
- critique ceilings such as statistical-rigor promotion guidance
- DeepLoop evidence-policy requirements

The package summary always includes paper-candidate and release-candidate
blockers so operator handoff, paper drafting, and release review all see the
same bounded posture.

When packaging from an archived mission tree that already lives under a package's
`artifacts/` mirror, the packager now reuses co-packaged copies of referenced
artifacts if the original absolute workspace paths no longer exist. That keeps
preserved mission evidence reviewable instead of making old packages depend on
stale absolute workspace paths.

## Outputs

Each package directory contains:

- `mission_artifact_package.json` — machine-readable artifact map and cross-links
- `mission_artifact_package.md` — operator handoff / paper drafting / release review summary
- `release_candidate_review.json` — machine-readable promotion-gate evaluation against the release-candidate policy
- `release_candidate_review.md` — release review checklist with gate status and missing approvals
- `artifacts/` — copied mission inputs and outputs, preserving workspace-relative paths

## CLI

Run the packager directly with:

```bash
python scripts/mission/package_mission.py --mission-state ~/workspaces/runs/deeploop/missions/translation-full-mission/mission_state.json
```

`meta_eval.py` also invokes the packager so the standard mission meta-eval path
materializes the package automatically.

For the final human-facing handoff, export the completed mission package into a
clean submission repository layout:

```bash
deeploop export \
  --mission-state ~/workspaces/runs/deeploop/missions/translation-full-mission/mission_state.json \
  --output /path/to/submission-repo \
  --format github-repo
```

The export reuses the canonical package manifest, then writes a README-first
tree with:

- `README.md` — mission objective, method/result/caveat summary, artifact index,
  and exact export command
- `project-input/` — copied inputs from the researcher-owned target project
- `methods/` — mission summaries and method-facing handoff notes
- `results/` — generated metrics, predictions, logs, stability notes, and other
  science outputs
- `manifests/` — experiment and run manifests
- `docs/` — findings, caveats, and review reports
- `bookkeeping/deeploop/` — DeepLoop package manifests, ledgers, runtime
  metadata, and release-review records kept separate from science outputs
- `submission_manifest.json` and `provenance.json` — machine-readable export
  index and provenance
- `caveats-and-limitations.md` — conservative blockers and limitations gathered
  from package claim/release posture

The output folder must be outside the DeepLoop source clone. If the destination
already contains files other than `.git`, pass `--force` only when it is safe to
replace that folder's contents.

To re-run release review or attempt promotion after recording approvals:

```bash
python scripts/release/review_release_candidate.py \
  --package-manifest ~/workspaces/runs/deeploop/packages/translation-full-mission/mission_artifact_package.json \
  --approvals /path/to/release_approvals.yaml
```
