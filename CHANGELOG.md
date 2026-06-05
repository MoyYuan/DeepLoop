# Changelog

All notable public-facing changes to DeepLoop should be recorded here.

The project is still in `0.x` public-alpha development. Entries should focus on
changes that affect:

- install / bootstrap contracts
- runtime or operator behavior
- package or release-review behavior
- proof / CI / validation surfaces
- public docs, governance, trust, and support posture

## 0.2.0

Major release: API-only control plane with DeepSeek integration, 11 features
from autonomous research landscape, and comprehensive test coverage.

### Changed

- **Provider:** removed copilot-cli support; control plane is now API-only
  (openai-compatible-api). Default provider is DeepSeek via the
  `deepseek-chat-control-plane` selection profile.
- **Version:** `__version__` now single-sourced from `pyproject.toml` with CI
  consistency check in `make repo-check`.
- **Shared utilities:** canonical `core/shared.py` replaces 11 duplicated
  private helpers across the codebase.
- **Stage kernels:** split into 4 kernel files (`baseline_evaluation`,
  `prompt_decode_sweep`, `mechanistic_localization`, `causal_intervention`).
- **Mission runtime:** dispatch block factored into handler functions;
  `operator_console_snapshot` split into per-state renderers;
  `initialize_mission` broken into composable steps.
- **Linting:** `ruff` added with basic rules (E, F, I); `make lint` now
  enforces code quality.

### Added

- **Zero-cost GPU monitoring** (`runtime/gpu_monitor.py`): OS-primitive
  process monitoring with zero LLM API calls during training.
- **Two-tier fixed-size memory** (`core/bounded_memory.py`): frozen project
  brief (3K chars) + rolling memory log (2K chars), total ~5K chars.
- **Tree search experiments** (`research/tree_search.py`): best-first
  draft/improve/debug with configurable metric direction and exploration phase.
- **Tiered LLM usage** (`configs/runtime/model-tiers.yaml`): per-role/phase
  model selection with cost tracking and pricing table.
- **Agent dialogue protocol** (`mission/agent_dialogue.py`): structured
  PLAN/CODE/DIALOGUE/REVIEW turn-taking between specialized roles.
- **Composable stop conditions:** `tokenCountIs`, `costIs`, `maxIterations`,
  `noProgressThreshold` — pluggable into runtime loop.
- **Report synthesis** (`runtime/report_synthesis.py`): LaTeX generation with
  `pdflatex` PDF compilation from experiment DAG and bounded memory.
- **DAG experiment lineage** (`research/experiment_dag.py`): SOTA selection,
  cycle detection, ancestor/descendant traversal.
- **Circuit breaker:** per-task failure tracking with configurable max attempts.
- **Dry-run validation:** 2-step CPU-only experiment validation before GPU launch.
- **Self-writing instructions:** `patterns.md` (operational knowledge) +
  `progress.md` (history), rolling windows with auto-compression.
- **Subagent fan-out:** `run_parallel_subagents()` with configurable parallelism.

### Fixed

- Data integrity race: executor-made state mutations now merged on reload.
- `assert` → `ValueError` for input validation in adaptation training runtime.
- Unsafe `importlib.import_module` now restricted to `deeploop.runtime.*`.
- `_schema_errors` warns when `jsonschema` is absent instead of silently
  accepting invalid data.
- Broad `except Exception` narrowed to specific types in autotune and recovery.
- `iter_examples()` now uses line-by-line generator for memory-efficient JSONL.

### Testing

- **700 tests, 0 failures** (up from ~200).
- New test tiers: acceptance (real DeepSeek API), integration (API contract +
  GPU monitor live), unit (12 new test files for all new modules).
- Docker release validation passes with API-only smoke tests.

## 0.1.10

Patch release focused on making DeepLoop's disposable user-simulation campaign
contract trustworthy for long-running validation and release review.

### Changed

