# Recursive agent runtime

DeepLoop includes a bounded **recursive agent-driving executor** for mission
actions that need repeated fresh-context CLI work.

- run **fresh-context agent iterations**
- persist external memory between iterations
- hand the next step from one iteration to the next in machine-readable form
- merge mission-state updates from agent results
- stop on explicit completion, bounded failure, or iteration budget

## Position in the architecture

- canonical top-level execution path: `scripts/mission/run_mission.py`
- bounded worker entrypoint: `scripts/mission/run_recursive_agent_loop.py --config <loop-config>`
- normal usage: the mission executor registry dispatches this runtime when a
  mission action selects the `recursive-agent` executor
- direct CLI usage is for isolated debugging, integration flows, or smoke
  proofs

## Prior-art influence

### Ralph

Borrowed directly:

- fresh-context iterations
- cheap external memory
- explicit completion signal
- lightweight loop controller outside the agent context

### AutoResearch

Borrowed directly:

- metric/result-driven iteration
- explicit keep/discard style loop state
- crash/failure handling as a first-class branch
- long-running autonomous repetition with bounded local rules

## Runtime contract

The runtime entrypoint is:

- `scripts/mission/run_recursive_agent_loop.py --config <loop-config>`

The canonical mission path remains `run_mission.py`; this runtime is a bounded
subordinate executor, not the primary controller.

The loop config must provide:

- `mission_state`
- `loop_name`
- `agent.command`

The loop config may also carry `provider_selection` to declare which provider
family, backend, and model the loop intends to use. That selection block is
separate from machine setup in [Provider setup](../reference/provider-setup.md)
and follows the canonical contract in
`configs/runtime/provider-selection-registry.yaml`.

The `agent.command` can invoke a provider launcher or another
provider-compatible command template. DeepLoop does not hardcode a specific
binary name because the available local launcher can vary across machines and
installs. The current public provider launcher lives at
`scripts/runtime/invoke_provider_prompt.py` and currently delegates
`copilot-cli` requests to the Copilot adapter while the `provider_selection`
block remains the stable selection record.

For the shipped recursive-agent example, DeepLoop also ships:

- `scripts/runtime/invoke_provider_prompt.py`
- `configs/runtime/recursive-agent-runtime-provider.example.yaml`

This keeps the outer-loop runtime generic while preserving Copilot CLI as one
supported provider adapter.

Template placeholders supported in `agent.command`:

- `{prompt_path}`
- `{result_json_path}`
- `{sandbox_root}`
- `{inputs_dir}`
- `{outputs_dir}`
- `{mission_state_path}`
- `{target_repo}`
- `{role}`
- `{iteration}`
- `{loop_action_id}`
- `{mission_action_id}`
- `{branch_id}`
- `{action_kind}`
- `{action_phase}`
- `{decision_id}`

If `agent.env_name` is set, DeepLoop wraps the command in:

- `conda run -n <env_name> ...`

## Per-iteration flow

1. Load mission state and loop state.
2. Choose the next action from:
   - a pending next-step emitted by the previous agent result, or
   - mission `next_actions.actions`, or
   - the loop config `initial_task`.
3. Build a fresh sandbox spec for the selected role.
4. Render a prompt with:
   - mission objective and phase
   - current task
   - artifact inputs
   - rule sources
   - recent ledger entries
   - recent recursive-loop memory
   - explicit result JSON contract
5. Launch the external agent CLI in fresh context.
6. Capture stdout/stderr/logs.
7. Read the machine-written result JSON.
8. Append durable loop memory and ledger entries.
9. Merge any mission-state updates supplied by the agent result.
10. Continue, complete, or stop on bounded failure.

## Result JSON contract

The agent must write a JSON file with at least:

- `status`: `continue` | `complete` | `blocked` | `failed`
- `summary`

Optional fields:

- `continuation`
- `action_result`
- `phase_control`
- `produced_artifacts`
- `findings`
- `mission_state_updates`

For backward compatibility with earlier loop artifacts, the runtime can still
ingest `next_role` / `next_task` fields. New integrations should emit the
structured `continuation`, `action_result`, and `phase_control` objects so the
recursive runtime can act as a subordinate mission executor with stable action
IDs, branch context, and phase-transition signals.

This gives DeepLoop a stable **machine-readable handoff primitive** between one
agent iteration and the next.

## Durable outputs

For a mission at:

- `~/workspaces/runs/deeploop/missions/<mission-id>/mission_state.json`

the recursive runtime writes under:

- `~/workspaces/runs/deeploop/missions/<mission-id>/runtime/recursive_agent_runtime/<loop-name>/`

including:

- `agent_loop_state.json`
- `loop_memory.jsonl`
- `loop_report.json`
- `loop_report.md`
- per-iteration prompt/log/result/summary files

Mission state is updated under `mission_state.json` in:

- `agent_driver`

Mission findings are appended under:

- `findings/recursive-loop-*.md`

Provider-returned `produced_artifacts` are accepted only when they resolve under
the current role's sandbox `outputs_dir`, the mission artifact roots
(`findings/`, `runtime/`, `agent_handoffs/`), or an explicitly configured
`allowed_mission_artifact_roots` entry. Out-of-scope paths stay out of
`produced_artifacts` and action `output_paths`; the iteration outcome records an
artifact provenance entry with `produced_by`, `sandbox_root`, `accepted`, and a
rejection reason plus a warning.

## Recursive budget-warning review

The current recursive budget warnings fire in two places:

- the runtime prints a stderr warning when utilization reaches at least 80% of
  `max_iterations` and at least one recursive iteration remains
- `deeploop analyze-budget` warns when the pending queue projects to at least
  80% utilization, and escalates to `over-budget` when it exceeds the ceiling

The low-signal pattern from the current release is cadence, not coverage. Once a
loop crosses the 80% threshold, the runtime repeats the same near-ceiling
warning on every subsequent iteration until the loop finishes or yields. That is
most noticeable on longer queues, where operators can see multiple variants of
the same "budget nearly exhausted" message even though the actionable decision
is unchanged. The dedicated execution-handoff warning already covers the most
actionable late-budget case: yielding before entering execution with only one
recursive iteration left.

Decision for the next release cycle:

- keep the 80% warning threshold for now
- keep the dedicated execution-handoff and `over-budget` warnings as-is
- tune near-ceiling runtime warnings in a follow-up PR so they fire once when
  the loop first crosses the threshold instead of on every post-threshold
  iteration
- soften near-ceiling warning wording in that follow-up so it reads as advisory
  budget pressure, while the stronger wording remains reserved for true
  `over-budget` and execution-handoff conditions
- continue treating `deeploop analyze-budget` as the preferred proactive
  operator check before submitting a large recursive queue

## Why this runtime exists

This executor fills the fresh-context worker slot inside the canonical mission
runtime without moving the top-level controller into the agent context.

## Current scope

This is still bounded, not infinite or cluster-scale. Items outside the current
public-alpha scope include:

- richer stop/budget policies
- multi-agent parallel swarms
- automatic training-branch scheduling
- stronger research-memory indexing beyond flat JSONL history
- additional provider-adapter contracts for machines that do not use the shipped
  Copilot-backed launcher
