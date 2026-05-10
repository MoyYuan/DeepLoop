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
- keep maintainer-only release backlog notes in
  `docs/release/release-maintenance.md` or linked GitHub issues, not in this
  companion deep dive
- use the mission-local platform release handoff as a summary surface, not as a
  replacement for operator approval

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
