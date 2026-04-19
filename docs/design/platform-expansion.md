# Platform expansion coordination

DeepLoop already ships a shared platform-expansion contract that mission
bootstrap, mission runtime sync, packaging, and release review all consume. The
contract lives in `configs/platform/expansion.yaml`, and the runtime helper
lives in `src/deeploop/platform/contracts.py`.

## Current behavior

- Mission init materializes `runtime/platform/` handoff records for the
  scheduler, indexed-memory, and release-automation surfaces.
- Mission state stores `platform_expansion` so runtime, packaging, and operator
  review all reuse the same durable paths.
- `sync_platform_expansion_bundle(...)` refreshes those records from live
  mission state:
  - `scheduler` mirrors queue, dispatch, and summary artifacts from
    `mission_scheduler`
  - `indexed_memory` catalogs mission memory, experiment ledger, mission ledger,
    and research-memory sources into durable ingest-job records
  - `release_automation` drafts release-candidate requests and release notes
    from package and review outputs
- `tests/test_platform_integration.py` exercises scheduler, indexed-memory, and
  release-automation as one integrated path.

## Stable surface rules

- **Scheduler** must keep using the published queue and dispatch-log paths under
  `runtime/platform/scheduler/`.
- **Indexed memory** must point only at durable mission artifacts and stable
  contracts, not transient shell logs.
- **Release automation** must stay anchored to mission package and release-review
  artifacts so promotion decisions remain auditable.

## Real roadmap limits

- Indexed memory is still a mission-linked catalog plus ingest-job surface; it
  is not yet a separate long-lived cross-mission indexing service.
- Release automation can draft requests and notes, but operator review remains
  the canonical approval gate for promotion.
- Scheduler integration is mission-linked and file-backed today, not a separate
  external control plane.
