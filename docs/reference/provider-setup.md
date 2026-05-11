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
| Copilot CLI | documented now | implemented | `copilot` installed, DeepLoop provider launcher available, machine already authenticated |
| OpenAI-compatible API providers | documented now | implemented | API key env var set, endpoint/base URL chosen outside repo, auth handled outside repo, prompt/result control-plane adapter available |
| Anthropic API providers | documented now | deferred | API key env var set, endpoint choice handled outside repo, auth handled outside repo |
| local-transformers | documented now | implemented | `torch` + `transformers` import cleanly and model weights are reachable |
| vllm | documented now | implemented | `torch` + `vllm` import cleanly and the machine exposes a suitable accelerator/runtime |

The Anthropic row is still first-class in this setup contract even though its
runtime adapter remains deferred. OpenAI-compatible setup now has a public
control-plane prompt/result adapter; the later mission selection contract is
documented separately.

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

## Family requirements

### Copilot CLI

- required tools:
  - `copilot`
  - `python`
- expected env vars/auth prerequisites:
  - no DeepLoop secret is stored in repo config
  - machine must already have a valid Copilot CLI authentication state
  - `GITHUB_TOKEN` may be present in the operator environment if the local
    Copilot installation expects it, but it is optional in repo config
- readiness expectations:
  - `copilot --help` exits cleanly
  - `python scripts/runtime/invoke_provider_prompt.py --help` exits cleanly
  - the machine is already signed in for Copilot CLI use

This family is wired into the current runtime through
`src/deeploop/runtime/provider_launcher.py`,
`src/deeploop/runtime/copilot_adapter.py`, and
`scripts/runtime/invoke_provider_prompt.py`.

The current Gate 2 coding-agent release-proof lane pins this family to the
`gpt-5-mini` alias through
`configs/runtime/gate-2-runtime-lanes.yaml` and
`configs/runtime/provider-selection-registry.yaml`. That lane still keeps
manual machine authentication explicit: repo automation can validate the CLI and
launcher surface, but release proof must record that Copilot CLI auth was
already valid on the machine.

#### Custom script data routing

> **Warning**: Never pass mission state, ledger contents, or other large
> payloads as inline strings to a provider CLI flag (e.g.
> `copilot -p "$STATE_TEXT"`). Once mission files grow beyond a few kilobytes
> the OS rejects the call with `[Errno 7] Argument list too long`.

Custom scripts that bridge DeepLoop state to a provider **must** use one of
these safe patterns instead:

1. **`deeploop analyze` (recommended)** – the built-in command that builds
   and routes the analysis prompt from the mission state file without ever
   expanding it into a shell argument:

   ```bash
   deeploop analyze --mission-state path/to/mission_state.json
   ```

   Pass `--prompt-file` to supply a fully custom prompt file, or `--task` to
   override only the analysis task description.

2. **`invoke_provider_prompt.py --prompt-file`** – write the prompt to a
   file first, then pass the file path:

   ```bash
   python scripts/runtime/invoke_provider_prompt.py \
       --prompt-file /tmp/my_prompt.md \
       --result-json-path /tmp/result.json
   ```

3. **stdin piping** – pipe the prompt into a provider tool that reads from
   stdin rather than a positional string argument.

DeepLoop's own orchestrator always writes prompts to files and passes them by
path. Custom scripts must follow the same rule.

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

DeepLoop now ships a public control-plane prompt/result adapter for this family.
It reads prompt files, calls an OpenAI-compatible `/v1/chat/completions`
endpoint, and materializes structured result JSON for prompt/result flows such
as `deeploop analyze`. Tool-using recursive-agent execution still remains on the
Copilot CLI path. Setup is documented here; mission/runtime provider selection
is documented separately.

#### Documented local deployment profile: `local-qwen3_6-27b-openai`

The current Gate 2 local OpenAI-compatible lane is a **deployment profile inside
this family**, not a new provider family:

- target model identifier: `Qwen/Qwen3.6-27B`
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
    `Qwen/Qwen3.6-27B` remain host-specific and must be validated on the machine
  - if the server depends on gated or private weights, provision access outside
    the repo before startup
- fallback / downgrade guidance:
  - lower context, max output, or request concurrency first while staying on the
    same OpenAI-compatible lane
  - if the dense 27B profile is not stable on the host, record an explicit
    downgrade to `qwen3_5-mid-fp16` or `single-gpu-8b-9b-fp16` from
    `configs/execution-profiles/inference-families.yaml`

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