- the disposable user-simulation matrix now carries a container-visible local
  Qwen 0.8B GGUF artifact path while preserving host-side provenance metadata,
  and the disposable container mount contract now exposes that model path
  read-only at `/models/...`
- the accepted disposable user-simulation project-root surface now includes the
  expanded 10-scenario campaign foundation used for long-running validation

### Fixed

- outer-user simulation sessions now honor the full one-hour minimum wall-clock
  contract even when an intermediate phase exits non-zero, while still
  persisting durable phase and summary artifacts before surfacing failure
- failed disposable user-simulation scenarios now preserve their true elapsed
  runtime instead of collapsing to `0.0` in scenario summaries
- final campaign status now retains the latest completed phase instead of
  dropping phase context at campaign completion
- the repaired 10-project sequential rerun now passes cleanly with `10/10`
  scenarios completing at `>=3600s`, restoring honest long-run proof for the
  disposable simulation surface

## 0.1.9

Patch release focused on tightening DeepLoop's workspace hygiene for release
smoke and local maintainer cleanup.

### Changed

- Docker release smoke now stages its temporary project copies under
  `scratch/deeploop/release-validation/docker-smoke` instead of using the older
  top-level `docker-validation` workspace root
- the testing docs now expose a dedicated `make clean-workspace-temp` helper so
  maintainers can remove known DeepLoop-created temporary workspace leftovers
  without touching durable `runs/` evidence

### Fixed

- release-smoke scratch and cleanup behavior now align with DeepLoop's intended
  workspace layout instead of leaving legacy top-level workspace folders behind
- the release Docker-validation test surface now locks the release-smoke root to
  the DeepLoop scratch area so the old top-level path does not regress silently
- Gate 2 provider-launch recovery now tolerates zero-exit provider races by
  accepting a ready `agent_result.json` that appears just after exit and by
  salvaging a valid recursive-agent result payload from Copilot stdout when the
  file write is omitted

## 0.1.8

Patch release focused on repairing the strongest acceptance/runtime validation
surface so DeepLoop's published proof stays honest.

### Changed

- plain-folder missions that bootstrap with blocking readiness now stop before
  runtime kickoff with an explicit `mission-readiness-required` outcome instead
  of silently entering runtime anyway
- the strongest `translation-paper-scale` acceptance wrapper now uses a
  dedicated `1800` second per-case timeout budget, keeping that expensive
  release-facing surface distinct from the cheaper bounded proof-matrix default
- the default recursive-agent runtime policy now sets bounded non-execution
  phase timeouts so long planner or literature iterations cannot silently
  inherit the broader execution budget

### Fixed

- the repaired plain-folder acceptance fixtures now include the required
  dataset/access contract, which restores launchable real-mission bootstrap for
  `literature-gap-map`, `replication-heavy-redteam`, and
  `translation-budget-ladder`
- recursive-agent phase timeout overrides now actually shorten the base timeout
  when a phase-specific budget is configured
- the Docker release smoke now matches the repaired literature fixture contract
  by expecting clarifications and launch guardrails instead of the older blocked
  bootstrap path

## 0.1.7

Patch release focused on making DeepLoop's disposable user-simulation artifact
roots traceable and cleanable without changing the bounded public-alpha runtime
promise.

### Changed

- the disposable user-simulation matrix can now opt into the shared
  `system-scripts/sandbox_manager.py` lifecycle so campaign roots carry TTL and
  cleanup-policy metadata instead of relying on ad hoc local folders
- managed user-simulation runs now record their sandbox manifest under
  `metadata/managed-sandbox.json` and summarize that managed root in the durable
  campaign summary

### Fixed

- local disposable user-simulation evidence now defaults under
  `reports/local/disposable-user-simulation/...`, which keeps long-form sandbox
  output out of normal repo status by default
- `make clean` now removes generated disposable user-simulation artifacts from
  both the current local-output path and the older legacy report path
