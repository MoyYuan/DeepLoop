# Autonomy governance

This page is the canonical public-facing inventory of **which DeepLoop stops are
permanent operator-only boundaries** and which ones are still **temporary gaps**
the product should reduce over time.

## Why this page exists

DeepLoop should not hide operator involvement behind vague language like
"sometimes a human may need to help." The runtime already emits a concrete
operator-request taxonomy:

- `hard-gate`
- `authority-boundary`
- `operator-review`
- `unrecoverable-failure`

This page maps those runtime classes to honest public claims.

The runtime summary and operator monitor now also surface autonomy-gap telemetry
so these classes stay visible in mission artifacts instead of living only in
documentation.

## The current classification

| Runtime class | What it means | Honest classification | Expected direction |
| --- | --- | --- | --- |
| `hard-gate` | A configured hard-gate risk class was crossed | **Permanent safety / authority / governance boundary** | Remains operator-only unless policy itself changes |
| `authority-boundary` | A selected action explicitly requires approval | **Permanent authority / governance boundary** | Remains operator-only |
| `operator-review` | DeepLoop needs a human decision after a blocked bounded path | **Temporary DeepLoop product gap** or **temporary substrate gap** | Should shrink when safe automation is added |
| `unrecoverable-failure` | Bounded recovery exhausted and DeepLoop stopped honestly | **Temporary DeepLoop product gap** or **temporary substrate gap** | Should shrink when root causes are fixed |

## Permanent operator-only boundaries

These are not bugs to paper over. They are the places where DeepLoop should
stop and ask for human review.

### 1. Hard-gate risk classes

The current hard-gate policy covers:

- `system-global-safety`
- `sandbox-boundary`
- `secrets-provenance-licensing`
- `external-release`
- `unsandboxed-escalation`

When one of these is crossed, the mission should stop and escalate instead of
pretending that bounded autonomy still applies.

### 2. Explicit authority boundaries

The current outer-loop action taxonomy keeps `external-publish` as an
approval-required action. This means public publication, announcement, or any
equivalent external release step is a **permanent operator-owned authority
decision**, not an automation gap.

### 3. Release approval requirements

Mission completion does **not** equal public release approval. Release review
still requires:

- `provenance-review`
- `licensing-review`
- `release-operator`

Those approvals stay explicit even when the mission runtime itself completed
autonomously.

## Temporary gap classes

These are the places where DeepLoop should improve over time, but should stay
honest until that improvement is real.

### Temporary DeepLoop product gap

Use this label when the blocker is inside DeepLoop's own runtime or bounded
executor surface, for example:

- executor mismatch that should be reducible through better routing
- bounded queue / recovery behavior that still stops too early
- packaging, monitoring, or orchestration failures
- runtime-owned missing evidence generation that DeepLoop should learn to do
  safely

Recent example: plain-folder missions used to finish late phases textually
without real executor-backed evidence. That was a **temporary DeepLoop product
gap**, and Track 2 reduced it by moving execution, critique, and replication
onto real executors.

### Temporary substrate gap

Use this label when the blocker comes from a substrate-specific contract,
missing asset, or scientific surface that DeepLoop cannot safely infer away,
for example:

- missing or invalid substrate facts / assets
- incompatible substrate-local assumptions
- scientific constraints that require new substrate-side clarification

DeepLoop should surface these clearly, not misclassify them as permanent
safety/governance boundaries.

## Soft gates are not the same as operator requests

DeepLoop also tracks soft-gate risk classes:

- `scientific-validity`
- `budget-overrun`
- `executor-mismatch`
- `quality-shortfall`

These are the **autopilot-owned temporary gap class**. The default expectation
is:

1. try bounded recovery
2. prefer `retry`, `reroute`, or `downscope`
3. keep the operator inbox closed while recovery is still honest and bounded

An operator request should open only when:

- a hard gate is crossed
- explicit approval is required
- a blocked bounded path now needs human review
- bounded recovery is exhausted

## Supported public claim today

The honest public claim is still:

- DeepLoop is a **local-first autonomous research autopilot**
- DeepLoop has real multi-substrate plain-folder proof and real evidence-bearing
  late-phase execution
- DeepLoop still keeps operator-only boundaries for safety, authority,
  provenance, licensing, and external release

It is **not** yet honest to claim "fully automatic for everyone."

## Non-goals for autonomy messaging

- do not describe a temporary product gap as a permanent safety boundary
- do not describe a permanent release approval requirement as a bug
- do not weaken package or release policy just to make promotion look easier
- do not hide substrate-specific blockers inside generic "operator judgment"
  wording

## Public trust posture

DeepLoop should be trusted only within the documented contract:

- mutable runtime state belongs in DeepLoop-owned workspace roots
- hard-gate classes remain operator-only
- external publication remains operator-approved
- provenance and licensing review remain explicit
- stronger public claims require stronger proof, not just better wording

## Source contracts

The machine-readable inventory for this page lives in:

- `configs/autonomy/operator-boundaries.yaml`
- `configs/autonomy/gates.yaml`
- `configs/autonomy/mission-outer-loop.yaml`
- `configs/runtime/release-candidate-policy.yaml`
- `configs/autonomy/evidence-policy.yaml`
