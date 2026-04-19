# DeepLoop evaluation plan

DeepLoop is itself a research system, so it needs explicit evaluation criteria.

## Compare the operator modes

- **sandboxed-yolo**
- **managed**
- **human-directed**

## Core system metrics

- **useful findings rate**: how often a run produces something the critic-verifier
  judges worth keeping
- **reproducibility rate**: how often exploratory results survive replication
- **crash-free run rate**: how often the system completes runs without fatal
  errors or abandoned instability
- **time to first useful finding**: wall-clock time to the first validated result
- **human review load**: how many approvals or interventions are needed
- **final report quality**: quality of the synthesized findings package

## Why this matters

DeepLoop should not be judged only by “did it improve one metric once.” It
should be judged by whether it produces useful, reproducible research with
reasonable human oversight.

## First evaluation slice

The first practical comparison should use the two local substrate repos:

- `translation-pilot`
- `forecast-lab`

and compare:

- a bounded human-directed baseline workflow
- a bounded sandboxed-yolo manifest-driven workflow
- a managed expert-mode run once the default comparison is stable
