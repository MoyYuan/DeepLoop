# Getting started

This is the shortest supported path from clone to a first running mission. You
do not need to understand every runtime detail before you start.

## What you need

- the DeepLoop repo
- either a minimal plain-folder project with `project-facts.yaml` plus docs, or
  an explicit mission config
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
   `init`, `start`, `status`, `inbox`, `resume`, `package`, and more.

   The Conda path remains supported too (installs in non-editable mode by
   default):

   ```text
   conda env create -n deeploop -f environment.yml
   ```

   Add the separate LLM runtime env only when you need local model inference:

   ```text
   conda env create -n llm -f environment.llm.yml
   ```

2. Prepare the workspace:

   ```text
   make setup
   ```

3. Validate the public bootstrap path:

   ```text
   make public-bootstrap-check
   ```

   This is the clean-room validation contract used by public CI.

4. Prepare machine-level provider availability with
   [Provider setup](reference/provider-setup.md).

   This setup contract is intentionally limited to machine readiness:

   - which tools must exist on the machine
   - which env vars/auth prerequisites are expected
   - which readiness checks should pass before mission execution

   It does **not** choose the provider or model for a specific mission. That
   mission/runtime selection contract now lives in
   [Provider selection](reference/provider-selection.md).

   If you only need local inference backends, the separate runtime env remains:

   ```text
   conda env create -n llm -f environment.llm.yml
   ```

5. Declare mission/runtime provider selection with
   [Provider selection](reference/provider-selection.md).

   This selection contract is intentionally separate from machine setup:

   - choose provider family per mission, loop, role, or phase
   - choose backend and model alias/identifier
   - define allowed fallbacks and override points
   - keep secrets and credential values outside repo config

6. Start from the canonical public example or your own plain-folder project:

    ```text
    cp -R examples/translation-budget-ladder <project-folder>
    ```

    `examples/translation-budget-ladder/` is the canonical public example. The
    proof-matrix fixture under `tests/_proof_fixtures/plain_folder/` remains
    validation-only. See [Examples](how-to/examples.md) and
    [Plain-folder starter](how-to/plain-folder-starter.md) for the public-safe
    plain-folder contract.

   Fastest happy path:

   ```text
   deeploop run --project-root <project-folder> --until-complete
   ```

    This is the shortest "use DeepLoop on a real project folder" path. It
    bootstraps the mission from the folder itself, then keeps running until
    completion, a true operator boundary, or total-iteration exhaustion.
    If it stops for operator review, use the returned `<mission-state.json>`
    with the `deeploop` commands below.

    > **Important:** `deeploop run` automatically detects explicit mission
    > configs in `<project-folder>/.deeploop/missions/*.yaml`. If one or more
    > YAML files are found there, `deeploop run` uses the first config instead
    > of bootstrapping a blank mission. If no explicit config exists, it
    > bootstraps from the folder's plain facts (e.g. `project-facts.yaml`).
    >
    > If you have multiple explicit configs or need to target a specific one,
    > use `deeploop init --config <mission-config.yaml>` followed by
    > `deeploop start --mission-state <mission-state.json>` instead of
    > `deeploop run`.

    If you want the explicit operator flow instead, materialize a mission state
    first:

   ```text
   deeploop init --project-root <project-folder> --force
   ```

   DeepLoop will synthesize the mission config into the mission runtime and keep
   the project folder as the only required project-side input. `deeploop init`
   prints the `<mission-state.json>` path you will use with `deeploop`.

   For the stricter substrate boundary, `<project-folder>` can now be just plain
   researcher-provided artifacts such as a `project-facts.yaml`, brief docs,
   benchmark notes, metric notes, and budget facts. It does not need a local
   `.deeploop/` contract for this bootstrap path. See
   [Plain-folder starter](how-to/plain-folder-starter.md) for the canonical
   public example contract.

   If you already have an explicit mission config, the config path still works:

   ```text
   deeploop init --config <mission-config.yaml> --force
   ```

7. If you initialized a mission state, start it with the canonical operator CLI:

   ```text
   deeploop start --mission-state <mission-state.json>
   ```

8. Check the operator console:

   ```text
   deeploop status --mission-state <mission-state.json>
   ```

   If you want repeated polls, use:

   ```text
   deeploop watch --mission-state <mission-state.json>
   ```

   Use `logs` or `decisions` only when you need more detail than `status`.
   When measurable adaptation or recovery signals exist, `status` now surfaces
   the ratchet, latest reroute, and temporary-gap hints directly.

9. If DeepLoop asks for help, inspect the inbox:

   ```text
   deeploop inbox --mission-state <mission-state.json>
   ```

   In managed mode, run `triage` first when the blocked request exposes
   intervention hooks for a blocked queue entry. If the inbox already says
   managed mode staged the next bounded recovery step, you can usually review
   that note and go straight to `resume`.

10. If you changed the path, record it with `retry` or `reroute`, then `resume`:

    ```text
    deeploop retry --mission-state <mission-state.json> --note "<what changed>"
    deeploop reroute --mission-state <mission-state.json> --note "<new plan>"
    deeploop resume --mission-state <mission-state.json>
    ```

Advanced/fallback repo-level surfaces:

```text
python scripts/mission/run_project.py --project-root <project-folder> --until-complete
python scripts/mission/init_mission.py --project-root <project-folder> --force
python scripts/mission/manage_mission.py status --mission-state <mission-state.json>
```

Keep these lower-level script surfaces for debugging, automation, or environments
where you intentionally want the repo-internal entry points. The `deeploop` CLI
above is the preferred first-run path.

Use placeholders such as `<project-folder>`, `<mission-config.yaml>`, and
`<mission-state.json>` in your own setup rather than copying any hardcoded
personal path from a machine-specific example.

## What success looks like

- `status` shows `operator_state: autopilot-running` or `autopilot-recovering`
- the operator inbox is clear unless DeepLoop needs a real decision
- DeepLoop is working on a real next action
- when measurable adaptation or recovery signals exist, `status` surfaces the
  ratchet, latest reroute, and temporary-gap telemetry directly instead of
  leaving them buried in raw JSON

## When something goes wrong

- If `status` shows `operator-action-required`, read the inbox first.
- If `status` shows `needs-investigation`, inspect `status`, `logs`, and
  `decisions` before resuming.
- If `status` shows `autopilot-ready-to-resume`, the last run ended after a
  soft-gate recovery path and another bounded `resume` is optional.
- In managed mode, check whether `status` or `inbox` says a retry, reroute, or
  downscope step was already staged for you before you record one manually.

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
