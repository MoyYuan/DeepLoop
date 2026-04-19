# Mission meta evaluation

DeepLoop should evaluate not only task results, but also how well the system
itself managed the mission.

## Minimum questions

- did the mission produce durable ledgers and findings?
- did role handoffs and sandbox metadata cover the full active role set?
- did DeepLoop advance from completed runs into concrete next-step artifacts?
- which parts of the lifecycle are still blocked by missing substrate runners?

## First implementation

The first implementation computes a bounded mission-level report from:

- mission state
- queue config
- manifests
- findings
- generated follow-up configs
