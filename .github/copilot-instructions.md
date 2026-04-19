# Copilot instructions for `deeploop`

- Treat this repo as a control-plane contract repo, not a benchmark or training
  repo.
- Keep checks CPU-friendly and deterministic for hosted agents.
- Do not assume access to local `~/workspaces` state in GitHub-hosted contexts.
- Prefer editing `configs/`, `schemas/`, `docs/design/`, and stable scripts over
  ad hoc prompt-only conventions.
- When introducing a new cross-repo rule, first decide whether it belongs in
  machine-wide instructions, DeepLoop config, or repo-local overrides.
- Do not add MCP dependencies unless they remove repeated friction that local
  tools and GitHub integrations cannot handle well.
- Do not add starter-model assumptions to substrate repos through DeepLoop
  without updating their repo contracts.
