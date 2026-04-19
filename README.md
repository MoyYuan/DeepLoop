# deeploop

DeepLoop is an autonomous research autopilot for local-first LLM research. It
runs a mission, chooses the next step from evidence, and asks for help only
when it reaches a real safety, authority, or sandbox boundary.

## Who this repo is for right now

- researchers evaluating the current **public alpha** on the documented path
- operators who want one mission runtime with `status`, an **operator inbox**,
  **inner-loop progress**, and **runtime telemetry**
- teams testing the DeepLoop/substrate split, where DeepLoop owns behavior,
  build surfaces, and generated execution logic while the **substrate** stays
  focused on minimal facts and contracts

## Current release posture

DeepLoop should currently be described as a **bounded-support autonomous
research autopilot**:

- supported now: **Linux with Python 3.11**, editable install or the documented
  Conda path, and the documented workspace roots
- backed by: `make public-bootstrap-check`, fresh-clone onboarding on the
  documented path, a 3-case plain-folder proof matrix, and a real release
  review/promotion path with approvals
- not honest to claim yet: broadly installable across arbitrary environments,
  **fully automatic for everyone**, or approval-free release promotion

For the detailed claim ladder and roadmap, start with
[Release posture](docs/release/README.md) and the
[Public autonomy roadmap](docs/release/public-autonomy-roadmap.md).

## Fastest evaluation path

1. Install DeepLoop:
   - `python -m pip install -e .`
   - or `conda env create -n deeploop -f environment.yml`
   - editable installs expose `deeploop`, `deeploop-init-mission`,
     `deeploop-run-project`, and `deeploop-package-mission`
2. Prepare workspace roots:
   - `make setup`
3. Validate the supported bootstrap contract:
   - `make public-bootstrap-check`
4. Prepare machine-level provider availability:
   - follow [Provider setup](docs/reference/provider-setup.md)
   - this covers tools, auth/env prerequisites, and readiness only
5. Choose mission/runtime provider selection:
    - follow [Provider selection](docs/reference/provider-selection.md)
    - this chooses provider family, backend, and model intent per mission/loop/phase/role
    - keep secrets and credential values outside repo config
6. Start from the public example or your own plain researcher folder:
   - canonical example:
     [`examples/translation-budget-ladder/`](examples/translation-budget-ladder/)
   - optional copy step: `cp -R examples/translation-budget-ladder <project-folder>`
   - `python scripts/mission/init_mission.py --project-root <project-folder> --force`
   - `python scripts/mission/run_project.py --project-root <project-folder> --until-complete`
   - proof fixtures remain under `tests/_proof_fixtures/plain_folder/` for validation only
7. Monitor or intervene when needed:
   - `python scripts/mission/manage_mission.py status --mission-state <mission-state.json>`
   - `python scripts/mission/manage_mission.py inbox --mission-state <mission-state.json>`

## Operator model in one screen

- default mode: `sandboxed-yolo`
- expert intervention mode: `managed`
- keep the human in the loop on important choices: `human-directed`
- DeepLoop routes work through registered `stage-kernel` executors and stops
  only when it needs a real operator decision
- when you record lessons, keep DeepLoop for runtime/product invariants,
  **skills for reusable methods**, and substrate repos for domain/science rules

## Read next

- [Docs home](docs/index.md)
- [Getting started](docs/getting-started.md)
- [Examples](docs/how-to/examples.md)
- [Plain-folder starter](docs/how-to/plain-folder-starter.md)
- [Release posture](docs/release/README.md)
- [Public autonomy roadmap](docs/release/public-autonomy-roadmap.md)
- [Portable bootstrap](docs/release/portable-bootstrap.md)
- [Provider setup](docs/reference/provider-setup.md)
- [Provider selection](docs/reference/provider-selection.md)
- [Autonomy governance](docs/release/autonomy-governance.md)
- [Multi-substrate proof](docs/release/multi-substrate-proof.md)
- [Technical reference](docs/reference/index.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
