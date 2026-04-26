# Portable bootstrap

This page defines what DeepLoop must provide before setup can be described as
portable beyond this research box.

## Goal

A new user should be able to:

1. install DeepLoop on a supported machine
2. prepare the workspace
3. validate the environment
4. prepare provider readiness on the machine
5. choose provider/model selection for the mission
6. materialize a mission state
7. start and monitor a mission

without relying on undocumented machine-specific assumptions.

## Supported-environment contract

DeepLoop should describe support as explicit tiers instead of vague
"works anywhere" language.

| Tier | Meaning |
| --- | --- |
| **Supported now** | Linux with Python 3.11, editable install or the documented Conda path, and the documented workspace/output roots |
| **Near-term target** | Linux CPU-only and Linux GPU setups with the same bootstrap flow |
| **Later target** | Bounded cloud and runner environments with the same validation contract |

## Portable bootstrap checklist

### 1. Environment setup

- install Python and the documented dependencies
- create the DeepLoop environment from the repo contract
- make the intended provider family available on the machine through the
  canonical provider setup contract
- avoid requiring undiscoverable local shell customizations

### 2. Workspace preparation

- materialize output roots through `make setup`
- keep mutable artifacts outside the repo
- document what paths are required and why

### 3. Validation

At minimum the public bootstrap path should verify:

- the workspace roots exist
- Python imports succeed
- the repo control-plane scaffold is intact
- the default contributor confidence path runs cleanly
- provider setup is discoverable as a separate machine-level contract from
  mission/runtime provider-model selection
- provider selection is discoverable as its own mission/runtime contract

### 4. First mission flow

The quickstart should use placeholders such as:

- `<project-folder>`
- `<mission-config.yaml>`
- `<mission-state.json>`

instead of hardcoded personal paths as the only visible examples.

## Public bootstrap path

The current intended path is:

1. install the environment described by the repo — choose the mode that matches
   your use case:
   - **Standard user** (running missions, not modifying DeepLoop source):
     `python -m pip install .`
   - **Contributor** (developing DeepLoop features):
     `python -m pip install -e .` — do **not** modify source, switch branches,
     or introduce syntax errors while a mission is running in the background
   - **Hybrid user** (missions + development simultaneously): use two separate
     clones; run missions only from the non-editable clone
   - or `conda env create -n deeploop -f environment.yml`
2. run `make setup`
3. run:
     - `make public-bootstrap-check`
    - or the narrower environment-only check:
      - `make public-bootstrap-preflight`
4. prepare provider readiness on the machine:
    - review [Provider setup](../reference/provider-setup.md)
    - use `configs/runtime/provider-setup-registry.yaml` as the machine-readable registry
    - keep this separate from mission/runtime provider-model selection
5. choose mission/runtime provider selection:
     - review [Provider selection](../reference/provider-selection.md)
     - use `configs/runtime/provider-selection-registry.yaml` as the selection registry
     - keep secrets and credential values outside repo config
6. initialize a mission:
     - canonical public starter: `examples/translation-budget-ladder/`
     - optional copy step: `cp -R examples/translation-budget-ladder <project-folder>`
     - `python scripts/mission/init_mission.py --project-root <project-folder> --force`
     - `python scripts/mission/init_mission.py --config <mission-config.yaml> --force`
     - `python scripts/mission/run_project.py --project-root <project-folder> --until-complete`
7. start and monitor the mission:
     - `python scripts/mission/manage_mission.py start --mission-state <mission-state.json>`
     - `python scripts/mission/manage_mission.py status --mission-state <mission-state.json>`

The preferred substrate-respecting bootstrap is now the project-folder path:
DeepLoop should derive the mission config from the folder's minimal facts rather
than requiring users to hand-author mission YAML before first contact.

For the plain-artifacts bootstrap path, the project folder can remain a
researcher-style substrate with facts/artifacts only and **no project-local `.deeploop/` contract**.

The `run_project.py --until-complete` surface is the beginning of the true
product path for plain-folder projects: DeepLoop bootstraps the mission and then
keeps extending the bounded runtime until completion, operator review, or the
configured total iteration budget.

## Current validation status

The limited public-alpha bootstrap contract is now validated on:

- a local Linux workstation using the documented workspace layout
- a clean GitHub Actions Ubuntu runner through `make public-bootstrap-check`
- a Python 3.12 CI preflight lane that validates the environment contract before
  running the full bootstrap path
- docs/build/contract checks that keep the public provider setup and provider
  selection surfaces, plus the public examples surface, present and linked from
  onboarding docs

Provider auth and endpoint reachability are still outside
`make public-bootstrap-check`; provider selection is now documented separately
but remains an operator-managed mission/runtime input for now.

## Environment preflight

DeepLoop now exposes a dedicated preflight check:

```text
python scripts/public_bootstrap_preflight.py
make public-bootstrap-preflight
```

This validates:

- Python version
- operating system
- workspace root availability
- required external DeepLoop workspace directories

The goal is to fail early with an explicit contract mismatch instead of letting a
new researcher discover a machine assumption only after bootstrap has already
started.

## What is still not portable enough

DeepLoop still needs improvement before setup is broadly installable:

- support is still limited to Linux with Python 3.11 and the documented
  workspace roots
- Python 3.12 now has a narrower CI preflight lane, but the full supported
  public-bootstrap claim remains conservative until the broader path is proven at
  that version too
- some higher-tier proofs still depend on substrate-local assets
- broader OS, runner, and local-inference environment portability still needs
  proof beyond the current limited contract

## Promotion rule

Do not describe DeepLoop as broadly installable beyond the current limited
Linux + Python 3.11 contract until stronger portability proof exists.

## Related docs

- [Getting started](../getting-started.md)
- [Examples](../how-to/examples.md)
- [Provider setup](../reference/provider-setup.md)
- [Provider selection](../reference/provider-selection.md)
- [Plain-folder starter](../how-to/plain-folder-starter.md)
- [Public alpha foundations](public-alpha-foundations.md)
- [Public autonomy roadmap](public-autonomy-roadmap.md)
