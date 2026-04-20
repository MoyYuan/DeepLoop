# Glossary

| Term | Plain-English meaning |
| --- | --- |
| Mission | A long-running DeepLoop run with a clear goal and durable state |
| Mission state | The JSON file that records what the mission knows and plans next |
| Executor | The component that actually performs a bounded unit of work |
| Stage kernel | An executor for a specific evaluation or inference stage |
| Soft gate | A recoverable problem where DeepLoop should retry or reroute |
| Hard gate | A real safety or authority boundary that needs review |
| Operator console | The `deeploop status` surface that tells the operator what is happening and exactly what to do next |
| Operator inbox | The `deeploop inbox` surface where DeepLoop explains why it needs help |
| Lifecycle state | The mission-level state such as `running`, `blocked`, `paused`, `completed`, or `stopped` |
| Operator state | The operator-facing posture such as `autopilot-running`, `operator-action-required`, or `needs-investigation` |
| Attention level | How urgently the operator should look: passive, optional, required, investigate, or complete |
| Resume policy | Whether `resume` is not needed, optional, or should wait for a fix first |
| Sandboxed-yolo | The default autopilot mode: DeepLoop keeps control unless a true boundary opens |
| Managed | A broader-permission mode with more intervention hooks for expert operators |
| Human-directed | A step-by-step mode where the operator stays in the loop on important decisions |
| Bounded support | The current release posture: supported on the documented Linux + Python 3.11 path, not yet a claim of broad portability or full automation |
| Substrate repo | The project repo DeepLoop is currently working on |
| Contract | A machine-readable file that tells DeepLoop how a project wants to run |
| Branch | A tracked mission path created for a specific line of work |
| Ledger | The append-only record of what happened during the mission |
| Follow-up | The next action DeepLoop stages after a baseline or comparison step |

## See also

- [Mission operations](../guide/operator.md)
- [Runtime architecture](architecture.md)
- [Technical reference](../reference/index.md)
