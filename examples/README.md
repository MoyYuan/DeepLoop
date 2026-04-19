# Public examples

DeepLoop's public-safe starter projects live in the repo-root `examples/`
directory.

## Canonical onboarding example

- `translation-budget-ladder/` — the main public plain-folder example for
  onboarding, bootstrap docs, and public bootstrap validation

## Reusable templates

- `templates/mission-config.template.yaml` — copy/edit mission config scaffold
  for cases where you want an explicit mission YAML instead of bootstrapping from
  a project folder

This example stays within the current bounded-support posture:

- researcher-owned input only
- no `.deeploop/` runtime state, generated configs, or secrets
- aligned with the documented Linux + Python 3.11 onboarding path

## Validation-only fixtures

Proof-matrix fixtures still live under `tests/_proof_fixtures/plain_folder/`.
The matching translation proof fixture remains useful for test metadata such as
`proof-case.yaml`, but new users should start from `examples/` instead of the
test-only fixture tree.
