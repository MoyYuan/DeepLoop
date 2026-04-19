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

Once your folder exists, the supported bootstrap path is:

```text
make public-bootstrap-check
python scripts/mission/run_project.py --project-root <project-folder> --until-complete
```

`make public-bootstrap-check` proves the install, workspace setup, repo
contract, and plain-folder bootstrap surfaces on a clean Linux + Python 3.11
environment.

## Why this matters

DeepLoop's public-alpha share story depends on a truthful substrate boundary:

- the project folder stays minimal
- DeepLoop synthesizes mission config from project facts
- DeepLoop runtime and package state live outside the project folder
- the same plain-folder contract works in docs, tests, and CI
