# Release scripts

Place deterministic helpers for packaging manifests, reports, or future release
artifacts here when those workflows are ready.

Mission bootstrap now materializes release-automation handoff stubs under each
mission's `runtime/platform/` directory. Future release helpers should consume
those stable paths instead of inventing a parallel release root.
