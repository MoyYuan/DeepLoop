# DeepLoop docs

Use these docs to get DeepLoop installed, connect a provider, start a mission
from a project folder, and monitor what happens next. The supported beginner
path today assumes the documented Linux + Python 3.11 environment and the
installed `deeploop` CLI. Deeper runtime and release pages stay
linked below when you need them.

Recent supported-path improvements now surface measurable adaptation outcomes,
narrow deterministic reroute cues, clearer temporary-gap telemetry, and managed
recovery cues directly in the operator flow, so most first runs can stay on the
normal `status` / `inbox` / `resume` loop longer before you need deeper runtime
detail.

## Who should read what

| You are... | Start here | Page type | Why this page |
| --- | --- | --- | --- |
| New to DeepLoop | [Getting started](getting-started.md) | Guide | Shows the shortest supported path from install to a first mission |
| Looking for a public-safe starter project | [Examples](how-to/examples.md) | Guide | Points to the repo-root `examples/` surface and the canonical translation onboarding example |
| Preparing a machine for provider access | [Provider setup](reference/provider-setup.md) | Reference | Covers the machine readiness checks before mission execution |
| Choosing provider/model intent for a mission | [Provider selection](reference/provider-selection.md) | Reference | Covers which provider/model the mission should use and how to keep secrets out of repo config |
| Running or watching a mission | [Mission operations](guide/operator.md) | Guide | Explains the canonical `deeploop` operator commands, operator states, and new recovery/evidence signals in plain language |
| Starting from a plain-folder project | [Plain-folder starter](how-to/plain-folder-starter.md) | Guide | Shows the minimum project shape for the public bootstrap path |
| Trying to understand how DeepLoop works | [Runtime architecture](concepts/architecture.md) | Concept | Summarizes the mission loop and the canonical runtime surfaces |
| Learning the vocabulary | [Glossary](concepts/glossary.md) | Concept | Defines terms like mission, operator state, soft gate, and bounded support |
| Looking for an answer to a common problem | [FAQ](guide/faq.md) | Guide | Gives short answers to the questions people ask most often |
| Need technical depth | [Technical reference](reference/index.md) | Reference | Maps the supported technical contracts, provider references, and advanced runtime surfaces |
| Extending or maintaining DeepLoop | [Contributor and developer docs](contributors/index.md) | Contributor docs | Groups design notes, deep dives, docs maintenance, and contributor-facing guidance into a separate lane |

## One-minute model

1. Start from the canonical public example or your own plain-folder project.
2. Connect a provider DeepLoop can use.
3. Use `deeploop run --project-root <project-folder> --until-complete`
   for the fastest happy path.
4. If you want the explicit operator flow, run `deeploop init`, then
   `deeploop start`.
5. Check `deeploop status` to see the current work, operator state, and any
   surfaced ratchet or temporary-gap cues.
6. Open `deeploop inbox` only when DeepLoop asks for a real decision; use
   `deeploop resume`, `retry`, or `reroute` after you respond.

## If you only read three pages

1. [Getting started](getting-started.md)
2. [Examples](how-to/examples.md)
3. [Mission operations](guide/operator.md)

## More for users and researchers

- [Research and release](research/README.md)
- [Examples](how-to/examples.md)
- [Plain-folder starter](how-to/plain-folder-starter.md)
- [Provider setup](reference/provider-setup.md)
- [Provider selection](reference/provider-selection.md)
- [Technical reference](reference/index.md)

## When you need more context

- [Runtime architecture](concepts/architecture.md)
- [Glossary](concepts/glossary.md)
- [Release posture](release/README.md)
- [Technical reference](reference/index.md)

## Contributing or maintaining

- [Contributor and developer docs](contributors/index.md)
