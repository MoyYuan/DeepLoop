# DeepLoop design notes

This directory contains maintainer-facing implementation and policy notes that
support the main docs site. If you are using DeepLoop rather than extending it,
start with the docs home instead.

## Navigation

- [Docs home](../index.md)
- [Contributor and developer docs](../contributors/index.md)
- [Mission operations](../guide/operator.md)
- [Runtime architecture](../concepts/architecture.md)
- [Technical reference](../reference/index.md)
- [Docs maintenance](../reference/docs-maintenance.md)

## Main design groups

### Mission control and runtime

- [Operating model](operating-model.md)
- [Mission orchestrator](mission-orchestrator.md)
- [State machine](state-machine.md)
- [Role contract](role-contract.md)
- [Stage kernels](stage-kernels.md)
- [Runtime standardization](runtime-standardization.md)
- [Self-healing runtime](self-healing-runtime.md)
- [Recursive agent runtime](recursive-agent-runtime.md)
- [Bounded autoexecutor](bounded-autoexecutor.md)
- [Platform expansion](platform-expansion.md)

### Evidence and evaluation

- [Evaluation plan](evaluation-plan.md)
- [Evidence policy](evidence-policy.md)
- [Experiment ledger](experiment-ledger.md)
- [Statistical rigor](statistical-rigor.md)
- [Confound guard](confound-guard.md)
- [Research sanity gates](research-sanity-gates.md)
- [Mission meta-eval](mission-meta-eval.md)
- [Utility scorer](utility-scorer.md)
- [Memory registry](memory-registry.md)
- [Mission artifact packager](mission-artifact-packager.md)

### Research, release, and change management

- [Self-correction](self-correction.md)
- [Self-correction engine](self-correction-engine.md)
- [Novelty refresh](novelty-refresh.md)
- [Self-optimization](self-optimization.md)
- [Autonomy boundary reduction](autonomy-boundary-reduction.md)
- [Release automation](release-automation.md)
- [Rollout plan](rollout-plan.md)
- [Translation full autonomy](translation-full-autonomy.md)
- [Policy placement](policy-placement.md)

### Supporting concepts

- [Agent spawner](agent-spawner.md)
- [Sandboxed agents](sandboxed-agents.md)
- [Fresh context redteam](fresh-context-redteam.md)
- [Substrate boundary](substrate-boundary.md)
- [Optimization skills](optimization-skills.md)
- [Mission artifact package](mission-artifact-package.md)
