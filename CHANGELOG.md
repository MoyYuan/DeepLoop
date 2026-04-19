# Changelog

All notable public-facing changes to DeepLoop should be recorded here.

The project is still in `0.x` public-alpha development. Entries should focus on
changes that affect:

- install / bootstrap contracts
- runtime or operator behavior
- package or release-review behavior
- proof / CI / validation surfaces
- public docs, governance, trust, and support posture

## 0.1.0

Initial public-alpha share-readiness baseline.

### Added

- MIT license and packaging metadata through `pyproject.toml`
- public CI for repo checks, unit, integration, smoke, docs, and public
  bootstrap validation
- explicit autonomy-governance inventory and release-facing docs
- SECURITY and code-of-conduct surfaces
- public release-maintenance guidance
- plain-folder starter guidance tied to tested proof fixtures

### Changed

- plain-folder missions now materialize executor-backed late-phase follow-ups
- plain-folder packages now include truthful manifest and critique-report
  coverage
- public bootstrap docs now point to `make public-bootstrap-check` as the
  supported clean-room validation path
- public docs now describe DeepLoop as an experimental public alpha for Linux
  with Python 3.11, not "fully automatic for everyone"
