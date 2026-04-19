# DeepLoop state machine

DeepLoop should not “just keep looping.” It should move through explicit states
with required outputs.

## Core sequence

1. idea intake
2. literature review
3. question design
4. benchmark selection
5. experiment design
6. execution
7. critique
8. replication when warranted
9. final reporting

## Why this matters

- it separates planning from execution
- it forces critique before claim promotion
- it creates natural handoff artifacts between agent roles

## Key transition rules

- no execution without a draft manifest
- no final report without critique
- no replicated claim without follow-up evidence
- no paper-candidate promotion if autonomy gates require human review and none was given
- transition metadata in `configs/autonomy/state-machine.yaml` also records the
  default decision type plus branch/recovery status for each allowed hop
