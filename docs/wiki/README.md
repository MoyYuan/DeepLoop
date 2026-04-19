# DeepLoop companion deep dives

This section holds companion pages for readers who already know the basics and
want extra context. These pages should support the main docs path, not replace
it. If you are new, start at [the docs home](../index.md).

## Pages

| Page | Use it for | Canonical page |
| --- | --- | --- |
| [Mission operator deep dive](mission-ops.md) | Adjacent files, runtime surfaces, and recovery context | [Mission operations](../guide/operator.md) |
| [Runtime architecture deep dive](runtime-architecture.md) | Debugging-oriented runtime map, including scheduler and platform handoffs | [Runtime architecture](../concepts/architecture.md) |
| [Research and release deep dive](research-and-release.md) | Durable research artifacts, experiment ledger, and release promotion context | [Research notes](../research/README.md) / [Release posture](../release/README.md) |

## Where to read next

- If you are launching or watching a run, go to [Mission operations](../guide/operator.md).
- If you are changing runtime behavior or tracing platform handoffs, go to [Runtime architecture](../concepts/architecture.md).
- If you are turning work into a shareable result, go to [Technical reference](../reference/index.md).

## Canonical runtime surfaces

- `scripts/mission/manage_mission.py`
- `scripts/mission/run_mission.py`
- `scripts/mission/monitor_mission.py`
- `src/deeploop/mission/mission_runtime.py`
- `src/deeploop/mission/mission_decision_engine.py`
- `src/deeploop/mission/mission_scheduler.py`
- `src/deeploop/platform/contracts.py`
- `src/deeploop/research/sanity_gates.py`
