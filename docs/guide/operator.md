# Mission operations

Use this page when you are starting, watching, stopping, or recovering a
mission through `python scripts/mission/manage_mission.py`.

## The canonical operator loop

1. Start with `manage_mission.py start`.
2. Monitor with `status`.
3. Use `watch`, `logs`, or `decisions` only when you need more detail.
4. Open `inbox` only when `status` says DeepLoop needs operator help.
5. In managed mode, use `triage` first when a blocked queue entry exposes
   intervention hooks.
6. Record `retry` or `reroute` if you changed the path.
7. Resume when the blocker is fixed.

## Commands operators actually use

| Command | Use it when |
| --- | --- |
| `start` | Launch the detached mission runtime |
| `status` | See the operator console, state vocabulary, and exact next commands |
| `inbox` | Read the current operator request and recommendation |
| `resume` | Continue after a stop, block, or completed operator fix |
| `logs` | Inspect the detached process log tail |
| `decisions` | Inspect recent mission decisions without reading raw JSONL |
| `watch` | Poll for fresh watch/alarm lines during monitoring |
| `retry` / `reroute` | Record the operator change before `resume` |
| `triage` | Run the bounded managed-mode triage hook when intervention hooks are enabled |
| `stop` | Stop the detached mission process |

Most operators live on these four commands:

```text
python scripts/mission/manage_mission.py start --mission-state <mission_state.json>
python scripts/mission/manage_mission.py status --mission-state <mission_state.json>
python scripts/mission/manage_mission.py inbox --mission-state <mission_state.json>
python scripts/mission/manage_mission.py resume --mission-state <mission_state.json>
```

## What `status` is telling you

`status` surfaces both mission progress and operator posture.

### Mission-facing labels

| Field | Common values | Meaning |
| --- | --- | --- |
| `mission_state` / `lifecycle_state` | `running`, `blocked`, `paused`, `completed`, `stopped` | Where the mission run is in its lifecycle |
| `gate_class` | `none`, `soft-gate`, operator-needed blocker kinds | Whether DeepLoop is just recovering or has crossed a true boundary |
| `process_status` | `running`, `exited`, `unknown` | Whether the detached runtime process is still alive |

### Operator-facing labels

| `operator_state` | Meaning | What to do |
| --- | --- | --- |
| `autopilot-running` | DeepLoop is healthy and still owns the next step | Keep watching `status` |
| `autopilot-recovering` | A soft gate opened, but DeepLoop is still retrying/rerouting/downscoping on its own | Usually do nothing |
| `operator-action-required` | A real blocker opened the operator inbox | Read `inbox`, make the smallest safe fix |
| `autopilot-ready-to-resume` | The last run ended after a soft-gate recovery path | Inspect briefly, then `resume` if you want another bounded pass |
| `mission-complete` | The mission reached a completed state | Review outputs; no resume needed |
| `needs-investigation` | The mission is blocked, failed, paused, or the detached process exited unexpectedly | Inspect `status`, `logs`, and `decisions` before `resume` |
| `stopped` | No detached mission is running and no stronger state is active yet | `start` or `resume` once the next step is clear |

The related hints are:

- `attention_level`: how urgently to look (`passive`, `resume-optional`,
  `action-required`, `investigate`, `complete`)
- `next_step_owner`: whether DeepLoop or the operator should act next
- `resume_policy`: whether `resume` is not needed, optional, or should wait for
  a fix first

## A simple decision rule

- If you only want to watch, use `status`; add `watch` for repeated polls.
- If `operator_state` is `operator-action-required`, use `inbox`.
- If `operator_state` is `autopilot-recovering`, let DeepLoop keep control.
- If you changed something, record it with `retry` or `reroute`.
- If `resume_policy` says the fix is in place or resume is optional, use
  `resume`.
- If `operator_state` is `needs-investigation`, inspect before you resume.

## Where a lesson should live

When a mission failure teaches you something new:

- put runtime and operator-surface invariants in **DeepLoop**
- put reusable methods in **general skills**
- put domain-specific evidence rules in the **substrate repo**
- put cross-repo safety and hygiene defaults in **machine-wide instructions**

Remember the foundational substrate rule:

- the project repo should stay a **minimal fact/contract substrate**
- DeepLoop-owned build code, runtime scripts, generated configs, and experiment
  implementation surfaces belong in DeepLoop-owned locations
- DeepLoop may still propose additional trusted datasets, stronger metrics, or
  new training/evaluation plans when the science requires them

Do not rely on a manual operator habit when the real fix belongs in the product.

## Learn more

- [FAQ](faq.md)
- [Runtime architecture](../concepts/architecture.md)
- [Technical reference](../reference/index.md)
