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

For the next public release, `pyproject.toml` now declares `0.1.4`, so the
publishable tag and GitHub Release tag must be `v0.1.4`.

`publish.yml` only pushes to PyPI after the GitHub Release is published, and it
aborts if the published release tag and `project.version` diverge.

Current preflight posture:

- the public claim stays bounded-support public alpha on the documented Linux +
  Python 3.11 path
- merged `main` has already been rechecked with the integrated release-baseline
  unittest sweep, `make docs-build`, and `make public-bootstrap-check`
- the next release should emphasize installed-runtime import correctness,
  stale-output recovery hardening, and the strengthened clean-room release gate
  rather than a broader portability or autonomy claim

## Release gates at a glance

The current release story has a narrow Gate 1 / Gate 2 split:

- **Gate 1** provider-free bootstrap/smoke and Docker clean-room validation are
  the **baseline** install/onboarding proof
- **Gate 2** is the separate real LLM-backed mission/runtime proof required
  before recommending a coordinated release

The current approved Gate 2 phase is intentionally narrow and must stay honest:

1. **local Qwen via the OpenAI-compatible lane**
2. **Copilot CLI with GPT-5 mini for the coding-agent lane**
3. **no commercial OpenAI-compatible lane in this phase**

The machine-readable source of truth for those approved lanes is
`configs/runtime/gate-2-runtime-lanes.yaml`.

## Maintainer hardening backlog

Keep release hardening follow-ups version-agnostic on this maintainer surface or
in the linked GitHub issues, not in published release notes or deep-dive pages.

Current backlog pointers:

- [ ] [#55](https://github.com/tnetal/DeepLoop/issues/55) Investigate the
  unrelated full mission-runtime segfault
- [ ] [#56](https://github.com/tnetal/DeepLoop/issues/56) Evaluate optional
  recursive budget-warning/noise tuning
- [ ] [#57](https://github.com/tnetal/DeepLoop/issues/57) Expand smoke coverage
  beyond translation workflows

Docs-only release-prep edits are ignored by the `push` leg of CI, so release
maintainers should still run the release-facing checks locally before
publishing:

- `make public-bootstrap-check`
- `make docker-release-validate`
- `make docs-build`

## GitHub share checklist

1. update `CHANGELOG.md`
2. complete **Gate 1** by running `make public-bootstrap-check`
3. complete **Gate 1** by running `make docker-release-validate` to build
   sdist/wheel in Docker, install the wheel in a fresh container, and execute
   the provider-free bootstrap / onboarding smoke matrix; this is baseline proof
   only
4. complete **Gate 1** by running `make docs-build`
5. verify a fresh-clone / fresh-home onboarding run still succeeds on the
   documented path when onboarding or docs-command claims changed
6. complete **Gate 2 runtime proof contract** for both approved lanes:
    - local Qwen via an OpenAI-compatible endpoint
    - Copilot CLI with GPT-5 mini for the coding-agent lane
    - keep machine auth explicit and manual for Copilot CLI
    - record durable mission/runtime artifacts plus provider family, backend,
      model/profile, and lane-boundary notes instead of relying on shell output
7. verify the current proof-matrix review is still eligible for promotion
8. verify at least one real mission package still has a promotable
   `release_candidate_review.json` with the required approvals and the embedded
   `gate_2_runtime_contract`
9. run `make test-smoke` when runtime/bootstrap behavior changed
10. verify README and release docs still match the real proof level, including
    the explicit Gate 1 / Gate 2 boundary, the approved lanes, and the fact
    that provider-free bootstrap/smoke stays baseline-only
11. verify operator-only boundaries, provenance, licensing, and approval
    requirements are still documented honestly
12. publish the GitHub Release for the tagged version; the PyPI publish workflow
    is triggered from the published release event, not from a bare tag push
13. after PyPI publish completes, run
    `make docker-release-validate-pypi VERSION=<version>` in a second fresh
    container build to confirm the published artifact still passes the
    clean-room smoke
14. publish release notes that call out:
     - install / bootstrap changes
     - runtime / operator changes
     - package / release-review changes
     - proof / CI changes, including Gate 1 baseline plus Gate 2 lane-contract
       evidence
     - governance / trust-surface changes

## GitHub release notes draft (`v0.1.4`)

```md
## DeepLoop v0.1.4

This patch release keeps the published Linux + Python 3.11 public-alpha path
honest after wheel install, hardens runtime recovery against stale outputs, and
adds release-proof coverage for the shipped launcher without widening the public
claim.

- **Install / bootstrap:** the shipped runtime launcher now resolves imports
  correctly when it is executed from an installed wheel, not only from a repo
  checkout or runtime cache.
- **Runtime / operator:** non-execution phase recovery now ignores stale output
  artifacts even on timestamp ties, so old files do not look like fresh phase
  completions.
- **Package / release review:** the release artifact keeps the packaged runtime
  script executable as shipped, which is now covered by an explicit wheel-based
  regression test.
- **Proof / CI:** merged-main release checks were revalidated with targeted
  provider-launcher/package tests, `make public-bootstrap-check`,
  `make docs-build`, the Docker clean-room release validation harness, and the
  explicit Gate 1 / Gate 2 runtime-proof contract.
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
