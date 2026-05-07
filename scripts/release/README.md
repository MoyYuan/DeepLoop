# Release scripts

Release validation now has a repo-owned Docker clean-room harness.

## Canonical entrypoints

- `python scripts/release/docker_validation.py validate-dist`
- `make docker-release-validate`
- `python scripts/release/docker_validation.py validate-pypi --install-spec deeploop==<version>`
- `make docker-release-validate-pypi VERSION=<version>`

## What the Docker harness proves today

The current harness is intentionally deterministic and provider-free:

1. build the sdist and wheel inside `docker/release-validation.Dockerfile`
2. install the built wheel in a fresh runtime image
3. verify the shipped CLI entrypoints respond
4. bootstrap the canonical `examples/translation-budget-ladder/` plain-folder example
5. confirm the generated mission state lands under the configured DeepLoop workspace root without mutating the project copy
6. bootstrap the non-translation `literature-gap-map` proof fixture and verify it surfaces the expected blocked operator-readiness contract
7. package that initialized literature mission to prove the release artifact still exposes the lightweight packaging surface cleanly
8. bootstrap the messy-start `forecast-rough-notes` fixture and verify the bounded clarifications/defaults handoff still packages cleanly
9. rerun that messy-start fixture through `--discover` to keep the discovery-first onboarding path honest
10. verify a partial project-folder bootstrap fails with the expected bounded repair diagnostics instead of mutating the project copy

`validate-pypi` reuses the same smoke helper after install from PyPI so the
post-publish check exercises the published artifact instead of the local wheel.

## Non-goals

- this is not a devcontainer or full interactive development image
- this does not replace the documented conda/uv workflows for contributors
- this does not yet prove provider-backed execution inside Docker; extend the
  in-container smoke helper only when the provider contract is ready to be
  documented and tested cleanly
