# DeepLoop

> Structured research missions from a bundled starter or local project folder — with visible autonomy boundaries, durable mission state, and an explicit operator inbox.

DeepLoop helps researchers and operators run structured work from existing artifacts or a bundled starter instead of rebuilding everything around one long chat. It keeps the loop moving, pauses only at real safety, authority, or support boundaries, and makes the path legible when you need to inspect or redirect it.

DeepLoop **owns behavior** and orchestration; substrate repos own reusable domain or science rules.

## Why it matters

- **Start from a real folder or a bundled starter:** use the same mission flow either way.
- **Keep control visible:** `status`, `inbox`, and `resume` make the operator inbox explicit when DeepLoop needs a real decision.
- **Inspect the loop:** operator-facing summaries expose runtime telemetry, inner-loop progress, stage-kernel activity, reroutes, and temporary gaps instead of hiding them in raw JSON.
- **Keep evidence close to the work:** your project folder stays focused on facts, docs, and outputs while DeepLoop keeps durable mission state.
- **Use autonomy with governance:** the shipped path includes explicit release boundaries, autonomy governance, and reviewed promotion surfaces.
- **Separate platform from domain logic:** DeepLoop runs the loop; substrate repos keep reusable methods, constraints, and science rules.

## Getting started

1. **Install DeepLoop**

   ```text
   pip install deeploop
   ```

   For the full install matrix — GitHub installs, editable contributor setup,
   two-clone hybrid workflows, and the documented Conda path — use
   [Getting started](docs/getting-started.md).

2. **Set up a provider**

   DeepLoop uses OpenAI-compatible API providers. Configure your API key and
   endpoint:

   ```text
   export OPENAI_API_KEY="sk-..."
   export OPENAI_BASE_URL="https://api.deepseek.com"
   ```

   The default control-plane profile uses `deepseek-chat` via the
   OpenAI-compatible adapter. See [Provider setup](docs/reference/provider-setup.md)
   for other options.

3. **Run DeepLoop**

   Start a mission with a single command:

   ```text
   deeploop start --idea "your research idea"
   ```

   DeepLoop materializes a project under `WORKSPACE_ROOT/projects/`, compiles a
   mission from your idea, and launches the same operator loop as every other path.

   To start from an existing project folder:

   ```text
   deeploop start --project-root <project-folder> --idea "your research idea"
   ```

   To control iteration budget and cost:

   ```text
   deeploop start --idea "your research idea" --max-iterations 50 --max-cost 10.00
   ```

   If you prefer an interactive kickoff that asks for your mission idea and lets
   you choose a bundled starter:

   ```text
   deeploop start
   ```

4. **Use the operator CLI when a run pauses**

   ```text
   deeploop status
   deeploop inbox
   deeploop resume
   ```

   Start with `status` for a compact overview of runtime telemetry, inner-loop
   progress, and current state. Open `inbox` only when DeepLoop pauses for a
   real decision — it shows actionable handoffs with the exact information needed
   to respond. Use `logs`, `decisions`, `retry`, `reroute`, or `triage` only
   when the surfaced handoff says you need more detail or a managed-mode override.

The `deeploop` CLI is the single entry point — `start`, `status`, `inbox`,
`resume`, and more are all subcommands.

## Readiness at a glance

- **Unified first run:** Linux, Python 3.11+, `pip install deeploop`, `export OPENAI_API_KEY="sk-..."`, `deeploop start --idea "your research idea"`
- **Same front door for existing work:** use `deeploop start --project-root <project-folder> --idea "your research idea"`
- **Repo-checkout validation path:** `make setup`, `make public-bootstrap-check`, and direct access to `examples/translation-budget-ladder/`
- **Messy starts are supported:** rough plain-folder projects can initialize with disclosed clarifications/defaults, or you can use `deeploop init --discover ...` for a guided kickoff
- **Repair stays bounded:** if the folder is missing the plain-folder bootstrap contract, DeepLoop exits with bootstrap-repair guidance and suggested starter inputs instead of silently rewriting project files
- **Current baseline release proof:** `make public-bootstrap-check`, `make docker-release-validate`, and `make docs-build`

## Best fit today

DeepLoop is best when you have:

- either a project folder on disk or a clear enough idea to start from a bundled starter
- a clear mission or question
- an operator who can check `status` and respond when the operator inbox opens
- a need for bounded autonomy, durable state, and evidence-aware summaries

> **Public alpha** — best on Linux with Python 3.11; not claiming a fully automatic experience for everyone. See the [roadmap](docs/release/public-autonomy-roadmap.md) for current scope.

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
