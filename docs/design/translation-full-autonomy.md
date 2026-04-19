# translation pilot as the first full DeepLoop mission

translation pilot is both:

1. a real research project
2. the first full-system DeepLoop test
3. the first canonical **final acceptance campaign**

## Goal

DeepLoop's goal is to run the whole translation pilot lifecycle through its mission
outer runtime:

- idea and novelty framing
- literature-grounded question design
- dataset and model decisions
- baseline execution
- findings synthesis
- mechanistic follow-up
- intervention follow-up

## Immediate target

The current target is a mission-driven, ledger-backed, sandbox-aware runtime
that can coordinate the full project with minimal human intervention through the
canonical `run_mission.py` path.

translation pilot should prove that DeepLoop can own the runtime boundary. It is not
meant to become a hidden long-term fallback runtime for generic orchestration or
execution kernels.

Remaining queue runners, recursive worker loops, and end-to-end smoke harnesses
should be described as bounded proof or compatibility surfaces around that
canonical path, not as the primary runtime.

## Canonical long-run operator path

The recommended long-run translation pilot surface is now:

1. `python scripts/mission/init_mission.py --config ~/workspaces/repos/translation-pilot/.deeploop/missions/translation-long-run.yaml --force`
2. `python scripts/mission/manage_mission.py start --mission-state ~/workspaces/runs/deeploop/missions/translation-long-run-mission/mission_state.json`
3. `python scripts/mission/manage_mission.py status --mission-state ~/workspaces/runs/deeploop/missions/translation-long-run-mission/mission_state.json`
4. `python scripts/mission/manage_mission.py inbox --mission-state ~/workspaces/runs/deeploop/missions/translation-long-run-mission/mission_state.json`
5. `python scripts/mission/manage_mission.py resume --mission-state ~/workspaces/runs/deeploop/missions/translation-long-run-mission/mission_state.json`

That mission profile carries its own launcher defaults:

- `launch_env_name: llm`
- `max_iterations: 256`
- `mission_profile: translation-long-run`

and its primary baseline roster is `~/workspaces/repos/translation-pilot/.deeploop/queues/translation-long-run-baseline-queue.yaml`.

## Canonical final-exam command

DeepLoop now exposes a canonical acceptance runner for the translation pilot final
exam:

```text
python scripts/testing/run_acceptance_campaign.py --campaign translation-paper-scale
```

or:

```text
make test-acceptance
```

This is the current DeepLoop-owned acceptance bootstrap. It writes
`acceptance_review.json` / `.md` on top of the existing DeepLoop ->
translation pilot end-to-end proof artifacts and is the surface that should harden
toward a broader paper-scale final exam.

## Runtime boundary notes

- `~/workspaces/repos/translation-pilot/.deeploop/missions/translation-full.yaml`
  and `~/workspaces/repos/translation-pilot/scripts/deeploop/run_endtoend_smoke.py`
  remain bounded proof surfaces for regression coverage.
- The long-run profile stops forcing mechanistic/intervention follow-up configs
  onto `mock-entailment`; generated follow-ups now preserve the real anchor
  model backend from the winning baseline manifest.
- Adaptation now stages a substrate-owned bounded LoRA surface in
  `translation-pilot/scripts/adaptation/run_lora_adaptation.py`, with the
  generated DeepLoop config carrying the anchor model, training slice, and
  evaluation manifest needed for post-adaptation comparison.
