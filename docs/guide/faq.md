# FAQ

## What is DeepLoop?

DeepLoop is an autonomous research autopilot. It runs a mission, picks the next
step, and asks for help only when it reaches a real blocker.

## What is a mission?

A mission is a long-running research run with a durable state file, decision
log, branch log, and runtime summary.

## What command should I start with?

Use `deeploop status --mission-state <mission-state.json>`. It is the canonical
operator console and tells you the current state, the recommended next step,
and the exact next commands. The repo-level
`python scripts/mission/manage_mission.py` surface still exists as a fallback
for debugging and automation.

## What should I do if DeepLoop stops?

Open `status` first.

- If it shows `operator-action-required`, read `inbox`, make the smallest safe
  fix, then resume.
- If it shows `needs-investigation`, inspect `logs` and `decisions` before
  resuming.
- If it shows `autopilot-ready-to-resume`, the last run ended after a soft-gate
  recovery path and another bounded `resume` is optional.
- In managed mode, use `triage` first when a blocked queue exposes intervention
  hooks.
- In managed mode, `status` or `inbox` may also tell you that DeepLoop already
  staged the next bounded retry, reroute, or downscope step.

## What is the difference between `status` and `inbox`?

- `status` is the full operator console: lifecycle state, operator state,
  monitoring summary, and exact next commands.
- `inbox` is the current operator request: blocker, recommendation,
  alternatives, and continue command.

## What new evidence might show up in `status`?

On measurable runs, `status` may show `adaptation_metric_ratchet` and
`last_reroute` so you can see the bounded keep/discard/route result without
opening raw JSON. On recovery-heavy runs, it may also show temporary-gap
counts, categories, and whether DeepLoop auto-recovered or escalated the latest
gap. In managed mode, it may tell you the next bounded recovery step was
already staged.

## What does `autopilot-recovering` mean?

It means DeepLoop hit a soft gate but is still running its own bounded recovery
path. Usually you just keep watching. In managed mode, DeepLoop may also stage
the next bounded recovery step for you so the next `resume` uses that path.

## What does `needs-investigation` mean?

It means the mission is blocked, failed, paused, or the detached process exited.
Do not blindly resume; inspect the surfaced blocker first.

## What is a soft gate?

A soft gate is a recoverable issue. DeepLoop should usually retry, reroute, or
downscope before bothering the operator. The operator console now also shows
temporary-gap counts and categories so you can tell whether DeepLoop is already
absorbing those issues or still escalating them.

## What does deterministic routing v1 actually mean?

It means some mission configs can predeclare a next route for narrow measurable
cases, usually after a ratchet result. It is opt-in and narrow on purpose.
When no rule matches, DeepLoop still falls back to its normal planning path.

## What is a hard gate?

A hard gate is a real safety, authority, or sandbox boundary. DeepLoop should
stop and wait for review.

## What does bounded support mean?

It means the repo is currently supported on the documented Linux + Python 3.11
path with the documented workspace roots. It is not yet a claim of broad
portability or fully automatic operation everywhere.

## Can DeepLoop start from a scratchpad and formalize it for me?

Not as a shipped promise. The supported path is still a structured project
folder, and the scratchpad-to-formalization bridge remains deferred and
exploratory in the public roadmap.

## Do I need to read the code to use DeepLoop?

No. Start with the getting-started and operator guide pages. Read the technical
reference only when you need implementation detail.

## Is DeepLoop already fully automatic for everyone?

No. The repo is now available as a **bounded-support autonomous research
autopilot** on the documented Linux path, but it is still not honest to claim
"fully automatic for everyone." Stronger claims still need broader portability
and fewer temporary product-gap operator boundaries.

## Learn more

- [Glossary](../concepts/glossary.md)
- [Runtime architecture](../concepts/architecture.md)
- [Technical reference](../reference/index.md)
- [Release posture](../release/README.md)
