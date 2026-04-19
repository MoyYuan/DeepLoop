# DeepLoop docs

DeepLoop is a **bounded-support autonomous research autopilot** with an
operator management layer. The current newcomer/operator path assumes the
documented Linux + Python 3.11 environment and the canonical
`scripts/mission/manage_mission.py` runtime surface.

## Who should read what

| You are... | Start here | Page type | Why this page |
| --- | --- | --- | --- |
| New to DeepLoop | [Getting started](getting-started.md) | Guide | Shows the shortest supported setup and first mission loop |
| Looking for a public-safe starter project | [Examples](how-to/examples.md) | Guide | Points to the repo-root `examples/` surface and the canonical translation onboarding example |
| Preparing a machine for provider access | [Provider setup](reference/provider-setup.md) | Reference | Defines the canonical machine-level provider setup contract and its boundary from mission-time selection |
| Choosing provider/model intent for a mission | [Provider selection](reference/provider-selection.md) | Reference | Defines the canonical mission/runtime provider, backend, model, fallback, and override contract |
| Running or watching a mission | [Mission operations](guide/operator.md) | Guide | Explains the canonical `manage_mission.py` commands and operator states in plain language |
| Starting from a plain researcher folder | [Plain-folder starter](how-to/plain-folder-starter.md) | Guide | Shows the minimum project shape for the public bootstrap path |
| Trying to understand how DeepLoop works | [Runtime architecture](concepts/architecture.md) | Concept | Summarizes the mission loop and the canonical runtime surfaces |
| Learning the vocabulary | [Glossary](concepts/glossary.md) | Concept | Defines terms like mission, operator state, soft gate, and bounded support |
| Looking for an answer to a common problem | [FAQ](guide/faq.md) | Guide | Gives short answers to the questions people ask most often |
| Need technical depth | [Technical reference](reference/index.md) | Reference | Maps the operator CLI, runtime modules, and design docs |

## One-minute model

1. A **mission** is the long-running research loop.
2. `scripts/mission/manage_mission.py` is the canonical operator CLI.
3. DeepLoop picks the next step from durable mission state and evidence.
4. It dispatches that step through a registered **executor**.
5. The normal operator loop is `start` -> `status` -> `inbox` only when asked -> `resume`.
6. `logs`, `decisions`, and `watch` add monitoring detail, and managed mode can surface `triage` before `retry`/`reroute` + `resume`.

## If you only read three pages

1. [Getting started](getting-started.md)
2. [Mission operations](guide/operator.md)
3. [Runtime architecture](concepts/architecture.md)

## Deep dives

- [Research and release](research/README.md)
- [Examples](how-to/examples.md)
- [Plain-folder starter](how-to/plain-folder-starter.md)
- [Provider setup](reference/provider-setup.md)
- [Provider selection](reference/provider-selection.md)
- [Technical reference](reference/index.md)
- [Design index](design/README.md)
