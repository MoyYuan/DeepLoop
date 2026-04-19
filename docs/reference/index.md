# Technical reference

Use this page when you already understand the basics and want implementation
detail.

## Content map

Use these surfaces intentionally so the docs stay organized:

| Surface | Use it for | Avoid using it for |
| --- | --- | --- |
| `README.md` | Short project landing page and docs entry | Full operator or architecture explanations |
| `examples/` | Public-safe starter projects and onboarding inputs | Proof-only metadata or test harness details |
| `docs/guide/` | Task-based operator help | Low-level implementation notes |
| `docs/concepts/` | Plain-language mental models | File-by-file runtime details |
| `docs/reference/` | Curated map into deeper material | Duplicating beginner guides |
| `docs/design/` | Implementation notes and design detail | Competing “start here” pages |
| `docs/wiki/` | Companion deep dives and historical context | The primary docs path for new readers |
| `docs/research/` / `docs/release/` | Research and release notes | Generic docs navigation |

## Canonical runtime surfaces

Use these as the technical map for the current mission runtime:

- `scripts/mission/manage_mission.py` — canonical operator CLI for `start`,
  `resume`, `status`, `inbox`, `logs`, `decisions`, `watch`, `triage`,
  `retry`, `reroute`, and `stop`
- `src/deeploop/mission/mission_management.py` — command parser, detached launch
  control, and the rendered operator surfaces
- `src/deeploop/mission/_operator_surface.py` — shared operator-state
  vocabulary (`lifecycle_state`, `operator_state`, `attention_level`,
  `next_step_owner`, `resume_policy`)
- `scripts/mission/run_mission.py` — backend detached mission runtime launched
  by `manage_mission.py`
- `scripts/mission/monitor_mission.py` and
  `src/deeploop/mission/mission_monitor.py` — backend snapshot and monitoring
  surfaces that feed `status` / `inbox`
- `docs/reference/provider-setup.md` — canonical public contract for
  machine-level provider availability and readiness
- `configs/runtime/provider-setup-registry.yaml` — machine-readable registry for
  first-class provider families, prerequisites, env vars, and readiness checks
- `docs/reference/provider-selection.md` — canonical public contract for
  mission/runtime provider, backend, model, fallback, and override selection
- `configs/runtime/provider-selection-registry.yaml` — machine-readable registry
  for provider-selection profiles, fallbacks, override points, and linked
  runtime surfaces
- `configs/runtime/backend-policy.yaml` — current local inference backend
  defaults; related to runtime behavior, but not the canonical source for
  machine-level provider setup or mission-time provider/model selection by
  itself

## Public examples

- [Examples](../how-to/examples.md)
- [Plain-folder starter](../how-to/plain-folder-starter.md)

## Providers

- [Provider setup](provider-setup.md)
- [Provider selection](provider-selection.md)

## Testing

- [Testing strategy](testing-strategy.md)
- [Acceptance campaign](acceptance-campaign.md)

## Runtime and orchestration

- [Operating model](../design/operating-model.md)
- [Mission orchestrator](../design/mission-orchestrator.md)
- [State machine](../design/state-machine.md)
- [Role contract](../design/role-contract.md)
- [Stage kernels](../design/stage-kernels.md)
- [Runtime standardization](../design/runtime-standardization.md)
- [Self-healing runtime](../design/self-healing-runtime.md)
- [Recursive agent runtime](../design/recursive-agent-runtime.md)
- [Bounded autoexecutor](../design/bounded-autoexecutor.md)
- [Platform expansion](../design/platform-expansion.md)

## Evidence and evaluation

- [Evaluation plan](../design/evaluation-plan.md)
- [Evidence policy](../design/evidence-policy.md)
- [Experiment ledger](../design/experiment-ledger.md)
- [Statistical rigor](../design/statistical-rigor.md)
- [Confound guard](../design/confound-guard.md)
- [Research sanity gates](../design/research-sanity-gates.md)
- [Mission meta-eval](../design/mission-meta-eval.md)
- [Utility scorer](../design/utility-scorer.md)
- [Memory registry](../design/memory-registry.md)
- [Mission artifact package](../design/mission-artifact-package.md)

## Release and research

- [Research notes](../research/README.md)
- [Release posture](../release/README.md)
- [Release maintenance](../release/release-maintenance.md)
- [Public autonomy roadmap](../release/public-autonomy-roadmap.md)
- [Public alpha foundations](../release/public-alpha-foundations.md)
- [Portable bootstrap](../release/portable-bootstrap.md)
- [Autonomy governance](../release/autonomy-governance.md)
- [Multi-substrate proof](../release/multi-substrate-proof.md)
- [Plain-folder starter](../how-to/plain-folder-starter.md)
- [Prior art](../prior-art/ralph-vs-autoresearch.md)
- [Release automation](../design/release-automation.md)
- [Autonomy boundary reduction](../design/autonomy-boundary-reduction.md)
- [Rollout plan](../design/rollout-plan.md)

## Docs maintenance

- [Docs maintenance](docs-maintenance.md)

## If you are new

Go to:

1. [Getting started](../getting-started.md)
2. [Mission operations](../guide/operator.md)
3. [Runtime architecture](../concepts/architecture.md)
