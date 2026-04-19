# DeepLoop role contract

DeepLoop should separate responsibilities so autonomous research does not blur
planning, execution, critique, and reporting into one opaque agent step.

## Core roles

- **planner**: maintains mission scope and loop progress
- **literature-scout**: maintains prior-art and benchmark context
- **experiment-designer**: turns questions into manifests and ablations
- **inference-optimizer**: resolves inference profiles and fallback ladders
- **training-optimizer**: resolves training presets and capacity tradeoffs
- **execution-operator**: runs jobs and registers artifacts
- **critic-verifier**: audits evidence quality and confounds
- **report-synthesizer**: packages validated findings into paper-grade outputs

## Required handoffs

- planner -> experiment-designer: mission brief and current loop state
- literature-scout -> experiment-designer: prior-art memo and benchmark notes
- experiment-designer -> optimizer/operator: run manifest draft
- execution-operator -> critic-verifier: completed manifest plus logs and metrics
- critic-verifier -> report-synthesizer: evidence-state recommendation

## Why this matters

- it reduces silent assumption drift
- it makes failures easier to localize
- it turns DeepLoop into a measurable research system instead of a black box
