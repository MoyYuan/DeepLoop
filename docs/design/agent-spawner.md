# Agent spawner and coordination runtime

This note describes the coordination boundary between mission planning and
role-specific execution.

## Current public posture

DeepLoop does not yet ship a separate always-on agent-spawner service. Today,
mission execution is driven by the mission runtime and the bounded
recursive-agent runtime. The "agent spawner" label refers to the bundle format
and coordination responsibilities those runtimes already need to honor.

## Current responsibilities

When DeepLoop delegates a mission step to a role, the coordinating runtime
should:

- generate a durable handoff bundle for that role
- attach sandbox paths, rule sources, and mission/action identifiers
- define expected outputs, result locations, and blocked/failure semantics
- record the launch plus returned artifacts in the mission ledger

These bundles keep role handoffs inspectable even when the actual executor is a
local CLI call rather than a dedicated spawner daemon.

## What is not shipped yet

- no standalone daemon that watches a queue and launches arbitrary agents
- no general multi-agent swarm scheduler
- no separate retry/escalation service beyond the bounded logic already present
  in mission runtimes

If DeepLoop grows a dedicated spawner later, it should consume the same bundle
contract rather than invent a second coordination surface.
