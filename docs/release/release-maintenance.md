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

For the next public release, `pyproject.toml` currently declares `0.1.2`, so
the publishable tag and GitHub Release tag must be `v0.1.2`.

`publish.yml` only pushes to PyPI after the GitHub Release is published, and it
aborts if the published release tag and `project.version` diverge.

Current preflight posture:

- the public claim stays bounded-support public alpha on the documented Linux +
  Python 3.11 path
- post-smoke hardening was rechecked with clean canonical
  `translation-budget-ladder` smoke reruns
- the next release should emphasize runtime/package hardening and release
  hygiene, not a broader portability or autonomy claim

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
   the wheel in a fresh container, and execute the provider-free bootstrap
   smoke
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

## GitHub release notes draft (`v0.1.2`)

```md
## DeepLoop v0.1.2

This patch release hardens the documented Linux + Python 3.11 public-alpha path
without widening the public claim.

- **Install / bootstrap:** GitHub Release publication remains the only PyPI
  publish trigger, and the publish workflow rejects tags that do not match
  `project.version`.
- **Runtime / operator:** Copilot-backed recursive runs get a longer idle
  window, cleaner canonical phase handoffs, and better resumed-run bookkeeping
  on the supported path.
- **Package / release review:** Completed missions now refresh final package
  manifests, and package validation ignores transient sandbox/runtime scratch
  outputs instead of treating them as durable release artifacts.
- **Proof / CI:** Post-smoke hardening was revalidated with clean canonical
  `translation-budget-ladder` smoke reruns, and release-facing docs were
  rechecked with `make public-bootstrap-check` and `make docs-build`.
- **Governance / trust surface:** DeepLoop still ships as a bounded-support
  public alpha for the documented Linux path; this release improves safety and
  durability rather than widening autonomy scope.
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

That gives release signoff a reusable clean-room install proof today, while
leaving provider-backed mission execution on the normal documented paths until a
future containerized provider contract is ready.
