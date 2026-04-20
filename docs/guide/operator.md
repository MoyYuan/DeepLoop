# Mission operations

Use this page when you are deciding what to run next while a mission is
starting, running, blocked, or ready to continue through the installed
`deeploop` operator CLI.

Keep one contract in mind while you operate: the project folder is a minimal fact/contract substrate. DeepLoop owns generated configs, build repo code, and runtime behavior outside that substrate, and it may still propose additional trusted datasets when the science requires them.

## Your first 10 minutes

1. If you just ran `deeploop-init-mission`, start the mission with
   `deeploop start --mission-state <mission-state.json>`.
2. Run `deeploop status --mission-state <mission-state.json>` right after it so
   you can see whether DeepLoop is still driving or needs you.
3. If `status` says DeepLoop is still in control, keep checking `status`; add
   `deeploop watch --mission-state <mission-state.json>` only if you want
   repeated updates.
4. If `status` says action is required, open
   `deeploop inbox --mission-state <mission-state.json>` and make the smallest
   safe fix.
5. In managed mode, use `triage` first when `status` points you to an available
   intervention hook.
6. If `status` or `inbox` says managed mode already staged the next bounded
   recovery step, you can usually inspect briefly and go straight to `resume`.
7. If you changed the plan yourself, record that with `retry` or `reroute`.
8. Run `deeploop resume --mission-state <mission-state.json>` when the fix is
   in place or `status` says resume is optional.

If you got here from `deeploop-run-project` after an operator stop, skip the
`start` step and go straight to `status` or `inbox` with the returned
`<mission-state.json>`.

You do not need to memorize every state label before your first run. The
important questions are:

- what should I run next?
- what should I expect next?
- when do I need to intervene?

This page answers those questions first, then gives the exact labels deeper
down.

## Commands operators actually use

| Command | Use it when |
| --- | --- |
| `start` | Launch the detached mission runtime |
| `status` | See whether DeepLoop is still driving, whether it needs you, and what command to run next |
| `inbox` | Read the current operator request and the recommended fix |
| `resume` | Continue after a stop, block, or completed operator fix |
| `logs` | Inspect the detached process log tail when `status` is not enough |
| `decisions` | Inspect recent mission decisions without reading raw JSONL |
| `watch` | Poll for fresh watch/alarm lines during monitoring |
| `retry` / `reroute` | Record the operator change before `resume` |
| `triage` | Run the bounded managed-mode triage hook when intervention hooks are enabled |
| `stop` | Stop the detached mission process |

Most operators live on these four commands:

```text
deeploop start --mission-state <mission-state.json>
deeploop status --mission-state <mission-state.json>
deeploop inbox --mission-state <mission-state.json>
deeploop resume --mission-state <mission-state.json>
```

## What to expect next

| After you run... | What you should expect | What to do next |
| --- | --- | --- |
| `start` | A detached mission process launches | Run `status` |
| `status` with `autopilot-running` | DeepLoop still owns the next step | Keep watching with `status` or `watch` |
| `status` with `autopilot-recovering` | DeepLoop hit a soft problem and is already retrying, rerouting, or downscoping | Usually wait and check `status` again |
| `status` with `operator-action-required` | DeepLoop opened an operator request with a concrete blocker | Run `inbox` |
| `inbox` | A recommendation, missing dependency, or decision that needs your input | Make the fix, then use `retry` / `reroute` if needed |
| `status` with `autopilot-ready-to-resume` | The last run stopped after a bounded recovery path | Inspect briefly, then `resume` when you want another pass |
| `status` with `needs-investigation` | Something ended unexpectedly or blocked without a clean operator handoff | Inspect `logs` and `decisions` before `resume` |
| `resume` | DeepLoop takes another bounded pass with the updated state | Go back to `status` |

## A simple decision rule

- If you only want to watch, use `status`; add `watch` for repeated polls.
- If `operator_state` is `operator-action-required`, use `inbox`.
- If `operator_state` is `autopilot-recovering`, let DeepLoop keep control.
- If you changed something, record it with `retry` or `reroute`.
- If `resume_policy` says the fix is in place or resume is optional, use
  `resume`.
- If `operator_state` is `needs-investigation`, inspect before you resume.

## What `status` is telling you

`status` surfaces both mission progress and operator posture. Use the decision
rule above first; use this section when you want the precise label meanings.

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

## New bounded recovery signals

Recent operator surfaces now show a little more structure before you decide what
to do:

- `adaptation_metric_ratchet` summarizes a measurable keep/discard/route result
  when a bounded adaptation run produced one.
- If your mission opted into a narrow deterministic route, `status` usually
  pairs that ratchet with `last_reroute` so you can see why DeepLoop moved
  without digging through config
- `temporary_gap_auto_recovered` and `temporary_gap_escalated` show whether
  DeepLoop already absorbed a recoverable issue or still had to escalate it.
- `temporary_gap_categories` tells you what kind of product-gap work is
  recurring.
- In managed mode, the inbox may say DeepLoop already staged the next bounded
  recovery step after a soft gate or blocked queue triage. When that happens,
  review briefly, then `resume` unless you want to override the staged path.

## If the same fix keeps repeating

Do not rely on a manual operator habit when the real fix belongs in the
product. If a lesson should change DeepLoop itself, move it into the product or
its contributor-facing documentation instead of treating it as a permanent
operator workaround.

## Learn more

- [FAQ](faq.md)
- [Runtime architecture](../concepts/architecture.md)
- [Technical reference](../reference/index.md)

Repo-level `python scripts/mission/manage_mission.py ...` remains available as a
fallback surface for debugging and automation, but `deeploop` is the preferred
operator path for a first run.
