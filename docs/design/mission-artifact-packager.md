# Mission artifact packager

DeepLoop missions should end in a coherent artifact package, not a scattered collection of outputs.

## Goal

Collect and cross-link the mission state, ledger, findings, stage outputs, critique artifacts, and
related run manifests into a browsable mission package.

## Package outputs

The packager writes a package directory under the mission root containing:

- `package-manifest.json`
- `artifact-index.json`
- `package-summary.md`
- `linked_artifacts/` symlinks for quick browsing

## Collection strategy

The first implementation collects artifacts from:

1. the mission root tree
2. mission ledger `related_paths`
3. substrate run manifests matching the mission id
4. explicit extra globs for mission-adjacent outputs such as utility-score and self-optimization reports
