# Changelog

All notable public-facing changes to DeepLoop should be recorded here.

The project is still in `0.x` public-alpha development. Entries should focus on
changes that affect:

- install / bootstrap contracts
- runtime or operator behavior
- package or release-review behavior
- proof / CI / validation surfaces
- public docs, governance, trust, and support posture

## 0.1.3

Patch release focused on making the supported DeepLoop path easier to start,
easier to recover, and better proven in clean-room validation without widening
the bounded-support public-alpha claim.

### Changed

- the public `deeploop` CLI now presents a clearer front door: `run`, `init`,
  `start`, `status`, `inbox`, and `resume` hand off with user-facing
  `deeploop ...` commands instead of repo-internal script paths
- `deeploop init --discover` now inspects an optional project folder, reuses
  detected context, keeps the question flow bounded, and shows readiness/default
  summaries before kickoff
- project-root bootstrap now fails early with deterministic repair guidance and a
  starter scaffold when a plain-folder contract is missing or incomplete
- provider-free smoke and Docker clean-room validation now cover messy-start
  clarifications/defaults, discovery-first onboarding, and bounded
  bootstrap-repair diagnostics in addition to the canonical bootstrap path
- runtime/package summaries now carry clearer recovery and large-ledger context
  through resumed/interrupted mission paths
- release-facing docs now describe the supported CLI-first onboarding path and
  the expanded clean-room release gate more directly

### Fixed

- degraded provider payloads, readiness failures, and partial execution gaps now
  synthesize canonical runtime artifacts with deduplicated actionable warnings
- resumed/runtime-recovery paths now preserve clearer package and operator
  handoff context instead of leaving those details implicit
- partial or ambiguous project folders now stop with bounded repair output
  instead of drifting into opaque bootstrap failures

## 0.1.2

Patch release focused on post-smoke hardening, operator safety, and clearer
public-facing guidance. The documented Linux + Python 3.11 path was revalidated
with clean canonical translation-budget-ladder smoke reruns before release
preflight.

### Changed

- PyPI publish now triggers from the published GitHub Release event only, and
  validates that the release tag matches `project.version` before building
- Copilot-backed recursive runs now use a longer default idle window, normalize
  generic phase handoffs to the supported phase defaults, and persist
  canonicalized result payloads for cleaner resumed runs
- completed missions now refresh their final package manifests at completion,
  and release-candidate packaging ignores transient sandbox/runtime scratch
  outputs instead of treating them as durable required artifacts
- the plain-folder proof-matrix harness now emits per-case progress, enforces a
  per-case timeout, and terminates the full subprocess group on timeout instead
  of leaving descendant provider processes behind
- bounded triage now rejects a non-zero subprocess exit even if a result JSON
  was written, preventing success-shaped CLI behavior on failed subprocess runs
- public docs now reduce install duplication, document `deeploop analyze-budget`
  more clearly, and make the installed `deeploop` CLI the canonical operator
  entry surface
- release docs now include GitHub release preflight guidance and a concise
  copy-ready release-notes draft aligned with the GitHub Release -> PyPI flow

### Fixed

- resumed recursive loops now respect the remaining persisted iteration budget
  instead of silently re-spending the full configured budget after restart
- proof-matrix timeouts now fail cleanly with structured remediation output
  rather than hanging silently
- release maintenance guidance now matches the real GitHub Release -> PyPI
  publish flow

## 0.1.0

Initial public-alpha share-readiness baseline.

### Added

- MIT license and packaging metadata through `pyproject.toml`
- public CI for repo checks, unit, integration, smoke, docs, and public
  bootstrap validation
- explicit autonomy-governance inventory and release-facing docs
- SECURITY and code-of-conduct surfaces
- public release-maintenance guidance
- plain-folder starter guidance tied to tested proof fixtures

### Changed

- plain-folder missions now materialize executor-backed late-phase follow-ups
- plain-folder packages now include truthful manifest and critique-report
  coverage
- public bootstrap docs now point to `make public-bootstrap-check` as the
  supported clean-room validation path
- public docs now describe DeepLoop as an experimental public alpha for Linux
  with Python 3.11, not "fully automatic for everyone"
