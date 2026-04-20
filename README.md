# deeploop

DeepLoop is a local-first research autopilot for structured project folders. It
helps a researcher or operator run a mission, keep the next step tied to what
is already on disk, and step in only when the system reaches a real decision,
safety, or support boundary.

Today the honest release posture is still a **bounded-support public alpha** on
the documented Linux + Python 3.11 path.

DeepLoop owns behavior and orchestration; substrate repos own domain or science
rules.

## Why researchers and operators care

- **Less babysitting:** DeepLoop keeps durable mission state instead of relying
  on one long chat thread.
- **Visible handoffs:** `status`, `inbox`, and `resume` make operator
  intervention explicit and show when a real operator inbox opens.
- **Auditable autonomy:** runtime telemetry, inner-loop progress, and
  stage-kernel execution stay inspectable instead of hidden behind one opaque
  agent loop.
- **Keep project inputs clean:** your project folder can stay focused on facts
  and docs while DeepLoop manages runtime state elsewhere.
- **Evidence-first runs:** `status` can now surface measurable ratchets,
  reroutes, and temporary-gap recovery hints instead of leaving them buried in
  raw JSON.
- **Local-first control:** project folders, review, and release surfaces stay on
  your machine and in your repo workflow.

## Building toward

DeepLoop is building toward a research autopilot that can run longer with less
operator friction, on more machine shapes, with clearer evidence promotion and
stronger trust surfaces. This public alpha is intentionally narrow today. The
goal is not a bigger slogan first; it is a system that can earn stronger
autonomy claims by making its boundaries and proof more legible over time.

For the release-facing claim, trust, and next-step docs, start with
[Release posture](docs/release/README.md). It routes onward to the foundations
and roadmap pages when you need them.

## Fastest path to try it

1. Install DeepLoop:
   - `python -m pip install -e .`
   - or `conda env create -n deeploop -f environment.yml`
2. Prepare the documented workspace shape and verify the supported bootstrap
   path:
   - `make setup`
   - `make public-bootstrap-check`
3. Connect a provider:
   - [Provider setup](docs/reference/provider-setup.md)
   - [Provider selection](docs/reference/provider-selection.md)
4. Run the canonical example or your own plain-folder project:
   - example project:
     [`examples/translation-budget-ladder/`](examples/translation-budget-ladder/)
   - optional copy step: `cp -R examples/translation-budget-ladder <project-folder>`
   - fastest path:
     `deeploop-run-project --project-root examples/translation-budget-ladder --until-complete`
   - explicit operator path:
     `deeploop-init-mission --project-root examples/translation-budget-ladder --force`
   - on a copied folder, substitute `<project-folder>` in the commands above
5. When DeepLoop pauses for review, use the operator CLI:
   - `deeploop status --mission-state <mission-state.json>`
   - `deeploop inbox --mission-state <mission-state.json>`
   - `deeploop resume --mission-state <mission-state.json>`

The installed `deeploop*` commands above are the preferred first-run path.
Lower-level repo scripts remain available for debugging and automation.

## What operators will notice on the shipped path

- measurable adaptation runs can now surface an `adaptation_metric_ratchet`
  result and the latest reroute directly in `status`
- some missions can opt into deterministic routing for narrow measurable cases;
  when no rule matches, DeepLoop still falls back to the normal planner
- temporary-gap telemetry now separates auto-recovered versus escalated gaps and
  shows recurring categories
- in managed mode, DeepLoop can stage one bounded retry, reroute, or downscope
  step for review before you `resume`

## Day-1 reality

DeepLoop is useful today when the work already fits a supported structured path:
a project folder on disk, a clear mission, and an operator who can check
`status` or `inbox` when asked. It is not yet the best fit for messy scratchpad
ideation, notebook-style wandering, or "start from nothing and figure it out"
research sessions. The scratchpad -> formalization bridge is still exploratory,
not part of the current alpha promise.

## Where DeepLoop fits today

| System | Best fit today | What stands out | Honest tradeoff |
| --- | --- | --- | --- |
| **DeepLoop** | Operator-visible research runs from a local project folder | Explicit mission state, operator handoff surfaces, packaging/release posture, evidence-aware workflow | Supported path is still narrow today, and the product is not yet ideal for messy ideation |
| **Ralph** | Lightweight recursive coding loops around a PRD | Fresh-context shell loop, simple external memory, very low orchestration overhead | More centered on software delivery than on evidence-heavy research programs |
| **AutoResearch** | Repeated experiment hill-climbing on one editable surface | High automation density, metric-driven branch advancement, strong experiment cadence | Narrower single-task/single-metric shape with less operator/governance structure |

For the deeper reasoning behind this comparison, see
[Ralph vs AutoResearch for DeepLoop](docs/prior-art/ralph-vs-autoresearch.md).

## Current limits, proof, and deeper links

| Surface | Today | Where to go deeper |
| --- | --- | --- |
| **Supported path** | Documented Linux with Python 3.11 bootstrap lane, editable install or documented Conda path, and the documented workspace roots | [Portable bootstrap](docs/release/portable-bootstrap.md) |
| **What backs the current claim** | `make public-bootstrap-check`, fresh-clone onboarding on the documented path, a 3-case plain-folder proof matrix, and a reviewed release promotion path | [Release posture](docs/release/README.md) |
| **What DeepLoop is not claiming yet** | Broad installability across arbitrary environments, "fully automatic for everyone," or approval-free release promotion | [Release posture](docs/release/README.md) |

## Operator model in one screen

- most people start with `sandboxed-yolo`
- use `managed` when you want intervention hooks before DeepLoop continues
- use `human-directed` when you want to approve important choices yourself
- the normal loop is: start a mission, check `status`, open the operator inbox
  when asked, then `resume`
- when you record lessons, keep skills for reusable methods and domain/science
  rules in substrate repos
- DeepLoop may still propose additional trusted datasets when the science
  requires them, even while the substrate stays minimal

## Read next

### Using DeepLoop

- [Docs home](docs/index.md)
- [Getting started](docs/getting-started.md)
- [Examples](docs/how-to/examples.md)
- [Plain-folder starter](docs/how-to/plain-folder-starter.md)
- [Release posture](docs/release/README.md)
- [Portable bootstrap](docs/release/portable-bootstrap.md)
- [Provider setup](docs/reference/provider-setup.md)
- [Provider selection](docs/reference/provider-selection.md)
- [Autonomy governance](docs/release/autonomy-governance.md)
- [Multi-substrate proof](docs/release/multi-substrate-proof.md)
- [Technical reference](docs/reference/index.md)

### Contributing or maintaining

- [Contributor and developer docs](docs/contributors/index.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
