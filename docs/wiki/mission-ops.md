# Mission operator deep dive

The canonical operator page is [Mission operations](../guide/operator.md). Use
this companion page only when you already know the normal operator loop and want
the adjacent runtime surfaces.

## When this page is useful

Use this page when you need to answer questions like:

- Which files back the operator console?
- Where do operator requests live on disk?
- Which design notes explain why the control flow works the way it does?

## Control surfaces and artifacts

| Surface | Role |
| --- | --- |
| `scripts/mission/manage_mission.py` | Canonical operator CLI for start, status, inbox, retry, reroute, resume, logs, and stop |
| `scripts/mission/run_mission.py` | Backend mission runtime |
| `scripts/mission/monitor_mission.py` | Backend monitor used for progress reporting |
| `mission_operator_requests.jsonl` | Durable log of operator requests |
| `current_operator_request.json` | Current operator-needed blocker when a review is active |

## Related design notes

- [DeepLoop operating model](../design/operating-model.md)
- [Mission orchestrator](../design/mission-orchestrator.md)
- [State machine](../design/state-machine.md)
- [Self-healing runtime](../design/self-healing-runtime.md)
