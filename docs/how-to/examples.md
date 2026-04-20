# Examples

DeepLoop's public-safe starter projects live in the repo-root `examples/`
directory.

## Canonical onboarding example

The canonical public example is `examples/translation-budget-ladder/`.

It is the same plain-folder contract described in
[Plain-folder starter](plain-folder-starter.md), but surfaced as a first-class
public example instead of a test fixture.

```text
examples/translation-budget-ladder/
├── project-facts.yaml
└── docs/
    ├── project-brief.md
    ├── benchmark-and-metrics.md
    └── budget-and-baselines.md
```

Use it as-is or copy it into your own `<project-folder>` before editing:

```text
cp -R examples/translation-budget-ladder <project-folder>
deeploop-run-project --project-root <project-folder> --until-complete
```

That is the fastest happy path for trying DeepLoop on the canonical public
example.

If you want the explicit operator flow first, use the installed CLI surfaces
directly:

```text
deeploop-init-mission --project-root <project-folder> --force
deeploop start --mission-state <mission-state.json>
deeploop status --mission-state <mission-state.json>
```

If `deeploop-run-project` stops for operator review instead of finishing, reuse
the printed `<mission-state.json>` with `deeploop status`, `deeploop inbox`,
and `deeploop resume`.

Lower-level repo scripts remain available as fallback surfaces when useful:

```text
python scripts/mission/init_mission.py --project-root <project-folder> --force
python scripts/mission/run_project.py --project-root <project-folder> --until-complete
python scripts/mission/manage_mission.py status --mission-state <mission-state.json>
```

## Why this example is public-safe

- researcher input only
- no `.deeploop/`, generated configs, runtime outputs, or secrets
- aligned with the bounded-support Linux + Python 3.11 onboarding path

## What stays test-only

Proof-matrix fixtures still live under `tests/_proof_fixtures/plain_folder/`.
The matching translation fixture remains useful for validation because it adds
proof metadata such as `proof-case.yaml`, but it is no longer the main visible
example path for new users.
