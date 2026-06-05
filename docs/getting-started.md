# Getting started

This is the shortest supported path from install to a first running mission. You
do not need to understand every runtime detail before you start.

## What you need

- either a rough mission idea, your own plain-folder project, or a repo checkout
  if you want direct access to the public example
- a terminal
- a supported environment (today: Linux with Python 3.11 and the documented
  workspace roots)
- access to one documented provider family so DeepLoop can run the mission once
  setup is complete

Stay on the documented path for the smoothest first run: Linux with Python
3.11, the editable-install or documented Conda path, the documented workspace
roots, and one configured provider. That is the path public CI and fresh-clone
onboarding validate today; outside it, expect gaps.

## First useful path

1. Install DeepLoop — choose the path that matches your use case:

   - **Standard user** — install from PyPI (no local checkout required):

     ```text
     pip install deeploop
     ```

     For the latest unreleased commit without a local checkout:

     ```text
     pip install git+https://github.com/tnetal/DeepLoop.git
     ```

     Both paths copy the library into `site-packages`, isolating live missions
     from any local source changes.

   - **Contributor** — clone the repo and install in editable mode with dev
     extras:

     ```text
     git clone https://github.com/tnetal/DeepLoop.git
     cd DeepLoop
     pip install -e ".[dev]"
     ```

     > **Warning:** Editable installs tie every spawned Python subprocess
     > directly to the live source tree. `deeploop start` automatically
     > snapshots the package into `~/.deeploop/runtime_cache/` before launching
     > the daemon, insulating the background mission from subsequent source
     > edits. It also warns if the working tree is dirty at launch time. Even
     > so, avoid switching Git branches or introducing syntax errors during a
     > live mission run.

   - **Hybrid user** (running long missions *and* developing features
     simultaneously): maintain **two separate clones** — one stable clone
     installed with `pip install git+…` or `pip install .` for running
     missions, and one development clone with `pip install -e ".[dev]"` for
     writing PRs. Never run a background mission from the development clone.

   All install paths expose the `deeploop` CLI with all subcommands: `run`,
   `init`, `start`, `status`, `inbox`, `analyze`, `analyze-budget`, `resume`,
   `package`, and more.

   The Conda path remains supported too (installs in non-editable mode by
   default):

   ```text
   conda env create -n deeploop -f environment.yml
   ```

   Add the separate LLM runtime env only when you need local model inference:

   ```text
   conda env create -n llm -f environment.llm.yml
   ```

2. Set up a provider:

   DeepLoop uses OpenAI-compatible API providers. Configure your API key and
   endpoint:

   ```text
   export OPENAI_API_KEY="sk-..."
   export OPENAI_BASE_URL="https://api.deepseek.com"
   ```

   The default control-plane profile uses `deepseek-chat` via the
   OpenAI-compatible adapter. See [Provider setup](reference/provider-setup.md)
   for other options and provider families.

   If you want to verify machine-level readiness before running a mission:

   ```text
   deeploop provider-ready
   ```

   This checks that the required environment variables and tooling are in place
   without launching a mission.

3. Run DeepLoop:

   Start a mission with a single command:

   ```text
   deeploop start --idea "your research idea"
   ```

   This is the primary first-run story. DeepLoop materializes a project under
   `WORKSPACE_ROOT/projects/`, compiles a mission from your idea, and launches
   the operator loop.

   To start from an existing project folder with a specific idea:

   ```text
   deeploop start --project-root <project-folder> --idea "your research idea"
   ```

   This uses the same front door but bootstraps from your existing facts and
   docs instead of creating a bundled starter project.

   To control iteration budget and maximum cost:

   ```text
   deeploop start --idea "your research idea" --max-iterations 50 --max-cost 10.00
   ```

   If you prefer an interactive kickoff that asks for your mission idea and
   lets you choose a bundled starter:

   ```text
   deeploop start
   ```

   `deeploop run` is also available for compatibility and advanced use. It
   performs the same readiness check before kickoff. If setup is missing,
   DeepLoop stops early with the exact missing requirement, one next step, and
   a resume command.

   This is the shortest supported end-to-end path. It keeps running until
   completion, a true operator boundary, or total-iteration exhaustion. If it
   pauses, keep the operator loop simple: start with `status`, open `inbox`
   only when DeepLoop needs you, then `resume`.

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

   If you want repeated polls:

   ```text
   deeploop watch
   ```

