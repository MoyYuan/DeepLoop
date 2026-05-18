# Testing strategy

DeepLoop uses a **four-tier** testing model:

1. **unit**
2. **mocked integration**
3. **tiny real smoke**
4. **bounded real**

The goal is not just to have more tests. The goal is to make it obvious what
each layer proves and when it should run.

## Tier 1 — Unit

Use this tier for fast, local logic and invariant checks.

Typical DeepLoop coverage:

- planner and gate logic
- prompt rendering
- payload normalization
- schema/config adapters
- small research/evaluation helpers

Canonical command:

```text
make test-unit
```

Use it:

- on almost every code change
- when changing isolated logic
- as the fastest correctness pass

## Tier 2 — Mocked integration

Use this tier for realistic DeepLoop wiring with durable mission state and
artifacts, but mocked expensive executors or model work.

Typical DeepLoop coverage:

- mission runtime
- mission management CLI
- mission monitor and operator surfaces
- self-healing/runtime recovery paths
- recursive-agent/runtime integration with bounded mocks

Canonical command:

```text
make test-integration
```

Use it:

- when changing runtime flow
- when changing operator surfaces or telemetry
- when changing recovery or executor wiring

## Tier 3 — Tiny real smoke

Use this tier for **tiny but real** proofs. This is the most important tier for
catching contract drift between generated artifacts and downstream execution.

Typical DeepLoop coverage:

- tiny mission init + follow-up planning
- tiny queue execution
- tiny stage/runtime/package proofs
- runnable-contract checks on real generated artifacts

Canonical command:

```text
make test-smoke
```

Use it:

- when changing planners, generated configs, or downstream artifact contracts
- when changing smoke-critical operator/runtime surfaces
- before merging changes that could be “wired correctly but not actually runnable”

## Tier 4 — Bounded real

Use this tier for production-like mission proofs with explicit budgets and
sample caps.

Typical DeepLoop coverage:

- bounded long-run profile proof
- mission init / advance / meta-eval / package script chain
- selected real substrate validations
- plain-folder cross-substrate proof campaigns

Canonical command:

```text
make test-real
```

Use it:

- for long-run regression checks
- before release-grade or substrate-contract-sensitive changes
- on demand, scheduled, or during higher-confidence validation passes

The current reusable plain-folder bounded-real runner is:

```text
python scripts/testing/run_plain_folder_proof_matrix.py --list
python scripts/testing/run_plain_folder_proof_matrix.py --case <case-id>
python scripts/testing/run_plain_folder_proof_matrix.py
```

For milestone review, the same runner now emits:

```text
~/workspaces/runs/deeploop/proof_matrix/<campaign-id>/proof_matrix_review.json
~/workspaces/runs/deeploop/proof_matrix/<campaign-id>/proof_matrix_review.md
```

That review surface summarizes whether the current campaign is strong enough to
serve as a multi-substrate promotion artifact instead of just a raw bounded-real
campaign log.

## Final acceptance campaign

Above the four engineering tiers sits a separate **acceptance campaign**. This
is an expensive real-project confidence surface for DeepLoop, not an ordinary
fast tier.

Current canonical command:

```text
make test-acceptance
```

This runs the DeepLoop-owned translation pilot acceptance bootstrap and writes an
acceptance review artifact on top of the existing real proof outputs.

Unlike the cheaper bounded proof-matrix entrypoint, the acceptance wrapper uses
a larger per-case timeout budget so longer real mission phases can finish.

Use it:

- before major releases or milestone promotions
- when you need an translation pilot-backed real-project confidence check in
  addition to the broader release evidence bundle
- when you need a real-project final confidence check instead of just a bounded
  engineering proof

## Final acceptance bundle

Do not treat `make test-acceptance` as the sole final exam anymore. The
stronger share claim depends on a bundle of evidence:

1. an eligible-for-promotion `proof_matrix_review.json` covering materially
   different plain-folder workflow shapes
2. a passing documented bootstrap/onboarding path from a fresh clone and fresh
   home
3. a real promotable `release_candidate_review.json` for at least one mission
   package with the required durable reviews
4. a Gate 2 release proof that records real LLM-backed mission/runtime evidence
   on the current approved lanes:
   - local Qwen3.5-9B via an OpenAI-compatible lane
   - Copilot CLI with GPT-5 mini for the coding-agent lane
   - use `configs/runtime/gate-2-runtime-lanes.yaml` as the machine-readable
     source of truth for that proof boundary
5. autonomy-gap evidence showing bounded recovery is happening before operator
   escalation for the covered gap classes
6. the translation pilot acceptance campaign when you need an additional real-project
   exam on top of the broader bundle

Provider-free smoke remains baseline-only release evidence in this bundle. It
does not replace the Gate 2 runtime proof, and the current approved phase does
not include a commercial OpenAI-compatible lane.

## Release gate mapping

DeepLoop's release story sits on top of the engineering tiers:

- **Gate 1** — required baseline for every PR and every release
  - `make public-bootstrap-check`
  - `make docker-release-validate`
  - `make docs-build`
  - proves install/bootstrap/docs integrity, not the final live runtime claim
