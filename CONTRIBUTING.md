# Contributing to DeepLoop

DeepLoop is currently an **experimental public alpha / local-first research
autopilot** repo for Linux with Python 3.11, not a finished "fully automatic
for everyone" platform. Contributions should help the repo become more
installable, more truthful, and more reproducible.

## Before you open a pull request

1. Keep public claims honest. Do not market DeepLoop beyond what the current
   proofs, docs, and release gates actually support.
2. Preserve the substrate boundary. DeepLoop-owned runtime/config/build state
   should stay outside researcher project folders unless the contract explicitly
   says otherwise.
3. Prefer reusable runtime/docs/test improvements over one-off local demos.

## Local validation baseline

Run the narrowest relevant checks, and use this default baseline for repo-facing
changes:

```text
make repo-check
make test-unit
make test-integration
```

Add stronger coverage when your change touches those surfaces:

- `make public-bootstrap-check` for public bootstrap, quickstart, and starter-path changes
- `make test-smoke` for tiny real artifact flows
- `make test-real` for bounded production-like proof surfaces
- `make docs-build` for docs or quickstart changes

## Bug reports and issue quality

Please include:

- the supported environment shape you used
- the exact command you ran
- whether you used the plain-folder bootstrap or an explicit mission config
- the mission status and operator inbox state
- the relevant mission/package paths when safe to share
- the smallest reproduction you can provide

If the issue is about release readiness or artifact truthfulness, include the
package manifest and release review output when available.

Do not use the public bug-report path for security vulnerabilities; follow
`SECURITY.md` instead.

## Pull request expectations

- explain the user-visible change
- mention any autonomy or operator-boundary impact
- mention any artifact / packaging / release-review impact
- mention any docs that needed to change with the code

When a change affects public posture, quickstart, or release gates, include a
brief note on how it changes the honest claim DeepLoop can make.

## Release notes posture

Release-facing changes should call out one or more of:

- bootstrap / install contract changes
- runtime / operator behavior changes
- artifact package or release-review changes
- proof / CI / validation changes
- public docs or governance changes
- security / support / conduct changes

## Non-goals for contributions

- weakening package or release contracts to make results look stronger
- hiding operator boundaries instead of classifying or reducing them
- adding DeepLoop runtime junk inside researcher-owned substrate folders
- replacing reusable contracts with machine-local assumptions

## Support posture

DeepLoop currently has a best-effort maintainer posture with no SLA. Public
alpha means outside researchers can inspect and try the repo under documented
boundaries; it does **not** mean every workflow or environment is already
supported.
