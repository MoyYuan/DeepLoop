# Provider selection

This page is the canonical public contract for **mission/runtime provider
selection**.

It defines how DeepLoop declares **which provider family, backend, and model a
mission is configured to use** after machine-level setup is already satisfied.

The matching machine-readable source of truth is
`configs/runtime/provider-selection-registry.yaml`.

## Scope boundary

This contract covers:

- provider family choice for a mission, loop, role, or phase
- backend selection and concrete model alias/identifier selection
- allowed fallback ladders and operator override points
- where the effective resolved selection should be recorded in runtime artifacts

This contract does **not** cover:

- machine-level provider availability, auth, or tooling setup
- checked-in secrets, credential values, or endpoint secrets

Machine-level provider setup stays in [Provider setup](provider-setup.md).
Selection builds on setup, but it does not redefine setup.

## First-class provider families

DeepLoop's initial public provider-selection contract treats these families as
the first-class mission/runtime selection set:

| Provider family | Typical selection use | Current public selection status | Notes |
| --- | --- | --- | --- |
| Copilot CLI | control-plane / recursive-agent loops | implemented | current recursive-agent example uses the provider launcher with the Copilot CLI adapter; optional explicit model selection is allowed |
| OpenAI-compatible API providers | API-backed control-plane prompt/result flows | implemented | provider launcher can route structured prompt/result control-plane tasks through an OpenAI-compatible `/v1/chat/completions` endpoint |
| Anthropic API providers | API-backed mission/runtime selection | contract reserved | selection surface is defined now; public request adapter remains deferred |
| local-transformers | local execution / replication | implemented | explicit local model choice plus backend-policy-controlled fallback |
| vllm | local execution / replication | implemented | explicit `vllm` selection remains mission-driven, not automatic |

## Canonical sources of truth

- human-readable selection contract: `docs/reference/provider-selection.md`
- machine-readable registry: `configs/runtime/provider-selection-registry.yaml`
- companion machine-setup contract: `docs/reference/provider-setup.md`
- companion machine-setup registry: `configs/runtime/provider-setup-registry.yaml`
- Gate 2 runtime-lane registry: `configs/runtime/gate-2-runtime-lanes.yaml`
- local backend defaults and ladder input: `configs/runtime/backend-policy.yaml`
- recursive-loop policy surface: `configs/runtime/recursive-agent-runtime.yaml`
- recursive-loop example with selection block:
  `configs/runtime/recursive-agent-runtime-provider.example.yaml`
- role/env map: `configs/sandbox/agent-launch-policy.yaml`
- manifest recording surface: `configs/manifests/run-manifest-template.json`

## Resolution model

The canonical precedence order is:

1. operator or launcher override supplied at mission start
2. mission `runtime.provider_selection`
3. loop config `provider_selection`
4. phase override inside the selected profile
5. role override inside the selected profile
6. repo default profile from `provider-selection-registry.yaml`

The resolution axes are intentionally explicit:

- mission
- loop
- phase
- role
- run manifest recording

## Selection profiles

The machine-readable registry defines these public profiles:

### `control-plane-copilot-cli`

- provider family: `copilot-cli`
- backend: `copilot-cli`
- intended roles: planning/control-plane roles plus recursive-agent loops
- model selection: optional explicit `model.alias` or `model.identifier`
- default behavior: use the operator-local Copilot default unless a mission or
  loop explicitly pins a model
- fallback posture: no cross-provider fallback by default

### `gate2-coding-agent-copilot-gpt5-mini`

- provider family: `copilot-cli`
- backend: `copilot-cli`
- intended role/loop: coding-agent validation through the recursive-agent path
- model selection: explicit `model.alias: gpt-5-mini`
- fallback posture: no model or cross-provider fallback; the Gate 2 lane is
  pinned on purpose
- notes:
  - this is the current approved Gate 2 coding-agent runtime lane
  - machine auth stays in [Provider setup](provider-setup.md); this profile only
    pins the runtime selection
  - release proof for this lane must record durable mission/runtime artifacts
    with the resolved provider family, backend, and model alias

### `local-transformers-execution`

- provider family: `local-transformers`
- backend: `local-transformers`
- intended role/phase: `execution-operator` during `execution` / `replication`
- model selection: explicit local model path or identifier required
- fallback posture: may use the backend ladder described by
  `configs/runtime/backend-policy.yaml`

### `vllm-execution`

- provider family: `vllm`
- backend: `vllm`
- intended role/phase: `execution-operator` during `execution` / `replication`
- model selection: explicit `vllm`-compatible model identifier required
- fallback posture: may use the backend ladder described by
  `configs/runtime/backend-policy.yaml`

### `openai-compatible-api-control-plane`