- **Gate 2** — required for every release and for high-risk PRs
  - run `python scripts/release/real_runtime_validation.py ...`
  - prove both approved lanes:
    - local Qwen3.5-9B via the OpenAI-compatible lane
    - Copilot CLI with `gpt-5-mini` for the coding-agent lane
  - keep manual machine auth explicit and record durable evidence (`gate_2_real_runtime_validation.json` / `.md` and each lane's `validation_record.json` / `.md`)
- **Gate 3** — broader pre-release or nightly matrix confidence
  - use when you want additional provider/backend combinations or larger
    fixtures, not as the default merge gate

Provider-free smoke and `deeploop provider-ready` are still useful baseline
signals, but they do **not** satisfy Gate 2 on their own.

If you want to remove known DeepLoop-created temporary workspace leftovers from
older smoke, release, or test runs without touching durable `runs/` evidence,
use:

```text
make clean-workspace-temp
```

## Disposable user-simulation matrix

When you need a longer fresh-user exam beyond release smoke, DeepLoop now ships
a disposable Docker user-simulation harness:

```text
python scripts/testing/run_disposable_user_simulation_matrix.py --prepare-only
python scripts/testing/run_disposable_user_simulation_matrix.py \
  --mount-host-copilot \
  --simulator-command python scripts/testing/run_disposable_user_simulation_outer_user.py ...
```

Machine-readable campaign defaults live in
`configs/testing/disposable-user-simulation-matrix.yaml`. The current matrix is
deliberately opinionated:

- run scenarios **sequentially**, never in parallel
- use a **fresh disposable container** for each scenario
- require at least **3600 seconds** of wall time per simulated user
- treat the outer simulated user as an **explicit external boundary** pinned to
  `gpt-5.4-mini`
- pin DeepLoop's control plane to Copilot CLI `gpt-5-mini`
- pin all DeepLoop-carried experiment execution to the local
  `Qwen/Qwen3.5-9B` lane through repo-owned runtime and mission inputs

The repo-owned outer-user wrapper reads the generated prompt, contract, and
runtime-pin artifacts from the matrix runner, then writes durable transcripts
under each scenario's `artifacts/outer-user-simulation/` directory.

The harness prepares durable scenario contracts, prompt bundles, workspace
materialization, and DeepLoop runtime-pin files. It does **not** hide simulator
auth or model access behind repo automation; operator-supplied simulator wrappers
remain explicit.

By default the campaign root lands under
`reports/local/disposable-user-simulation/<campaign-id>/` so long-form local
evidence stays out of repo status unless you explicitly override `--output-root`.

If you want those campaign roots tracked and reaped through the shared workspace
sandbox registry instead, pass `--managed-sandbox` to the matrix runner. It can
reuse `../system-scripts/sandbox_manager.py` with the same TTL / cleanup-policy
controls used in XRTM, and records the returned sandbox manifest under the
campaign's `metadata/managed-sandbox.json`.

When you want the disposable container itself to exercise DeepLoop's pinned
Copilot `gpt-5-mini` control-plane path, pass `--mount-host-copilot`. That
flag is an explicit operator opt-in: it mounts the host `copilot` binary and
`~/.config/gh` read-only plus `~/.copilot` read-write so Copilot can create
session-state inside the container.

## Default run policy

Recommended default:

1. run **unit**
2. run **mocked integration**
3. run **tiny real smoke** when planner/runtime contracts changed
4. run **bounded real** when you need production-like confidence

If you want the full repo suite:

```text
make test
```

## Canonical runner

DeepLoop exposes the tiered runner through:

```text
python scripts/testing/run_test_tier.py --list
python scripts/testing/run_test_tier.py --tier unit
python scripts/testing/run_test_tier.py --tier integration
python scripts/testing/run_test_tier.py --tier smoke
python scripts/testing/run_test_tier.py --tier real
```

The runner is the source of truth for the current tier assignments.

## Mission runtime investigation entrypoint

When maintainers need a canonical fault-handler-enabled entrypoint for
`tests.test_mission_runtime`, use:

```text
make test-mission-runtime
```

That target enables `PYTHONFAULTHANDLER=1` and runs:

```text
python -m unittest tests.test_mission_runtime -q
```

If the full module passes but further narrowing is still useful, start with the
recursive-agent lifecycle and final-report closure paths:

```text
PYTHONFAULTHANDLER=1 python -m unittest \
  tests.test_mission_runtime.MissionRuntimeTests.test_runtime_completes_init_state_via_phase_execution_hints \
  tests.test_mission_runtime.MissionRuntimeTests.test_runtime_completes_generic_plain_folder_lifecycle_via_recursive_agent_hints \
  tests.test_mission_runtime.MissionRuntimeTests.test_runtime_completes_when_no_win_budget_closure_waives_replication \
  tests.test_mission_runtime.MissionRuntimeTests.test_runtime_completes_when_final_report_no_promotion_closes_replication -q
```

## Why Tier 3 matters so much

The recent mission failure was not mainly a missing unit test. It was a missing
proof that generated work was actually runnable under real artifact contracts.

That means Tier 3 should keep proving invariants like:

- queued work is runnable or explicitly deferred
- generated artifacts satisfy downstream sanity expectations
- operator/runtime surfaces reflect the real mission state

## Current philosophy

DeepLoop should bias toward:

- many **Tier 1** tests
- strong **Tier 2** wiring tests
- a smaller but high-value **Tier 3**
- a selective, explicitly bounded **Tier 4**
- a milestone-grade **acceptance campaign** above the tiers

Bounded real tests are intentionally not the default fast path.
