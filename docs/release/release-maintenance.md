# Release maintenance

This page defines the lightweight public release discipline for DeepLoop's
current `0.x` public-alpha phase.

## Versioning posture

DeepLoop is still a `0.x` project:

- versions can move quickly
- public claims must stay conservative
- breaking changes are acceptable when they are documented clearly
- release notes should explain changes in user-facing behavior, bootstrap
  expectations, and autonomy boundaries

## Canonical release artifacts

Before cutting or announcing a public release, update:

- `CHANGELOG.md`
- `README.md` when the honest public claim changes
- `docs/release/` pages when bootstrap, governance, or roadmap posture changes
- `CONTRIBUTING.md` when validation or support posture changes

Mission/package promotion is still separate from repo/public release posture:

- mission packages follow `configs/runtime/release-candidate-policy.yaml`
- repo releases follow this maintenance checklist plus the public docs contract

## GitHub share checklist

1. update `CHANGELOG.md`
2. run `make public-bootstrap-check`
3. verify a fresh-clone / fresh-home onboarding run still succeeds on the
   documented path
4. verify the current proof-matrix review is still eligible for promotion
5. verify at least one real mission package still has a promotable
   `release_candidate_review.json` with the required approvals
6. run `make test-smoke` when runtime/bootstrap behavior changed
7. run `make docs-build` for docs or claim changes
8. verify README and release docs still match the real proof level
9. verify operator-only boundaries, provenance, licensing, and approval
   requirements are still documented honestly
10. publish release notes that call out:
    - install / bootstrap changes
    - runtime / operator changes
    - package / release-review changes
    - proof / CI changes
    - governance / trust-surface changes

## Non-goals

- do not weaken release or package gates to make a version look stronger
- do not claim broader portability than the documented bootstrap proves
- do not advertise "fully automatic for everyone" unless the stronger proof bar
  is actually met
