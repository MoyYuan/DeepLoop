# DeepLoop operating model

DeepLoop is a bounded-support autonomous research autopilot with an operator
management layer, not a loose collection of runtime tools. All three
product-facing modes share the same mission contract and operator surfaces.

## Default operator path

Operators should mostly use one CLI and one loop:

- launch with `python scripts/mission/manage_mission.py start --mission-state <mission_state.json>`
- monitor with `python scripts/mission/manage_mission.py status --mission-state <mission_state.json>`
- if DeepLoop stops or blocks: inspect `status`, open `inbox` when present,
  record `retry` or `reroute` if you changed the path, then `resume`

Plain-English gate semantics:

- **soft gate**: DeepLoop hit a recoverable research/runtime problem and should
  retry, reroute, or downscope before bothering the operator
- **hard gate**: DeepLoop crossed a real safety, authority, or sandbox boundary
  and should stop for operator review

The `status` and `inbox` surfaces now use one shared operator-state vocabulary:

- `lifecycle_state`: running, blocked, paused, completed
- `operator_state`: whether the operator is only observing, has optional input,
  or is required to act
- `attention_level`: how urgently the mission needs human review
- `next_step_owner`: whether DeepLoop or the operator should act next
- `resume_policy`: whether `resume` should continue immediately or wait for a
  human response
- `state_reason` / `blocked_on`: short explanation of what is holding progress

When stage runtime reports exist, `status` also surfaces the live observability
summary that operators actually use: active stage, processed vs remaining
examples, token/compute budget summaries, ETA quality, and cost telemetry when
available (or the current token/elapsed-time proxy when cost is unavailable).

## 1. Sandboxed YOLO mode (default)

Use this when:

- the mission and guardrails are already defined
- users want an autopilot default where DeepLoop handles the internals
- the workload can stay inside DeepLoop's sandbox and policy gates

Characteristics:

- this is the default mode for new mission configs
- operators normally use `manage_mission.py start` and `manage_mission.py
  status`, with `run_mission.py`/`monitor_mission.py` underneath as backend
  surfaces
- agents may propose, prioritize, execute, critique, and summarize mission work
  autonomously inside bounded sandbox and evidence policy
- the default hard-gate profile is `minimal`: only real safety/authority
  boundary crossings hard-stop, while scientific, budget, executor, and
  quality issues stay soft-first and should retry, reroute, or downscope when
  possible
- operators mostly set mission, budget, and guardrails, then review outcomes
- public-facing release still requires human review

## 2. Managed mode

Use this when:

- an expert operator wants broader permissions than the default sandbox profile
- debugging or higher-touch supervision needs explicit intervention hooks
- the same mission loop should run, but with more operator control surfaces

Characteristics:

- it keeps the same outer runtime, evidence policy, and mission contracts
- it widens permissions only by explicit configuration
- it exposes more operator intervention hooks than sandboxed-yolo while keeping
  the same management CLI and operator inbox flow
- public-facing release still requires human review

## 3. Human-directed mode

Use this when:

- research direction is still being shaped
- benchmark or metric assumptions are changing
- expensive jobs need close supervision

Characteristics:

- humans approve important design choices
- agents implement and document the work
- manifests and configs still govern execution, but the human stays in the loop
  on major decisions instead of treating DeepLoop like background autopilot

## Relationship to substrate repos

`translation-pilot` and `forecast-lab` are not replaced by DeepLoop.

They act as:

- target domains
- minimal fact/contract substrates
- scientific evaluation surfaces

DeepLoop owns runtime behavior and build/execution surfaces: orchestration,
critique, retry/reroute logic, backend policy, generic execution kernels, build
repo code, runtime scripts, generated configs, and experiment implementation
surfaces needed to run the work.

This explicitly includes **build repo code** as a DeepLoop-owned surface.

Substrate repos own the minimal seed materials DeepLoop starts from: benchmark
facts, project brief, prompts, metrics, slice definitions, safety/scientific
rules, and evaluation contracts.

Those minimal substrate facts do **not** cap DeepLoop's scientific decisions.
DeepLoop may still propose additional trusted datasets, stronger metrics, new
evaluation slices, and new training or adaptation plans when the science calls
for them.

Some proof substrates still include narrowly scoped compatibility wrappers for
reproducing earlier experiments. Those wrappers are exceptions, not the normal
runtime model: they should stay explicit, inventoried, and temporary, and new
DeepLoop-owned surfaces such as build repo code or generated configs should not
move into the substrate repo.
