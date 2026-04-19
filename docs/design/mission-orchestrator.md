# Mission orchestrator

DeepLoop's canonical runtime is a mission-level outer loop with an operator
management layer, not a collection of isolated helpers.

## Responsibilities

- ingest human ideas and constraints
- materialize a mission state
- sequence phases across the full research lifecycle
- choose the next mission action from durable evidence
- dispatch runtime-owned executors
- persist mission-level artifacts, ledgers, monitor surfaces, and platform
  handoff records

## Canonical surfaces

- operator management layer: `scripts/mission/manage_mission.py`
- backend runtime: `src/deeploop/mission/mission_runtime.py`
- backend runtime CLI: `scripts/mission/run_mission.py`
- backend monitor CLI: `scripts/mission/monitor_mission.py`
- multi-mission scheduler: `src/deeploop/mission/mission_scheduler.py`
- platform handoff sync: `src/deeploop/platform/contracts.py`

The outer loop owns mission-level decision-making and state transitions. It is
the primary DeepLoop execution path, while `manage_mission.py` is the primary
operator path.

## Canonical flow

1. Load the mission state plus the machine-readable outer-loop contract.
2. Materialize mission memory, operator inbox, and platform handoff paths.
3. Gather evidence from mission outputs, failure records, branch history, and
   mission memory.
4. Decide the next action or phase transition through the mission decision
   engine.
5. Dispatch the selected action through the mission executor registry.
6. Persist the updated mission state, decision log, branch log, runtime history,
   monitor artifacts, platform handoff artifacts, and package outputs.

## Operator control loop

The intended operator experience is:

1. `manage_mission.py start` launches DeepLoop autopilot in the background.
2. `manage_mission.py status` is the obvious monitor path after a fresh mission
   init/bootstrap.
3. Soft gates stay operator-light: DeepLoop should recommend a retry, reroute,
   or downscope path in plain language.
4. Hard gates stop for review and write durable inbox artifacts under the
   mission root: `mission_operator_requests.jsonl` and
   `current_operator_request.json`.
5. If the mission blocks, the operator handles it through `status`, `inbox`,
   optional `retry`/`reroute`, then `resume`.

The operator console is now a real observability surface, not a placeholder: it
renders operator state, exact next commands, and inner-loop runtime telemetry
from stage/runtime reports when those artifacts exist.

## Mission outer-loop contract

DeepLoop-mode missions now carry a machine-readable outer-loop contract in
`mission_state.json` under `outer_loop`.

- internal execution is autonomous by default
- phase transitions, branch creation, runtime-owned artifact edits, bounded
  local training/eval, critique, replication, and private final reports do not
  require operator approval by default
- the default operator mental model is `sandboxed-yolo`: DeepLoop keeps working
  unless a true hard gate needs review
- hard gates are reserved for real safety, authority, or sandbox boundary
  crossings; research/runtime failures should stay soft-first when possible
- external publish / release remains operator-gated by default
- mission decision and branch logs are durable JSONL artifacts, not implicit
  state

## Secondary surfaces

DeepLoop still keeps smaller bounded runtimes, but they are subordinate to this
controller:

- stage-kernel execution
- self-healing queue runs
- recursive fresh-context agent workers
- bounded end-to-end smoke proofs

Those surfaces are useful as executors, proofs, or support utilities, not
as replacements for the mission outer loop.
