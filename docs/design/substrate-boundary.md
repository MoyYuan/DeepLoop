# DeepLoop / substrate boundary

DeepLoop is the runtime and control plane. Substrate repos are **minimal
fact/contract surfaces**, not the place where DeepLoop's orchestration or build
logic should live.

This is the **minimal fact/contract** rule for project repos.

## Foundational rule

Treat a project repo as the minimum substrate needed for science, not as the
home of DeepLoop-owned execution code.

That means:

- the substrate repo may contain the project brief, benchmark/test data,
  baseline metrics, slice definitions, and scientific or safety rules
- DeepLoop should still be free to decide scientifically that it needs
  additional trusted datasets, better metrics, new evaluation slices, or new
  training plans
- those additional decisions should be made and recorded by DeepLoop, not
  blocked just because the original substrate repo started with a minimal set of
  facts

## Ownership rule

- **DeepLoop owns behavior and build surfaces**
  - mission planning and orchestration
  - critique, retry, reroute, and queue execution
  - runtime backend policy and fallback decisions
  - registered generic baseline, mechanistic, and intervention kernels
  - manifest registration and generated-artifact policy
  - build repo code, runtime scripts, generated configs, and experiment
    implementation surfaces needed to run the work
  - scientific expansion decisions such as proposing additional datasets,
    metrics, or training/evaluation plans beyond the substrate's minimal inputs
- **Substrates own minimal facts/contracts**
- benchmark and dataset facts
- project brief, hypotheses, and evaluation contracts
- baseline prompts, metrics, slice definitions, and safety/scientific rules
- the minimal seed materials DeepLoop needs to start reasoning from scratch
- any explicit transition wrappers that are inventoried and tested

## Build-surface rule

If DeepLoop needs new code or scripts to build, design, train, evaluate, or run
the project, those surfaces belong in DeepLoop-owned locations, not in the
project repo tree.

Examples of DeepLoop-owned build surfaces:

- runtime entrypoints
- generated configs
- build/eval/train helper scripts
- experiment implementation code
- mission-generated plan/code artifacts

The project repo is not supposed to become the hidden home of DeepLoop-owned
orchestration or build logic.

## Artifact rule

Generated artifacts must live in DeepLoop-controlled workspace roots such as:

- `~/.deeploop/runs/deeploop/`
- `~/workspaces/runs/<substrate>/`
- `~/workspaces/scratch/<project>/`

They do not belong in the substrate repository tree.

## Compatibility and proof-substrate rule

A proof substrate such as translation pilot is a reference workload, not a hidden
fallback runtime.

For the limited public-alpha bootstrap path, DeepLoop's core runtime does **not**
require substrate repos. Plain-folder projects bootstrap from minimal facts and
contracts alone; bounded-real proof substrates remain optional
stronger-evidence surfaces.

Some proof substrates still carry limited compatibility wrappers so earlier
experiments can be replayed or compared. Those wrappers are audited exceptions,
not the default runtime path. When they exist, they must be:

1. explicitly inventoried
2. classified as substrate fact, generic behavior, or transition wrapper
3. documented as temporary
4. checked so new substrate-local orchestration, generated-config, or
   DeepLoop-owned build behavior is flagged early

DeepLoop now exposes the kernel registry at
`configs/runtime/stage-kernel-registry.yaml` and the generic runtime entrypoint
at `scripts/runtime/run_stage_kernel.py`.

## Enforcement

- `configs/runtime/substrate-boundary.yaml` is the machine-readable contract.
- substrate repos should import that contract in repo checks.
- substrate-local entrypoints must avoid DeepLoop-reserved orchestration naming.
- substrate configs must not introduce runtime fallback-policy fields; those
  belong to DeepLoop runtime policy.
- agent/runtime prompts should repeat this boundary so DeepLoop keeps treating
  it as a foundational rule.
