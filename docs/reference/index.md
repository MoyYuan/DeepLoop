# Technical reference

Use this page when you already understand the basics and want the supported
technical contracts, runtime surfaces, and advanced operator references.

If you are changing DeepLoop itself rather than using it, go to
[Contributor and developer docs](../contributors/index.md).

## Content map

Use these surfaces intentionally so the docs stay organized:

| Surface | Use it for | Avoid using it for |
| --- | --- | --- |
| `README.md` | Short project landing page and docs entry | Full operator or architecture explanations |
| `examples/` | Public-safe starter projects and onboarding inputs | Proof-only metadata or test harness details |
| `docs/guide/` | Task-based operator help | Low-level implementation notes |
| `docs/concepts/` | Plain-language mental models | File-by-file runtime details |
| `docs/reference/` | Supported technical contracts and advanced runtime references | Duplicating beginner guides or maintainer-only notes |
| `docs/contributors/` | Maintainer/developer entry points | Competing “start here” pages for users |
| `docs/design/` | Implementation notes and design detail | The primary docs path for new readers |
| `docs/wiki/` | Companion deep dives and historical context | The default user journey |
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

## Release and research

- [Research notes](../research/README.md)
- [Release posture](../release/README.md)
- [Release maintenance](../release/release-maintenance.md)
- [Public alpha foundations](../release/public-alpha-foundations.md)
- [Portable bootstrap](../release/portable-bootstrap.md)
- [Autonomy governance](../release/autonomy-governance.md)
- [Multi-substrate proof](../release/multi-substrate-proof.md)
- [Plain-folder starter](../how-to/plain-folder-starter.md)
- [Prior art](../prior-art/ralph-vs-autoresearch.md)

## Maintainers: start here instead

If you are debugging runtime behavior, changing contracts, or maintaining the
repo, use the contributor lane below before diving into lower-level design
material from user-facing pages.

- [Contributor and developer docs](../contributors/index.md)
- [Testing strategy](testing-strategy.md)
- [Acceptance campaign](acceptance-campaign.md)
- [Docs maintenance](docs-maintenance.md)
- [Design notes](../design/README.md)
- [Companion deep dives](../wiki/README.md)

## If you are new

Go to:

1. [Getting started](../getting-started.md)
2. [Mission operations](../guide/operator.md)
3. [Runtime architecture](../concepts/architecture.md)
