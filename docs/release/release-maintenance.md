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

## Current GitHub preflight

For the next public release, `pyproject.toml` currently declares `0.1.3`, so
the publishable tag and GitHub Release tag must be `v0.1.3`.

`publish.yml` only pushes to PyPI after the GitHub Release is published, and it
aborts if the published release tag and `project.version` diverge.

Current preflight posture:

- the public claim stays bounded-support public alpha on the documented Linux +
  Python 3.11 path
- merged `main` has already been rechecked with the integrated release-baseline
  unittest sweep, `make docs-build`, and `make public-bootstrap-check`
- the next release should emphasize onboarding/operator clarity, bounded repair,
  runtime/package hardening, and the strengthened clean-room release gate rather
  than a broader portability or autonomy claim

Docs-only release-prep edits are ignored by the `push` leg of CI, so release
maintainers should still run the release-facing checks locally before
publishing:

- `make public-bootstrap-check`
- `make docker-release-validate`
- `make docs-build`

## GitHub share checklist

1. update `CHANGELOG.md`
2. run `make public-bootstrap-check`
3. run `make docker-release-validate` to build sdist/wheel in Docker, install
   the wheel in a fresh container, and execute the provider-free bootstrap /
   onboarding smoke matrix
4. verify a fresh-clone / fresh-home onboarding run still succeeds on the
   documented path
5. verify the current proof-matrix review is still eligible for promotion
6. verify at least one real mission package still has a promotable
   `release_candidate_review.json` with the required approvals
7. run `make test-smoke` when runtime/bootstrap behavior changed
8. run `make docs-build` for docs or claim changes; docs-only pushes are
   ignored by the `push` leg of CI, so do not skip the local docs validation
9. verify README and release docs still match the real proof level
10. verify operator-only boundaries, provenance, licensing, and approval
   requirements are still documented honestly
11. publish the GitHub Release for the tagged version; the PyPI publish workflow
    is triggered from the published release event, not from a bare tag push
12. after PyPI publish completes, run
    `make docker-release-validate-pypi VERSION=<version>` in a second fresh
    container build to confirm the published artifact still passes the
    clean-room smoke
13. publish release notes that call out:
     - install / bootstrap changes
     - runtime / operator changes
     - package / release-review changes
     - proof / CI changes
     - governance / trust-surface changes

## GitHub release notes draft (`v0.1.3`)

```md
## DeepLoop v0.1.3

This patch release makes the documented Linux + Python 3.11 public-alpha path
easier to start, easier to recover, and better proven in clean-room validation
without widening the public claim.

- **Install / bootstrap:** the public `deeploop` CLI is now the clearer entry
  surface, discovery reuses detected project context, and incomplete plain-folder
  projects stop with bounded repair guidance instead of opaque failures.
- **Runtime / operator:** operator handoffs now point to public `deeploop ...`
  commands, degraded provider paths emit cleaner canonical warnings, and resumed
  runs preserve better recovery/package context on the supported path.
- **Package / release review:** runtime/package summaries now expose clearer
  recovery detail, and the release-candidate packaging/review path remains
  bounded and explicit.
- **Proof / CI:** the Docker clean-room gate now rechecks canonical bootstrap,
  messy-start clarifications/defaults, discovery-first onboarding, and bounded
  bootstrap-repair diagnostics on the same release path; merged-main release
  checks were also revalidated with the integrated unittest sweep,
  `make public-bootstrap-check`, and `make docs-build`.
- **Governance / trust surface:** DeepLoop still ships as a bounded-support
  public alpha for the documented Linux path; this release improves UX,
  resilience, and proof discipline rather than widening autonomy scope.
```

## Non-goals

- do not weaken release or package gates to make a version look stronger
- do not claim broader portability than the documented bootstrap proves
- do not advertise "fully automatic for everyone" unless the stronger proof bar
  is actually met

## Docker-first clean-room validation

`make docker-release-validate` is now the preferred release-validation harness.
It intentionally complements rather than replaces the normal contributor paths:

- **Docker** is the canonical clean-room proof for release signoff and future
  provider-free smoke expansion
- **conda** and **uv/pip** remain the standard development/install workflows

The Docker harness lives in repo-owned assets:

- `.dockerignore` keeps the build context deterministic
- `docker/release-validation.Dockerfile` builds artifacts in one stage and runs
  install validation in fresh runtime stages
- `scripts/release/docker_validation.py` is the operator entrypoint for both the
  pre-publish wheel/sdist pass and the post-publish PyPI pass
- `scripts/release/in_container_smoke.py` runs the current provider-free CLI and
  mission-bootstrap smoke inside the container

The current smoke contract is intentionally narrow and deterministic:

1. build the wheel and sdist inside Docker
2. install DeepLoop from the built wheel in a fresh runtime image
3. verify the console entrypoints respond
4. initialize the canonical plain-folder example with a deterministic mission id
5. confirm the generated mission state stays outside the project folder and the
   example itself remains unchanged
6. initialize the non-translation `literature-gap-map` proof fixture and verify
   its readiness contract stops for operator input instead of pretending it is
   runnable end to end
7. package that initialized literature mission and confirm the lightweight
   package surface still materializes with explicit missing-artifact reporting
8. initialize the messy-start `forecast-rough-notes` fixture and verify the
   guarded clarifications/defaults handoff still packages cleanly
9. rerun `forecast-rough-notes` through discovery-first onboarding to keep the
   confirmed-discovery install story honest
10. verify a partial project-folder bootstrap fails with bounded repair
    diagnostics instead of mutating the input project

That gives release signoff a reusable clean-room install proof today, while
leaving provider-backed mission execution on the normal documented paths until a
future containerized provider contract is ready.
