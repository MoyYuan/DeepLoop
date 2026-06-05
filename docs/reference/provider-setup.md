# Provider setup

This page is the canonical public contract for **machine-level provider setup**.
It defines what must be true on a machine before DeepLoop can rely on a provider
family at all.

The matching machine-readable source of truth is
`configs/runtime/provider-setup-registry.yaml`.

## Scope boundary

This contract covers:

- required tools or Python modules on the machine
- expected env var names and auth prerequisites
- readiness checks to run before mission execution

This contract does **not** cover:

- mission/runtime provider-model selection
- per-mission model IDs, routing, or fallback policy
- secret values or checked-in credentials

Keep secrets out of repo config. Only declare names, prerequisites, and
readiness expectations here.

Mission/runtime provider selection now lives separately in
[Provider selection](provider-selection.md) and
`configs/runtime/provider-selection-registry.yaml`.

## First-class provider families

DeepLoop's initial public provider contract treats these families as the
first-class machine-level setup set:

| Provider family | Machine setup contract | Current runtime integration | Canonical readiness summary |
| --- | --- | --- | --- |
| OpenAI-compatible API providers | documented now | implemented | API key env var set, endpoint/base URL chosen outside repo, auth handled outside repo, prompt/result control-plane adapter available, DeepSeek Chat default control-plane profile |
| Anthropic API providers | documented now | deferred | API key env var set, endpoint choice handled outside repo, auth handled outside repo |
| local-transformers | documented now | implemented | `torch` + `transformers` import cleanly and model weights are reachable |
| vllm | documented now | implemented | `torch` + `vllm` import cleanly and the machine exposes a suitable accelerator/runtime |

Anthropic remains a first-class family in this setup contract even though its
runtime adapter remains deferred. OpenAI-compatible setup now has a public
control-plane prompt/result adapter and is the default provider path for
DeepLoop v0.2.0+.

## Canonical sources of truth

- human-readable setup contract: `docs/reference/provider-setup.md`
- machine-readable registry: `configs/runtime/provider-setup-registry.yaml`
- human-readable selection contract: `docs/reference/provider-selection.md`
- machine-readable selection registry: `configs/runtime/provider-selection-registry.yaml`
- Gate 2 runtime-lane registry: `configs/runtime/gate-2-runtime-lanes.yaml`
- related local-backend defaults: `configs/runtime/backend-policy.yaml`
- related recursive-agent example: `configs/runtime/recursive-agent-runtime-provider.example.yaml`

`backend-policy.yaml` remains useful for local inference defaults, but it is not
the canonical source for the full machine-level provider setup contract.

## Guided readiness check

Use DeepLoop's provider-readiness surface when you want the machine-level setup
answer directly:

```text
deeploop provider-ready
```

This validates that the required environment variables (`OPENAI_API_KEY`,
`OPENAI_BASE_URL`) are set and the endpoint is reachable. It checks **setup
only** — it does not choose a model, mutate mission config, or replace the
separate provider-selection contract.

## Family requirements

### OpenAI-compatible API providers

- required tools:
  - `python`
  - optionally `curl` for manual endpoint checks
- expected env vars/auth prerequisites:
  - required: `OPENAI_API_KEY`
  - optional: `OPENAI_BASE_URL`, `OPENAI_ORG_ID`
  - credentials are provisioned outside the repo
- readiness expectations:
  - required env vars are set in the operator shell, runner, or deployment
    environment
  - if `OPENAI_BASE_URL` is overridden, the chosen HTTPS endpoint is reachable

DeepLoop ships a public control-plane prompt/result adapter for this family.
It reads prompt files, calls an OpenAI-compatible `/v1/chat/completions`
endpoint, and materializes structured result JSON for prompt/result flows such
as `deeploop analyze`. Setup is documented here; mission/runtime provider
selection is documented separately.

#### Documented local deployment profile: `local-qwen3_5-9b-openai`

The current Gate 2 local OpenAI-compatible lane is a **deployment profile inside
this family**, not a new provider family:

- target model identifier: `Qwen/Qwen3.5-9B`
- endpoint contract:
  - `OPENAI_BASE_URL` points at a host-local OpenAI-compatible server exposing
    `/v1/chat/completions`
  - `OPENAI_API_KEY` stays external/manual even for local serving; if the server
    accepts a placeholder token, keep that placeholder outside repo config too
  - `OPENAI_ORG_ID` remains optional and only matters if the chosen server honors
    it