- the managed-sandbox path now fails fast if the shared manager does not
  materialize the requested host campaign root

## 0.1.6

Patch release focused on making DeepLoop's long-form fresh-user validation more
durable and fixing runtime UX issues surfaced by those disposable user
simulations.

### Changed

- DeepLoop now ships a repo-owned disposable Docker user-simulation matrix that
  runs fresh users sequentially, requires one-hour minimum sessions, records
  durable scenario/campaign artifacts, and pins the simulation contract to
  GPT-5.4 mini for the outer user, Copilot CLI `gpt-5-mini` for the control
  plane, and local Qwen3.5-9B for DeepLoop-carried experiment execution
- the release-validation Docker image now exposes a dedicated
  `user-simulation-base` stage, and the testing docs now define how to run the
  simulation matrix with the explicit host-Copilot mount boundary

### Fixed

- disposable-container runs now have an explicit `--mount-host-copilot`
  contract for the working Copilot binary/config/session-state mount shape
- OpenAI-compatible provider launches from a source checkout now bootstrap the
  repo `src/` path into subprocess `PYTHONPATH`, so repo-local Gate 2 lanes can
  resolve `deeploop.runtime.openai_compatible_adapter` correctly
- OpenAI-compatible result-writing flows now request JSON-object mode, which
  keeps the local Qwen3.5-9B Gate 2 analyze lane from drifting into
  reasoning-only prose
- local loopback Qwen JSON-result flows now disable model thinking explicitly,
  which keeps the combined 9B Gate 2 proof lane from exhausting its completion
  budget on reasoning text before it returns the required JSON payload
- `deeploop analyze` now tells providers to return raw JSON while DeepLoop
  writes the result file, instead of instructing the model to write directly to
  a filesystem path it cannot touch
- `deeploop run` guidance now points users toward `--mission-state` when a
  launch did not produce a resumable mission state
- mission summaries now refresh from current mission state instead of leaving
  `mission_summary.md` stale after the runtime reaches `completed` /
  `final-report`
- Gate 1 unittest surfaces now run against an isolated DeepLoop runs root during
  `make test` and `make public-bootstrap-check`, preventing shared workspace
  research-memory state from destabilizing the release candidate test suite

## 0.1.5

Patch release focused on making the current release contract honest after the
9B Gate 2 lane swap and agent-review promotion changes landed on `main`.

### Changed

- the approved local OpenAI-compatible Gate 2 release lane is now standardized
  on **Qwen/Qwen3.5-9B** instead of the older 27B profile, and the related
  provider selection/setup docs and runtime contract now reflect that boundary
- release-candidate promotion now records durable **agent or human review**
  records through `required_reviews` instead of requiring explicit human-only
  approval clicks in the normal release path

### Fixed

- the OpenAI-compatible adapter now accepts additional llama.cpp/Qwen response
  content shapes so the host-local 9B Gate 2 lane can materialize its required
  JSON result again
- recursive-agent prompts now steer simple artifact/result writes toward direct
  file tools, which restores reliable Copilot CLI Gate 2 handoff behavior during
  bounded runtime validation

## 0.1.4

Patch release focused on keeping the published runtime path honest after
wheel install, tightening stale-output recovery for non-execution phases, and
recording that proof in the release surface.

### Changed

- the packaged runtime launcher now bootstraps imports from either the repo
  `src/` tree, an explicit runtime cache source, or the installed `deeploop`
  package so the shipped asset script works in wheel-installed environments
- release/package structure proof now includes a regression check that executes
  the shipped `invoke_provider_prompt.py` asset directly from an extracted wheel

### Fixed

- non-execution phase recovery now ignores stale output files even when prompt
  and output timestamps tie, preventing an old artifact from being mistaken for
  fresh work during runtime handoff

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

## 0.1.1

Prepare 0.1.1 patch release ([#16](https://github.com/tnetal/DeepLoop/pull/16)).

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
