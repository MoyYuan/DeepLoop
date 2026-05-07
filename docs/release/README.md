# Release posture

This page is the release-facing landing page for external researchers. It owns
the current claim, the evidence behind it, and the current non-claims. For
what is next versus later, go to
[Public autonomy roadmap](public-autonomy-roadmap.md).

DeepLoop is closer to an **experimental public alpha** than to something that
should be described as **fully automatic for everyone**.

## Honest claim today

DeepLoop can currently be shared as a **bounded-support autonomous research
autopilot** for researchers using the documented Linux bootstrap path.

That claim is backed by:

- `make public-bootstrap-check` on the documented public path
- fresh-clone / fresh-home onboarding using published docs
- a repo-owned Docker clean-room validation harness that builds artifacts, installs from a wheel in a fresh container, and runs a deterministic bootstrap smoke
- an eligible-for-promotion plain-folder proof matrix across 3 materially
  different workflow shapes
- a real release-candidate review and promotion path with required approvals
- explicit governance and autonomy-boundary docs
- user-facing operator surfaces that now expose ratchet evidence,
  temporary-gap telemetry, and bounded managed-mode recovery hints on the
  supported path
- Docker is now the preferred release-validation harness for clean-room install
  and bootstrap proof; conda and pip/uv remain the normal development paths

## Recent progress on the supported path

The release claim is still intentionally narrow, but the supported path is
stronger than it was before:

- measurable adaptation runs can now surface metric-ratchet evidence directly in
  operator-facing runtime summaries
- narrow measurable phases can opt into deterministic routing rules instead of
  relying only on generic transition fallback
- operator surfaces now expose clearer temporary-gap telemetry and managed-mode
  staged recovery hints
- the next patch release keeps the same bounded claim while hardening the
  documented path; the canonical `translation-budget-ladder` smoke path reran
  cleanly after the latest post-smoke hardening pass
- Copilot-backed recursive runs now preserve remaining loop budget on resumed
  runs, normalize generic handoffs to the supported phase defaults, and give
  Copilot-driven steps a longer idle window before they are treated as stalled
- completed missions now refresh final package manifests, while package
  validation ignores transient sandbox/runtime scratch outputs that should not
  be treated as durable release artifacts
- the GitHub Release -> PyPI path is now explicit: PyPI publish only runs from
  a published GitHub Release and rejects tags that do not match
  `project.version`

Those additions and hardening steps improve trust and reduce routine
babysitting on the documented path, but they do **not** widen the public claim
beyond bounded-support alpha.

## Honest non-claims

Do **not** describe the current release as:

- broadly installable across arbitrary environments
- fully automatic for everyone
- approval-free release promotion
- scratchpad-to-formalization automation beyond the structured project-folder
  path
- proof of broad multi-substrate portability beyond the current bounded-support
  contract

## Release page roles

Use the release docs as separate surfaces instead of repeating the same summary
everywhere:

- **Release posture** (this page): what is true now and why researchers should
  trust that claim
- [**Public alpha foundations**](public-alpha-foundations.md): the minimum
  repo-facing floor and checklist for public alpha readiness
- [**Public autonomy roadmap**](public-autonomy-roadmap.md): what is next,
  near-term, and later without changing today's claim

## Best next pages for researchers

- start using the repo: [Getting started](../getting-started.md)
- prepare provider prerequisites: [Provider setup](../reference/provider-setup.md)
- try the supported bootstrap contract: [Portable bootstrap](portable-bootstrap.md)
- review the minimum repo-facing bar: [Public alpha foundations](public-alpha-foundations.md)
- inspect remaining safety and operator boundaries: [Autonomy governance](autonomy-governance.md)
- review what comes next and what stays exploratory:
  [Public autonomy roadmap](public-autonomy-roadmap.md)

## Release docs map

- [Public autonomy roadmap](public-autonomy-roadmap.md)
- [Public alpha foundations](public-alpha-foundations.md)
- [Portable bootstrap](portable-bootstrap.md)
- [Release maintenance](release-maintenance.md)
- [Multi-substrate proof](multi-substrate-proof.md)
- [Release automation](../design/release-automation.md)
