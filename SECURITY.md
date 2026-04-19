# Security policy

DeepLoop is an experimental public-alpha research repo. Please do **not** report
potential vulnerabilities in public GitHub issues.

## How to report a vulnerability

Use a private maintainer channel whenever one is available for the repository.
If private GitHub security reporting is enabled, use that path first.

If no private reporting path is available yet:

1. do **not** publish exploit details in a public issue
2. open a minimal issue requesting a private contact path, without including the
   vulnerability details
3. wait for maintainer follow-up before sharing reproduction details

## What to include

- affected file or command surface
- supported environment shape used
- exact steps to reproduce
- expected versus observed behavior
- whether the issue crosses a DeepLoop hard-gate, authority, secrets,
  provenance, licensing, or sandbox boundary

## Supported scope

This policy covers the DeepLoop repository and its documented public bootstrap,
runtime, packaging, and release-review surfaces.

Third-party substrates, local machine configuration, or separately maintained
project repos may need their own disclosure path.

## Disclosure posture

DeepLoop is still an alpha project with limited support. Maintainers will try to
acknowledge and triage good-faith reports, but there is no SLA.
