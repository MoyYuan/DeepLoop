# DeepLoop

> Structured research missions from a local project folder — with visible autonomy boundaries, durable mission state, and an explicit operator inbox.

DeepLoop helps researchers and operators run structured work from the artifacts already on disk instead of rebuilding everything around one long chat. It keeps the loop moving, pauses only at real safety, authority, or support boundaries, and makes the path legible when you need to inspect or redirect it.

DeepLoop **owns behavior** and orchestration; substrate repos own reusable domain or science rules.

## Why it matters

- **Start from real project artifacts:** bootstrap from a plain project folder, not just a prompt.
- **Keep control visible:** `status`, `inbox`, and `resume` make the operator inbox explicit when DeepLoop needs a real decision.
- **Inspect the loop:** operator-facing summaries expose runtime telemetry, inner-loop progress, stage-kernel activity, reroutes, and temporary gaps instead of hiding them in raw JSON.
- **Keep evidence close to the work:** your project folder stays focused on facts, docs, and outputs while DeepLoop keeps durable mission state.
- **Use autonomy with governance:** the shipped path includes explicit release boundaries, autonomy governance, and reviewed promotion surfaces.
- **Separate platform from domain logic:** DeepLoop runs the loop; substrate repos keep reusable methods, constraints, and science rules.

## Getting started

1. **Install DeepLoop**

   ```text
   python -m pip install -e .
   ```

   Or use the documented Conda path:

   ```text
   conda env create -n deeploop -f environment.yml
   ```

2. **Prepare the workspace and validate the supported path**

   ```text
   make setup
   make public-bootstrap-check
   ```

3. **Prepare a provider**
   - [Provider setup](docs/reference/provider-setup.md)
   - [Provider selection](docs/reference/provider-selection.md)

4. **Run the canonical example or your own plain-folder project**
   - canonical example: [`examples/translation-budget-ladder/`](examples/translation-budget-ladder/)
   - optional copy step:

     ```text
     cp -R examples/translation-budget-ladder PROJECT_FOLDER
     ```

   - fastest path:

     ```text
     deeploop-run-project --project-root examples/translation-budget-ladder --until-complete
     ```

   - explicit operator path:

     ```text
     deeploop-init-mission --project-root examples/translation-budget-ladder --force
     ```

   On a copied folder, substitute `PROJECT_FOLDER` in the commands above.

5. **Use the operator CLI when a run pauses**

   ```text
   deeploop status --mission-state MISSION_STATE_PATH
   deeploop inbox --mission-state MISSION_STATE_PATH
   deeploop resume --mission-state MISSION_STATE_PATH
   ```

The installed `deeploop*` commands are the preferred first-run path; lower-level repo scripts remain available for debugging and automation.

## Best fit today

DeepLoop is best when you already have:

- a project folder on disk
- a clear mission or question
- an operator who can check `status` and respond when the operator inbox opens
- a need for bounded autonomy, durable state, and evidence-aware summaries

### Current limits

DeepLoop is still a bounded-support public alpha. Stay on the documented Linux with Python 3.11 path if you want the experience public CI validates today.

Today DeepLoop is **not** claiming:

- broad installability across arbitrary environments
- a fully automatic experience for everyone
- approval-free release promotion
- a finished scratchpad -> formalization bridge

Messy notebook wandering and "start from nothing and figure it out" ideation are still a weak fit. The scratchpad -> formalization bridge remains exploratory, not part of the current alpha promise.

## Key capabilities

### Operating modes

- **`sandboxed-yolo`** for the fastest bounded path when you want DeepLoop to keep moving inside the supported guardrails
- **`managed`** when you want intervention hooks before DeepLoop continues; managed mode can surface a bounded retry, reroute, or downscope step for review
- **`human-directed`** when you want to approve important choices yourself

### What you can inspect

- operator-facing status surfaces runtime telemetry, inner-loop progress, ratchets, reroutes, and temporary-gap recovery hints
- stage-kernel execution stays visible instead of disappearing behind one opaque agent loop
- the operator inbox keeps handoffs explicit when DeepLoop reaches a real decision or support boundary

### Reusable methods and governance

- keep skills for reusable methods and domain/science rules in substrate repos
- use [Release posture](docs/release/README.md) for the current claim and [Autonomy governance](docs/release/autonomy-governance.md) for current boundaries
- review the current [multi-substrate proof](docs/release/multi-substrate-proof.md) as proof of a bounded contract, not a claim of broad portability

## Documentation

- [Docs home](docs/index.md)
- [Getting started](docs/getting-started.md)
- [Examples](docs/how-to/examples.md)
- [Plain-folder starter](docs/how-to/plain-folder-starter.md)
- [Release posture](docs/release/README.md)
- [Portable bootstrap](docs/release/portable-bootstrap.md)
- [Provider setup](docs/reference/provider-setup.md)
- [Provider selection](docs/reference/provider-selection.md)
- [Autonomy governance](docs/release/autonomy-governance.md)
- [Multi-substrate proof](docs/release/multi-substrate-proof.md)
- [Technical reference](docs/reference/index.md)

## Contributing

Contributions, bug reports, and discussion are welcome.

- [Contributing guide](CONTRIBUTING.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
