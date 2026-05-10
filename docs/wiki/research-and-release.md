# Research and release deep dive

The canonical topic pages are [Research notes](../research/README.md) and
[Release posture](../release/README.md). Use this companion page when you want
the durable-artifact and policy-oriented view that connects those surfaces.

## Research path

- capture topic notes in `docs/research/`
- keep prior-art comparisons in `docs/prior-art/`
- keep evaluation assumptions explicit in design docs and runtime contracts
- record durable mission evidence in `mission_experiments.jsonl` and
  `mission_memory.json` rather than leaving findings only in shell output
- run research sanity gates before expensive follow-up studies when config or
  evidence prerequisites are uncertain

## Release path

- keep release-planning notes in `docs/release/`
- run the release policy and review CLI before promotion
- package mission outputs before publication or handoff
- use the mission-local platform release handoff as a summary surface, not as a
  replacement for operator approval

## Post-`v0.1.2` hardening follow-ups

These items were intentionally left for post-`v0.1.2` maintainer follow-up work.
Track them as internal release hardening backlog, not as part of the published
release notes:

- [ ] [#55](https://github.com/tnetal/DeepLoop/issues/55) Investigate the
  unrelated full mission-runtime segfault
- [ ] [#56](https://github.com/tnetal/DeepLoop/issues/56) Evaluate optional
  recursive budget-warning/noise tuning
- [ ] [#57](https://github.com/tnetal/DeepLoop/issues/57) Expand smoke coverage
  beyond translation workflows

## Key references

- [Research notes](../research/README.md)
- [Release posture](../release/README.md)
- [Prior art](../prior-art/ralph-vs-autoresearch.md)
- [Evaluation plan](../design/evaluation-plan.md)
- [Experiment ledger](../design/experiment-ledger.md)
- [Research sanity gates](../design/research-sanity-gates.md)
- [Evidence policy](../design/evidence-policy.md)
- [Mission artifact package](../design/mission-artifact-package.md)
- [Platform expansion](../design/platform-expansion.md)
- [Runtime standardization](../design/runtime-standardization.md)
