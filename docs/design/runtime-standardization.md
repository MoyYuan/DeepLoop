# Runtime standardization

DeepLoop now standardizes local execution through
`configs/runtime/backend-policy.yaml`, `environment.yml`, and
`environment.llm.yml` instead of letting each project guess its own runtime
stack.

## Current baseline

- use the `deeploop` env for planning and control-plane work
- use `llm` env for real local inference
- prefer `local-transformers` as the first stable backend
- keep `vllm` as an explicit secondary backend rather than an implicit default

## Why this is the current default

- `environment.yml` and `environment.llm.yml` already encode the two-env split
- `configs/runtime/backend-policy.yaml` publishes the same planning and
  inference recommendation to the runtime
- the split minimizes runtime ambiguity while keeping backend choice explicit in
  manifests and findings

## Real roadmap limits

- `vllm` is still an optimization path, not the primary standardized backend
- distributed and multi-node inference remain deferred work
