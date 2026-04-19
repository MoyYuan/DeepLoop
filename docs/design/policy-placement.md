# Policy placement

DeepLoop exists partly to stop future agents from scattering important rules in
the wrong place.

## The canonical placement rule

When a new lesson, rule, or workflow appears, classify it before you implement
it:

1. **If it is a universal runtime or product invariant, put it in DeepLoop.**
2. **If it is a reusable method, put it in a general skill.**
3. **If it is domain-specific, put it in the substrate repo.**
4. **If it is cross-repo safety or machine hygiene, put it in machine-wide instructions.**

The most important anti-pattern is:

- **do not use skills, prompts, or operator habit to compensate for missing
  DeepLoop product behavior**

If the lesson is really "the runtime must never behave this way again," it
belongs in DeepLoop even if an agent can currently work around it.

## Put rules in machine-wide instructions when

- they are stable across many repos
- they affect safety, reproducibility, or machine hygiene
- they should apply before a repo is even opened

Examples:

- no system Python installs
- keep large artifacts out of repos
- default workspace layout

## Put rules in DeepLoop config, code, or docs when

- they should be machine-readable or product-visible
- they are shared across research repos
- they affect autonomous execution, operator UX, evidence handling, or recovery
- the lesson is really a runtime, state, telemetry, or product-surface invariant

Examples:

- execution profiles
- resource tiers
- autonomy gates
- run-manifest schema
- blocked-entry detail propagation
- stale state cleanup after resume
- watcher/alarm fidelity
- "queued work must already be runnable or explicitly deferred"

## Put rules in repo-local or substrate-local files when

- they depend on one project's datasets, metrics, claims, or scientific artifacts
- they override shared defaults for scientific reasons
- they define readiness or comparability for one substrate rather than the
  DeepLoop runtime itself
- they describe the **minimal fact/contract substrate** DeepLoop starts from,
  not DeepLoop-owned build or orchestration logic

Examples:

- forecasting-specific metric rules
- translation-specific slice definitions
- mechanistic-evidence prerequisites for a domain-specific intervention
- project brief and benchmark/test-set facts

Do **not** put DeepLoop-owned build repo code, runtime scripts, generated
configs, or experiment implementation logic into the substrate repo just because
it is currently the active project.

## Use scripts and templates when

- the workflow is deterministic
- agents should execute it repeatedly without reinterpretation
- a named automation surface is enough and no reusable skill abstraction is needed

## Use general skills when

- the method is project-agnostic and reusable
- it is mainly about *how to investigate or execute*, not *what the product must guarantee*
- the same named workflow should work across many repos and tasks with only local inputs changed

Good skill candidates:

- bounded triage
- blocked-run recovery workflow
- log and trace investigation
- long-run monitoring summaries
- safe reroute / resume decision support

Not good skill candidates:

- repo-specific scientific readiness rules
- DeepLoop runtime invariants
- one-off project playbooks disguised as "general" skills

## Use MCP or named interfaces when

- the workflow is high-frequency and awkward without a named interface
- local tools and GitHub-native tools are not enough

Do **not** introduce MCP just because a workflow is complex. Prefer documented
scripts, configs, and product surfaces first.

## A short decision checklist for agents

Before adding a new rule, answer these questions:

1. Is this lesson about **truth/behavior**, **method**, **science**, or
   **machine hygiene**?
2. Should it apply across many repos, only inside DeepLoop, or only in one
   substrate?
3. Would failure here mean the runtime itself is wrong, or only that the
   operator lacks a reusable workflow?
4. Am I about to encode a product gap as a skill or manual habit?

If the answer to the last question is "yes," stop and move the fix deeper into
DeepLoop.

## Recent examples from the mission failures

| Lesson | Where it belongs | Why |
| --- | --- | --- |
| Defer unrunnable intervention work | DeepLoop + substrate planner contract | The queue/runtime invariant is generic, while the readiness evidence is substrate-specific |
| Surface blocked entry details in the inbox | DeepLoop | Operator truthfulness is a product surface |
| Clear stale blocker text after resume | DeepLoop | State hygiene is product behavior |
| Add bounded triage as an optional review workflow | General skill pattern + DeepLoop hook surface | The method is reusable, but the trigger/surface must be product-owned |
| Require richer mechanistic evidence before intervention | Substrate repo | This is domain/science logic, not a generic runtime rule |
| Keep machine cleanup and hygiene rules stable | Machine-wide instructions | The rule applies before any specific repo is opened |
