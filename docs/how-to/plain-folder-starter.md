# Plain-folder starter

This is the easiest way to understand what DeepLoop expects from a
researcher-owned project folder. The repo-root `examples/` directory is the
public onboarding surface for this contract.

## Minimal structure

A plain-folder project keeps DeepLoop behavior outside the project folder and
contains only the minimum facts and docs DeepLoop needs to bootstrap:

```text
<project-folder>/
├── project-facts.yaml
└── docs/
    ├── project-brief.md
    └── benchmark-and-metrics.md
```

Optional supporting docs are fine, but the folder should stay researcher-owned
input only.

## Required files

### `project-facts.yaml`

At minimum, include:

- `project.name`
- `project.objective`
- `artifacts.docs`

You can also include:

- `project.title`
- `project.summary`
- `project.constraints`
- `project.human_inputs` such as budget facts or starting ideas
- `artifacts.configs` for YAML/JSON/TOML configuration inputs
- `artifacts.data` for datasets, labels, splits, predictions, and benchmark
  files that should not be treated as configs
- operational contract fields such as `project.acceptance_criteria`,
  `artifact_contract`, `budgets`, `data`, and `evaluation_contract`

Dataset entries may be simple paths or metadata records:

```yaml
artifacts:
  docs:
    - docs/project-brief.md
  configs:
    - configs/experiment.yaml
  data:
    - path: data/train.csv
      kind: tabular-timeseries
      format: csv
      role: primary-dataset
      read_only: true
      prompt_safe: header-and-summary-only
      split_keys: [dt, pred_dt]
      packaging_policy: reference-only
```

DeepLoop preserves the dataset metadata in mission state, surfaces it to
dataset and execution roles, and keeps these files out of `mission_configs`.
If a CSV or other non-config file is declared under `artifacts.configs`,
DeepLoop emits a warning so the contract can be corrected.
DeepLoop also promotes those known contract fields into the generated mission
config and recursive-agent prompts. Prompts include a visible `Mission
acceptance criteria` section so concrete pass/fail requirements, required
artifacts, budgets, data assumptions, and evaluation requirements stay in
active runtime context rather than only preserved metadata. Unknown top-level
fields in `project-facts.yaml` are preserved in the discovered project
contract and reported as not operationalized so they do not look silently
enforced.

## What must stay out of the project folder

Do **not** put DeepLoop-owned runtime state into the starter folder:

- no `.deeploop/` runtime contract is required for the plain-folder path
- no generated mission configs
- no run outputs, ledgers, package artifacts, or build code

Those belong under DeepLoop's workspace roots outside the researcher folder.

## Canonical public example

The canonical public example now lives at:

- `examples/translation-budget-ladder/`

It shows a concrete starter folder with:

- `project-facts.yaml`
- `docs/project-brief.md`
- `docs/benchmark-and-metrics.md`
- `docs/budget-and-baselines.md`

The proof matrix still keeps a validation-only mirror at:

- `tests/_proof_fixtures/plain_folder/translation-budget-ladder/`

That proof fixture remains useful because it adds proof metadata such as
`proof-case.yaml`, but it should not be the main visible example path for new
users. See [Examples](examples.md) for the public example surface.

## First-run path

The unified first-run path is:

```text
deeploop setup
deeploop preflight
deeploop run --until-complete
```

That no-argument path creates a bundled starter project under
`WORKSPACE_ROOT/projects/` and launches the same mission flow a user gets from
an existing folder.

If that run pauses, stay on the same operator loop every time: `status`,
`inbox`, then `resume`. Treat `logs`, `decisions`, `retry`, `reroute`, and
`triage` as secondary detail surfaces.

Once your own folder exists, the matching existing-project path is:

```text
deeploop run --project-root <project-folder> --until-complete
```

If you are in a repo checkout, `make public-bootstrap-check` still proves the
install, workspace setup, repo contract, and plain-folder bootstrap surfaces on
a clean Linux + Python 3.11 environment.

## Messy starts and repair boundaries

DeepLoop does not require every real project folder to look as polished as the
canonical example on day one.

- if the folder is usable but rough, `deeploop init --project-root
  <project-folder> --force` can produce a mission state with a readiness summary
  such as `ready-with-clarifications`
- if you want DeepLoop to ask follow-up questions first, use
  `deeploop init --discover --project-root <project-folder> --force`
- if the folder is missing the plain-folder bootstrap contract entirely,
  DeepLoop exits with bounded bootstrap-repair guidance, reports the missing
  inputs, and may generate a starter scaffold path to copy into place before
  rerunning

In all three cases, keep the public entry point the same: the installed
`deeploop` CLI.

## Why this matters

DeepLoop's public-alpha share story depends on a truthful substrate boundary:

- the project folder stays minimal
- DeepLoop synthesizes mission config from project facts
- DeepLoop runtime and package state live outside the project folder
- the same plain-folder contract works in docs, tests, and CI