- provider family: `openai-compatible-api`
- backend: `openai-compatible-api`
- status: implemented for control-plane prompt/result flows
- model selection: explicit model identifier and any non-secret endpoint alias
  must come from mission/operator config
- notes:
  - the current public adapter covers structured prompt/result flows such as
    `deeploop analyze`
  - tool-using recursive-agent execution still remains on `copilot-cli`
  - local versus commercial deployment remains a profile choice inside this
    family, not a new first-class provider family

### `gate2-local-qwen3_6-27b-openai`

- provider family: `openai-compatible-api`
- backend: `openai-compatible-api`
- intended surface: Gate 2 prompt/result control-plane proof on a host-local
  OpenAI-compatible endpoint
- deployment profile: `local-qwen3_6-27b-openai`
- host execution profile: `qwen3_6-27b-openai-local`
- model selection: pin `model.identifier: Qwen/Qwen3.6-27B` and
  `model.endpoint_alias: local-qwen-openai`
- fallback posture: stay on the OpenAI-compatible family; downgrade only through
  an explicit local model ladder and record the downgrade
- notes:
  - this is the current approved Gate 2 local Qwen lane
  - treat local serving as a deployment profile inside the OpenAI-compatible
    family, not as a new public provider family
  - DeepLoop does not start the host-local server, provision auth, or turn this
    prompt/result lane into the Copilot-style coding-agent path

### `anthropic-api-control-plane`

- provider family: `anthropic-api`
- backend: `anthropic-api`
- status: selection contract reserved; runtime adapter still deferred
- model selection: explicit model identifier and any non-secret endpoint alias
  must come from mission/operator config

## Fallbacks and override points

The registry exposes three public fallback postures:

- `no-cross-provider-fallback` — stay on the selected provider family and allow
  only provider-native or operator-local model fallback
- `local-inference-backend-ladder` — use the explicit mission choice together
  with the local backend ladder from `backend-policy.yaml`
- `explicit-provider-ladder` — only switch provider families when the mission or
  operator provides an ordered fallback list

Public override points are:

- repo default profile in `provider-selection-registry.yaml`
- mission `runtime.provider_selection`
- loop `provider_selection`
- operator/launcher start-time override
- manifest recording under `runtime.provider_selection`

Keep secrets out of repo config. Only non-secret provider identifiers, backend
choices, model aliases/IDs, and fallback policy belong here.

If you want to validate the machine-level setup behind a selection profile
without collapsing this boundary, run:

```text
deeploop provider-ready --selection-profile <profile>
```

That command resolves the provider family from this registry, but it still
checks only the setup contract from [Provider setup](provider-setup.md).

## Relationship to existing runtime surfaces

### `configs/runtime/backend-policy.yaml`

`backend-policy.yaml` remains the source for local inference backend defaults and
the local fallback ladder between `local-transformers` and `vllm`. It does not
by itself choose which provider a mission should use.

### `configs/runtime/recursive-agent-runtime.yaml`
### `configs/runtime/recursive-agent-runtime-provider.example.yaml`

Recursive-agent loop configs may now carry a `provider_selection` block to
express mission/runtime intent separately from machine setup.

The current public runtime can route through
`scripts/runtime/invoke_provider_prompt.py`, and that provider-neutral entrypoint
currently delegates `copilot-cli` requests to the Copilot adapter and
`openai-compatible-api` requests to the OpenAI-compatible control-plane adapter.
The `provider_selection` block remains the canonical selection contract for that
loop.

The shipped example at
`configs/runtime/recursive-agent-runtime-provider.example.yaml` now pins the
`gate2-coding-agent-copilot-gpt5-mini` profile so the concrete Gate 2
coding-agent lane is explicit on this runtime surface.

### `configs/sandbox/agent-launch-policy.yaml`

`role_env_map` chooses the Conda/runtime environment for each role. It is not a
provider selector. A role can stay mapped to `deeploop` or `llm` while provider
selection independently chooses Copilot CLI, an API family, `local-transformers`,
or `vllm`.

### `configs/manifests/run-manifest-template.json`

Run manifests keep the resolved run model in the top-level `model` block. The
selection contract adds `runtime.provider_selection` as the place to record the
effective mission/runtime selection context that produced that run.

## Setup vs. selection

Provider setup answers:

- can this machine authenticate to or run a provider family at all?
- are the required tools/modules/env vars present?
- is the machine ready for a later mission to select from that family?

Provider selection answers:

- which provider family should this mission/loop/phase/role use?
- which backend and concrete model alias/identifier should it target?
- what fallback posture is allowed if the preferred selection cannot run?
- where should the resolved choice be recorded for manifests and runtime audit?
