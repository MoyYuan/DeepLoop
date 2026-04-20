# Public alpha foundations

This page defines the minimum repo foundations DeepLoop should satisfy to be
marketed as a public alpha. It owns the public-alpha floor and checklist, not
the roadmap. Use [Release posture](README.md) for the current release claim and
[Public autonomy roadmap](public-autonomy-roadmap.md) for next-versus-later
staging.

## Why this is separate

DeepLoop can have strong runtime ideas and still be a weak public repository.

Public alpha readiness is not the same as:

- a strong local mission runtime
- one successful substrate proof
- internal operator familiarity

It requires repo-facing foundations that outside contributors and researchers can
see, install, run, and trust.

## Minimum checklist

### 1. Legal and repository identity

- add a visible OSS `LICENSE`
- keep the README honest about current maturity and non-goals
- define contribution and support posture clearly

### 2. Installation and packaging

- add a packaging/install surface such as `pyproject.toml`
- document the supported Python version and dependency install path
- ensure editable install or equivalent works on a clean machine

### 3. Public CI

- add public CI beyond docs-only workflows
- validate at least the default contributor confidence path:
  - `make repo-check`
  - `make test-unit`
  - `make test-integration`
- add smoke and bounded-real release gates only where the environment contract
  is explicit and reproducible

### 4. Documentation quality

- provide a public quickstart using placeholders instead of hardcoded personal
  paths
- state what DeepLoop currently supports
- state what still requires expert operator involvement
- link the release posture hub directly so future-stage work routes through the
  roadmap from there

### 5. Release operations

- define versioning and release note expectations
- define issue and bug-report intake posture
- keep mission/package promotion distinct from repo/public release readiness

## Current state

At the current scope, DeepLoop now clears the repo-facing public-alpha bar for a
limited environment contract:

- visible OSS `LICENSE`
- packaging/install surface through `pyproject.toml`
- public CI for repo, docs, smoke, and bootstrap surfaces
- explicit contribution, security, and conduct posture
- machine-agnostic quickstart and release/governance docs
- clean-room bootstrap validation through `make public-bootstrap-check`

That makes DeepLoop shareable as an **experimental public alpha** for:

- Linux
- Python 3.11
- the documented workspace roots

## What still does not follow from this

Public alpha at this stage does **not** mean:

- broadly installable across arbitrary operating systems or runner shapes
- fully automatic for everyone
- release-grade package promotion without the existing claim-state and approval
  gates
- removal of operator-only safety, authority, provenance, licensing, or external
  release boundaries

## Promotion rule

Do not claim more than this limited public-alpha bar from this checklist alone.
The current release claim lives in [Release posture](README.md), and any
stronger staged work lives in
[Public autonomy roadmap](public-autonomy-roadmap.md).

## Related docs

- [Release posture](README.md)
- [Public autonomy roadmap](public-autonomy-roadmap.md)
- [Portable bootstrap](portable-bootstrap.md)
- [Release maintenance](release-maintenance.md)
- [Autonomy governance](autonomy-governance.md)
- repository-root `CONTRIBUTING.md`
- [Release automation](../design/release-automation.md)
