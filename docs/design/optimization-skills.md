# DeepLoop optimization skills

GPU optimization should be part of DeepLoop's reusable skill layer, not a pile
of undocumented shell guesses.

## What makes something a skill

Skills should stay **general and project-agnostic**.

Use a skill when the reusable value is the *method*:

- how to investigate
- how to triage
- how to monitor
- how to execute a bounded workflow safely

Do **not** use a skill when the real lesson is:

- a DeepLoop runtime invariant
- a product UX or observability gap
- a project-specific scientific contract

In short:

- **rules of truth and behavior** belong in DeepLoop
- **reusable methods** belong in skills
- **science and substrate contracts** belong in the substrate repo

## Inference optimizer

Inputs:

- model identifier
- task type
- resource tier
- profile registry

Outputs:

- backend choice
- context bucket
- batch probe order
- fallback ladder
- logging requirements

The inference optimizer should prefer:

- stable throughput over brittle peak speed
- explicit fallback logging on OOM
- reusable resolved profiles that can be compared across runs

## Training optimizer

Inputs:

- model size/family
- task type (SFT, LoRA, QLoRA, DPO)
- resource tier
- training preset registry

Outputs:

- precision choice
- load strategy
- optimizer choice
- gradient-checkpointing policy
- fallback ladder

For the current supported local training profile, defaults should assume:

- single GPU
- fp16 rather than bf16
- adapter tuning first for 7B-9B

## Execution operator

The execution operator is responsible for:

- resolving the chosen profile
- launching the run
- capturing peak VRAM, throughput, and crash information
- updating the manifest with actual execution details

## Critic-verifier

The critic-verifier must inspect:

- whether fallbacks were triggered
- whether stability issues bias comparisons
- whether the result is still only exploratory

Without this role, DeepLoop risks optimizing for noisy or fragile wins.
