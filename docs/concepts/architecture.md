# Runtime architecture

This page explains the DeepLoop runtime at a high level.

## The mental model

DeepLoop is a mission loop:

1. build the mission state and contract
2. inspect evidence and progress
3. choose the next action
4. dispatch that action through a registered executor
5. save the results durably
6. surface operator-facing state through `deeploop status` and
   `deeploop inbox`

## The main parts

| Part | What it does |
| --- | --- |
| Mission state | Stores the durable record of what the mission knows and what it plans next |
| Decision engine | Chooses the next action or phase transition |
| Executors | Run stage kernels, queues, recursive agents, and other bounded work |
| Operator management surface | `deeploop` CLI owns the canonical `start` / `status` / `inbox` / `resume` loop, plus logs, decisions, watch, triage, and stop |
| Ledgers | Keep durable evidence of decisions, branches, and findings |

## Canonical runtime surfaces

- `deeploop` CLI is the operator-facing entry point (`start`, `status`, `inbox`, `resume`, and more)
- `scripts/mission/manage_mission.py` remains available as a fallback surface for debugging and automation
- `scripts/mission/run_mission.py` is the detached mission runtime it launches
- `scripts/mission/monitor_mission.py` and `mission_monitor.py` build the
  snapshots behind `status`
- `_operator_surface.py` turns runtime state into the operator vocabulary:
  lifecycle state, operator state, attention level, next-step owner, and resume
  policy

## Why the split matters

DeepLoop owns the runtime behavior and the build/execution surfaces. The
substrate repo should stay as a minimal fact/contract surface.

That split lets DeepLoop stay generic while still working on a concrete project
like translation pilot.

That also means:

- the substrate repo can start with a brief, benchmark/test data, baseline
  metrics, slice definitions, and scientific/safety rules
- DeepLoop may still decide it needs additional trusted datasets, better
  metrics, new evaluation slices, or new training plans
- those expansions should be DeepLoop-owned design/runtime decisions, not a
  reason to push more DeepLoop code into the project repo

The same rule applies to new lessons:

- DeepLoop owns universal runtime and operator-surface behavior
- general skills own reusable methods
- substrate repos own scientific and domain-specific contracts
- machine instructions own cross-repo safety and hygiene defaults

## Where to go next

- [Glossary](glossary.md)
- [Technical reference](../reference/index.md)
- [Mission operations](../guide/operator.md)