5. **Advanced: explicit mission config and discovery paths**

   If your project folder already has explicit mission configs in
   `<project-folder>/.deeploop/missions/*.yaml`, `deeploop start` detects them
   automatically. To target a specific config directly:

   ```text
   deeploop init --config <mission-config.yaml> --force
   deeploop start --mission-state <mission-state.json>
   ```

   If the folder is rough but still recognizable, `deeploop init` can still
   materialize a mission state and keep the original project folder unchanged:

   ```text
   deeploop init --project-root <project-folder> --force
   ```

   On rough starts, the generated readiness summary can come back as
   `ready-with-clarifications` or `ready-with-defaults` so the handoff stays
   honest about what DeepLoop inferred.

   If you want the guided discovery flow first:

   ```text
   deeploop init --discover --project-root <project-folder> --force
   ```

   Discovery mode is the supported path when you want DeepLoop to ask
   clarifying questions, keep a checklist of missing information, and compile
   a reviewed mission config before kickoff.

   For the stricter substrate boundary, `<project-folder>` can be just plain
   researcher-provided artifacts such as a `project-facts.yaml`, brief docs,
   benchmark notes, metric notes, and budget facts. It does not need a local
   `.deeploop/` contract for this bootstrap path. See
   [Plain-folder starter](how-to/plain-folder-starter.md) for the canonical
   public example contract.

   If DeepLoop cannot bootstrap the project folder safely yet, it exits with
   bounded repair guidance instead of mutating the folder.

6. **When a decision is needed**

   If `status` shows `operator-action-required`, read the inbox first:

   ```text
   deeploop inbox
   ```

   In managed mode, run `triage` first when the blocked request exposes
   intervention hooks for a blocked queue entry. If the inbox already says
   managed mode staged the next bounded recovery step, you can usually review
   that note and go straight to `resume`.

   When the fix or choice is ready:

   ```text
   deeploop resume
   ```

   If you changed the path yourself, record that first with `retry` or `reroute`:

   ```text
   deeploop retry --note "<what changed>"
   deeploop reroute --note "<new plan>"
   deeploop resume
   ```

7. **When something goes wrong**

   - If `status` shows `operator-action-required`, read the inbox first.
   - If `status` shows `needs-investigation`, inspect `logs` and `decisions`
     before resuming.
   - If `status` shows `autopilot-ready-to-resume`, the last run ended after a
     soft-gate recovery path and another bounded `resume` is optional.
   - In managed mode, check whether `status` or `inbox` says a retry, reroute, or
     downscope step was already staged for you before you record one manually.

## What success looks like

- `status` shows `operator_state: autopilot-running` or `autopilot-recovering`
- the operator inbox is clear unless DeepLoop needs a real decision
- DeepLoop is working on a real next action
- when measurable adaptation or recovery signals exist, `status` surfaces the
  ratchet, latest reroute, and temporary-gap telemetry directly instead of
  leaving them buried in raw JSON

## Readiness summary you may see

- `ready` — the folder is explicit enough to launch directly on the supported path
- `ready-with-clarifications` — DeepLoop found a usable rough start and recorded
  clarification questions or disclosed assumptions in the mission summary
- `ready-with-defaults` — discovery mode filled in bounded defaults and kept the
  confirmed answers in mission state for operator review
- `blocked` with `repair-bootstrap-input` — the folder is missing required
  bootstrap inputs, so DeepLoop stops with repair guidance instead of guessing

## Advanced / repo-level fallback surfaces

> **Warning:** The canonical operator surface is the installed `deeploop` CLI.
> Use the repo-level scripts below only when you are intentionally debugging the
> DeepLoop runtime itself or running automation that targets repo internals.
> For normal first runs and day-to-day operation, stay on the `deeploop`
> commands above and see [Mission operations](guide/operator.md).

```text
python scripts/mission/run_project.py --project-root <project-folder> --until-complete
python scripts/mission/init_mission.py --project-root <project-folder> --force
python scripts/mission/init_mission.py --discover --mission-idea "I have a dataset and a rough goal"
python scripts/mission/manage_mission.py status --mission-state <mission-state.json>
```

The discovery path asks clarifying questions, keeps a missing-information
checklist, writes an inspectable compiled mission config, and asks for kickoff
confirmation before DeepLoop initializes the mission.

## Learn more

- [Mission operations](guide/operator.md)
- [Examples](how-to/examples.md)
- [Provider setup](reference/provider-setup.md)
- [Provider selection](reference/provider-selection.md)
- [Runtime architecture](concepts/architecture.md)
- [FAQ](guide/faq.md)
- [Plain-folder starter](how-to/plain-folder-starter.md)
- [Portable bootstrap](release/portable-bootstrap.md)
- [Release posture](release/README.md)
