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
deeploop run --project-root <project-folder> --until-complete
```

That is the fastest happy path for trying DeepLoop on the canonical public
example.

If your own folder is rougher than the canonical example, stay on the installed
CLI surfaces:

```text
deeploop init --project-root <project-folder> --force
deeploop init --discover --project-root <project-folder> --force
deeploop start --mission-state <mission-state.json>
deeploop status --mission-state <mission-state.json>
```

Use plain `deeploop init --project-root ...` when the folder already has enough
signal for DeepLoop to disclose clarifications/defaults and continue without
rewriting the project. Use `--discover` when you want DeepLoop to ask
clarifying questions, keep a checklist of missing pieces, and compile the
mission before kickoff.

If the folder is too incomplete for either path, DeepLoop exits with
bootstrap-repair guidance instead of mutating the example or your project root.

If `deeploop run` stops for operator review instead of finishing, reuse
the printed `<mission-state.json>` with `deeploop status`, `deeploop inbox`,
and `deeploop resume`.

Lower-level repo scripts remain available as fallback surfaces when you are
debugging repo internals rather than using the public CLI:

```text
python scripts/mission/init_mission.py --discover --mission-idea "I have a dataset and a rough goal"
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
