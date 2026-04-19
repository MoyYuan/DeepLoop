# Bounded autoexecutor

The bounded autoexecutor is a secondary DeepLoop runtime surface for
deterministic queue proofs, recovery drills, and integration workloads.
DeepLoop's canonical mission path is `mission_runtime.py` /
`scripts/mission/run_mission.py`.

## Role in architecture

- run explicit queue configs through `scripts/runtime/run_queue.py`
- serve as a bounded executor that higher-level mission actions can call
- validate recovery behavior in isolation
- avoid pretending to be the primary mission controller

## Design constraints

- explicit queue config
- mission-linked ledger updates
- bounded job count
- explicit env and repo root per job
- explicit expected manifest path per job

## First implementation

The first implementation is intentionally conservative:

- sequential execution only
- no hidden scheduler or daemon
- skip existing outputs unless rerun is explicitly requested
- block queued jobs whose proposal configs fail the research sanity gate
- write logs and status updates back into the mission ledger