- environment expectations:
  - DeepLoop's control-plane commands can stay on the normal `deeploop` env
  - the local serving stack commonly lives in `environment.llm.yml` or an
    equivalent host-managed env
- manual / host-specific boundary:
  - DeepLoop does not launch, supervise, or tune the host-local server
  - GPU sizing, precision/quantization choice, and server flags for
    `Qwen/Qwen3.5-9B` remain host-specific and must be validated on the machine
  - if the server depends on gated or private weights, provision access outside
    the repo before startup
- fallback / downgrade guidance:
  - lower context, max output, or request concurrency first while staying on the
    same OpenAI-compatible lane
  - if the dedicated 9B Gate 2 profile is not stable on the host, record an explicit
    downgrade to `qwen3_5-mid-fp16` or `single-gpu-8b-9b-fp16` from
    `configs/execution-profiles/inference-families.yaml`

#### Default control-plane deployment profile: `deepseek-chat`

DeepLoop v0.2.0+ ships with `deepseek-chat` as the default control-plane
provider. This is a **deployment profile inside the OpenAI-compatible family**,
not a new provider family:

- target model: `deepseek-chat` (DeepSeek's latest chat model via API)
- endpoint contract:
  - `OPENAI_BASE_URL=https://api.deepseek.com` (default)
  - `OPENAI_API_KEY` must be set to a valid DeepSeek API key
  - standard OpenAI-compatible `/v1/chat/completions` endpoint
- environment expectations:
  - all control-plane commands run in the normal `deeploop` environment
  - no additional runtime env required
- fallback / downgrade guidance:
  - if `deepseek-chat` is not available, configure an alternative
    OpenAI-compatible endpoint via `OPENAI_BASE_URL`
  - fallback model selection is handled by the provider selection contract,
    not by machine setup

### Anthropic API providers

- required tools:
  - `python`
  - optionally `curl` for manual endpoint checks
- expected env vars/auth prerequisites:
  - required: `ANTHROPIC_API_KEY`
  - optional: `ANTHROPIC_BASE_URL`
  - credentials are provisioned outside the repo
- readiness expectations:
  - required env vars are set in the operator shell, runner, or deployment
    environment
  - if `ANTHROPIC_BASE_URL` is overridden, the chosen HTTPS endpoint is
    reachable

DeepLoop does not yet ship a public request adapter. Setup is documented here;
mission/runtime provider selection is documented separately.

### local-transformers

- required tools/modules:
  - `python`
  - `torch`
  - `transformers`
- expected env vars/auth prerequisites:
  - no required env vars
  - optional: `HF_HOME`, `TRANSFORMERS_CACHE`, `HUGGING_FACE_HUB_TOKEN`
  - if model weights are gated/private, access must be provisioned outside the
    repo
- readiness expectations:
  - `python -c "import torch, transformers"` exits cleanly
  - the target model weights are reachable through a local path or the machine's
    configured model cache/access path

The documented optional runtime env for this family is `environment.llm.yml`.
Runtime backend detection already checks for `torch` + `transformers`.

### vllm

- required tools/modules:
  - `python`
  - `torch`
  - `vllm`
- expected env vars/auth prerequisites:
  - no required env vars
  - optional: `CUDA_VISIBLE_DEVICES`, `HF_HOME`, `HUGGING_FACE_HUB_TOKEN`
  - if model weights are gated/private, access must be provisioned outside the
    repo
- readiness expectations:
  - `python -c "import torch, vllm"` exits cleanly
  - the machine exposes a suitable accelerator/runtime for the intended `vllm`
    workload

`configs/runtime/backend-policy.yaml` keeps `vllm` as an explicit secondary
local backend rather than the default.

## Boundary to the selection contract

Machine-level provider setup answers:

- can this machine authenticate to or run a provider family at all?
- are the required tools/modules/env vars present?
- is the machine ready for a later mission to select from that family?

Mission/runtime provider-model selection answers different questions:

- which provider family should a specific mission use?
- which concrete model ID should that mission use?
- when should DeepLoop switch, retry, or fall back between providers?

That later surface now lives in `docs/reference/provider-selection.md` and
`configs/runtime/provider-selection-registry.yaml` so setup does not need to be
redefined from scratch.
