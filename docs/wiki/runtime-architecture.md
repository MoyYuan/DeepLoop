# Runtime architecture deep dive

The canonical overview page is [Runtime architecture](../concepts/architecture.md).
Use this page when you want the debugging-oriented map from concepts to source files.

## Main runtime surfaces

- [Mission orchestrator](../design/mission-orchestrator.md)
- [Mission state machine](../design/state-machine.md)
- [Stage kernels](../design/stage-kernels.md)
- [Runtime standardization](../design/runtime-standardization.md)
- [Self-healing runtime](../design/self-healing-runtime.md)
- [Recursive agent runtime](../design/recursive-agent-runtime.md)
- [Platform expansion](../design/platform-expansion.md)
- [Research sanity gates](../design/research-sanity-gates.md)
- [Experiment ledger](../design/experiment-ledger.md)
- [Mission artifact packager](../design/mission-artifact-packager.md)

## Contract boundary

DeepLoop keeps project-specific details outside the core runtime by reading
machine-readable contracts from the substrate repo: project metadata,
runtime-provider entrypoints, evaluation contracts, and mission-specific queue
or stage configs.

That split is what keeps DeepLoop generic while still letting each substrate
declare its own execution details. The same boundary now includes
`platform_expansion` records under each mission so scheduler, indexed-memory,
packaging, and release review reuse the same durable handoff paths.

## What to inspect when debugging

| Area | File |
| --- | --- |
| Executor selection | `src/deeploop/mission/mission_decision_engine.py` |
| Bootstrap and follow-up staging | `src/deeploop/mission/mission_runtime.py` |
| Multi-mission scheduling | `src/deeploop/mission/mission_scheduler.py` |
| Mission memory and experiment ledger sync | `src/deeploop/mission/mission_memory.py` |
| Platform handoff materialization and sync | `src/deeploop/platform/contracts.py` |
| Provider discovery and path resolution | `src/deeploop/project_contract.py` |
| Research preflight gating | `src/deeploop/research/sanity_gates.py` |
| Stage execution behavior | `src/deeploop/runtime/stage_kernels.py` |
