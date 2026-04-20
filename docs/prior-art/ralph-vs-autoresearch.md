# Ralph vs AutoResearch for DeepLoop

This note records the first explicit prior-art intake for DeepLoop.

The README uses a lightweight comparison matrix for storefront positioning. This
page is the deeper support for that matrix: it is about shape, strengths, and
tradeoffs, not a leaderboard claim that DeepLoop has already outgrown every
alternative.

## Artifacts inspected

### Ralph

- `snarktank/ralph` `README.md`
- `snarktank/ralph` `ralph.sh`
- `snarktank/ralph` `prd.json.example`

### AutoResearch

- `karpathy/autoresearch` `README.md`
- `karpathy/autoresearch` `program.md`
- `karpathy/autoresearch` `train.py`

## Ralph: what it gets right

- **Fresh-context looping:** `ralph.sh` launches a new AI instance each iteration
  instead of carrying a growing context window.
- **Concrete agent-driver shell:** the loop literally shells out to `amp` or
  `claude` every iteration, so the outer loop is not inside the model context.
- **Simple external memory:** the loop persists state in git, `progress.txt`, and
  `prd.json`.
- **Explicit completion signal:** the loop exits only on a verifiable completion
  string.
- **Low orchestration cost:** the main runtime is a short Bash loop, not a large
  framework.

## Ralph: limits relative to DeepLoop

- The central object is a **PRD/user-story list**, which is excellent for
  software delivery but weaker for open-ended research.
- There is no strong notion of:
  - evidence quality
  - replication
  - claim promotion
  - benchmark contamination or metric drift
- It has no native resource-tier or GPU execution contract.
- It can optimize local task completion while missing broader scientific
  strategy.

## AutoResearch: what it gets right

- **High automation density:** the system is built for repeated overnight
  experimentation.
- **Single editable surface:** `program.md` constrains the agent to mutate only
  `train.py`, which keeps diffs understandable.
- **Metric-driven keep/discard loop:** the program records results and advances
  only when the metric improves.
- **Hardware awareness in the code:** `train.py` explicitly exposes batch size,
  model depth, and peak VRAM reporting.

Concrete examples from the inspected code:

- `program.md` defines the whole loop around `results.tsv`, branch advancement,
  crash handling, and non-stop iteration.
- `README.md` makes the operating model explicit: one agent, one editable
  surface, fixed 5-minute experiments, and explicit human-authored `program.md`
  instructions that the agent follows recursively.
- `train.py` sets explicit knobs such as `TOTAL_BATCH_SIZE`, `DEPTH`, and
  `DEVICE_BATCH_SIZE`, and prints `peak_vram_mb`.

## AutoResearch: limits relative to DeepLoop

- The loop is fundamentally **single-task and single-metric**.
- It optimizes for local hill climbing, not for a multi-repo research program.
- It assumes a narrow experiment interface rather than literature review,
  hypothesis branching, or final report synthesis.
- It has little built-in support for evidence states beyond “keep/discard/crash”.

## DeepLoop design implications

Borrow from Ralph:

- fresh-context loop boundaries
- an external CLI-driven iteration loop that does not depend on one giant
  ever-growing prompt
- cheap external memory
- explicit completion / transition conditions

Borrow from AutoResearch:

- hard manifests for each run
- measurable keep/discard criteria
- explicit crash handling
- explicit forever-loop semantics with branch advancement and result logging
- resource- and memory-aware optimization signals

Extend beyond both:

- support **three operator modes**: sandboxed-yolo, managed, and human-directed
- add explicit autonomy gates
- add resource tiers and execution profiles
- add evidence promotion from exploratory to replicated to paper-candidate
- treat the research system itself as measurable

## Bottom line

Ralph gives DeepLoop a strong **iteration primitive**.

AutoResearch gives DeepLoop a strong **experiment primitive**.

DeepLoop should combine those strengths while adding:

- scientific evidence discipline
- cross-repo policy placement
- GPU optimization contracts
- role decomposition
- reporting and release readiness

## Additional design update after upstream review

DeepLoop must not stop at "mission orchestration plus bounded kernels". The real
missing layer was a **recursive agent-driver runtime** that:

- shells out to a Copilot-compatible CLI command each iteration
- keeps memory outside the model context
- requires a machine-readable next-step result
- can hand the next role/task from one fresh-context call to the next

That layer is now a first-class design requirement, not an optional future extra.
