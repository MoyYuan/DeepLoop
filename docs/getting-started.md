# Getting started

This is the shortest path to using DeepLoop without needing to understand every
runtime detail first.

## What you need

- the DeepLoop repo
- either a minimal plain-folder project with `project-facts.yaml` plus docs, or
  an explicit mission config
- a terminal
- a supported environment (today: Linux with Python 3.11 and the documented
  workspace roots)
- machine-level access to one of the documented provider families before you
  start mission execution

DeepLoop is currently a **bounded-support autonomous research autopilot**:
Linux with Python 3.11, editable install or the documented Conda path, and the
documented workspace roots. It should not yet be described as broadly
installable everywhere or fully automatic for everyone.

## First useful path

1. Install DeepLoop:

   ```text
   python -m pip install -e .
   ```

   The Conda path remains supported too:

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

4. Prepare machine-level provider availability:

   ```text
   see docs/reference/provider-setup.md
   ```

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

5. Declare mission/runtime provider selection:

    ```text
    see docs/reference/provider-selection.md
    ```

    This selection contract is intentionally separate from machine setup:

    - choose provider family per mission, loop, role, or phase
    - choose backend and model alias/identifier
    - define allowed fallbacks and override points
    - keep secrets and credential values outside repo config

6. Start from the canonical public example or your own plain-folder project,
   then materialize a mission state from the project folder itself:

    ```text
    cp -R examples/translation-budget-ladder <project-folder>
    ```

    `examples/translation-budget-ladder/` is the main onboarding example. The
    proof-matrix fixture under `tests/_proof_fixtures/plain_folder/` remains
    validation-only. See [Examples](how-to/examples.md) and
    [Plain-folder starter](how-to/plain-folder-starter.md) for the public-safe
    folder contract.

    ```text
    python scripts/mission/init_mission.py --project-root <project-folder> --force
    ```

   DeepLoop will synthesize the mission config into the mission runtime and keep
   the project folder as the only required project-side input.

   For the stricter substrate boundary, `<project-folder>` can now be just plain
   researcher-provided artifacts such as a `project-facts.yaml`, brief docs,
   benchmark notes, metric notes, and budget facts. It does not need a local
   `.deeploop/` contract for this bootstrap path. See
   [Plain-folder starter](how-to/plain-folder-starter.md) for the canonical
   public example contract.

   If you already have an explicit mission config, the config path still works:

   ```text
   python scripts/mission/init_mission.py --config <mission-config.yaml> --force
   ```

7. Start the mission with the canonical operator CLI:

   ```text
   python scripts/mission/manage_mission.py start --mission-state <mission_state.json>
   ```

8. Check the operator console:

   ```text
   python scripts/mission/manage_mission.py status --mission-state <mission_state.json>
   ```

   If you want repeated polls, use:

   ```text
   python scripts/mission/manage_mission.py watch --mission-state <mission_state.json>
   ```

   Use `logs` or `decisions` only when you need more detail than `status`.

9. If DeepLoop asks for help, inspect the inbox:

   ```text
   python scripts/mission/manage_mission.py inbox --mission-state <mission_state.json>
   ```

   In managed mode, run `triage` first when the blocked request exposes
   intervention hooks for a blocked queue entry.

10. If you changed the path, record it, then resume:

   ```text
   python scripts/mission/manage_mission.py retry --mission-state <mission_state.json> --note "<what changed>"
   python scripts/mission/manage_mission.py reroute --mission-state <mission_state.json> --note "<new plan>"
   python scripts/mission/manage_mission.py resume --mission-state <mission_state.json>
   ```

Optional higher-level launcher:

```text
python scripts/mission/run_project.py --project-root <project-folder> --until-complete
```

This extends the bounded mission-runtime budget until completion, a true
operator-required boundary, or total-iteration exhaustion. After launch, the
operator contract is still `manage_mission.py status` / `inbox` / `resume`.

Use placeholders such as `<project-folder>`, `<mission-config.yaml>`, and
`<mission_state.json>` in your own setup rather than copying any hardcoded
personal path from a machine-specific example.

## What success looks like

- `status` shows `operator_state: autopilot-running` or `autopilot-recovering`
- the operator inbox is clear unless DeepLoop needs a real decision
- DeepLoop is working on a real next action

## When something goes wrong

- If `status` shows `operator-action-required`, read the inbox first.
- If `status` shows `needs-investigation`, inspect `status`, `logs`, and
  `decisions` before resuming.
- If `status` shows `autopilot-ready-to-resume`, the last run ended after a
  soft-gate recovery path and another bounded `resume` is optional.

## Learn more

- [Mission operations](guide/operator.md)
- [Examples](how-to/examples.md)
- [Provider setup](reference/provider-setup.md)
- [Provider selection](reference/provider-selection.md)
- [Runtime architecture](concepts/architecture.md)
- [FAQ](guide/faq.md)
- [Plain-folder starter](how-to/plain-folder-starter.md)
- [Portable bootstrap](release/portable-bootstrap.md)
- [Public autonomy roadmap](release/public-autonomy-roadmap.md)
