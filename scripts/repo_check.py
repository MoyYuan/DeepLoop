from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import EXPECTED_EXTERNAL_DIRS, REPO_ROOT as PACKAGE_REPO_ROOT


REQUIRED_PATHS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "mkdocs.yml",
    REPO_ROOT / "AGENTS.md",
    REPO_ROOT / "Makefile",
    REPO_ROOT / "environment.yml",
    REPO_ROOT / ".github" / "copilot-instructions.md",
    REPO_ROOT / ".github" / "workflows" / "copilot-setup-steps.yml",
    REPO_ROOT / "configs" / "autonomy" / "gates.yaml",
    REPO_ROOT / "configs" / "autonomy" / "mission-outer-loop.yaml",
    REPO_ROOT / "configs" / "autonomy" / "research-sanity-gates.yaml",
    REPO_ROOT / "configs" / "autonomy" / "evidence-policy.yaml",
    REPO_ROOT / "configs" / "autonomy" / "state-machine.yaml",
    REPO_ROOT / "configs" / "execution-profiles" / "inference-families.yaml",
    REPO_ROOT / "configs" / "execution-profiles" / "training-presets.yaml",
    REPO_ROOT / "configs" / "evaluation" / "system-metrics.yaml",
    REPO_ROOT / "configs" / "ledger" / "policy.yaml",
    REPO_ROOT / "configs" / "manifests" / "run-manifest-template.json",
    REPO_ROOT / "configs" / "memory" / "registry.yaml",
    REPO_ROOT / "examples" / "templates" / "mission-config.template.yaml",
    REPO_ROOT / "configs" / "operating-model" / "modes.yaml",
    REPO_ROOT / "configs" / "platform" / "expansion.yaml",
    REPO_ROOT / "configs" / "policy" / "placement.yaml",
    REPO_ROOT / "configs" / "resource-tiers" / "tiers.yaml",
    REPO_ROOT / "configs" / "roles" / "agent-roles.yaml",
    REPO_ROOT / "configs" / "runtime" / "backend-policy.yaml",
    REPO_ROOT / "configs" / "runtime" / "artifact-package-contract.yaml",
    REPO_ROOT / "configs" / "runtime" / "provider-setup-registry.yaml",
    REPO_ROOT / "configs" / "runtime" / "provider-selection-registry.yaml",
    REPO_ROOT / "configs" / "runtime" / "release-candidate-policy.yaml",
    REPO_ROOT / "configs" / "runtime" / "self-healing-runtime.yaml",
    REPO_ROOT / "configs" / "runtime" / "stage-kernel-registry.yaml",
    REPO_ROOT / "configs" / "runtime" / "substrate-boundary.yaml",
    REPO_ROOT / "configs" / "sandbox" / "agent-launch-policy.yaml",
    REPO_ROOT / "docs" / "design" / "bounded-autoexecutor.md",
    REPO_ROOT / "docs" / "concepts" / "architecture.md",
    REPO_ROOT / "docs" / "concepts" / "glossary.md",
    REPO_ROOT / "docs" / "getting-started.md",
    REPO_ROOT / "docs" / "how-to" / "examples.md",
    REPO_ROOT / "docs" / "guide" / "faq.md",
    REPO_ROOT / "docs" / "guide" / "operator.md",
    REPO_ROOT / "docs" / "index.md",
    REPO_ROOT / "docs" / "reference" / "index.md",
    REPO_ROOT / "docs" / "reference" / "provider-setup.md",
    REPO_ROOT / "docs" / "reference" / "provider-selection.md",
    REPO_ROOT / "docs" / "reference" / "docs-maintenance.md",
    REPO_ROOT / "docs" / "prior-art" / "ralph-vs-autoresearch.md",
    REPO_ROOT / "docs" / "design" / "agent-spawner.md",
    REPO_ROOT / "docs" / "design" / "experiment-ledger.md",
    REPO_ROOT / "docs" / "design" / "mission-meta-eval.md",
    REPO_ROOT / "docs" / "design" / "operating-model.md",
    REPO_ROOT / "docs" / "design" / "optimization-skills.md",
    REPO_ROOT / "docs" / "design" / "policy-placement.md",
    REPO_ROOT / "docs" / "design" / "evidence-policy.md",
    REPO_ROOT / "docs" / "design" / "evaluation-plan.md",
    REPO_ROOT / "docs" / "design" / "memory-registry.md",
    REPO_ROOT / "docs" / "design" / "platform-expansion.md",
    REPO_ROOT / "docs" / "design" / "mission-artifact-package.md",
    REPO_ROOT / "docs" / "design" / "release-automation.md",
    REPO_ROOT / "docs" / "design" / "mission-orchestrator.md",
    REPO_ROOT / "docs" / "design" / "role-contract.md",
    REPO_ROOT / "docs" / "design" / "rollout-plan.md",
    REPO_ROOT / "docs" / "design" / "research-sanity-gates.md",
    REPO_ROOT / "docs" / "design" / "self-healing-runtime.md",
    REPO_ROOT / "docs" / "design" / "runtime-standardization.md",
    REPO_ROOT / "docs" / "design" / "sandboxed-agents.md",
    REPO_ROOT / "docs" / "design" / "stage-kernels.md",
    REPO_ROOT / "docs" / "design" / "state-machine.md",
    REPO_ROOT / "docs" / "design" / "substrate-boundary.md",
    REPO_ROOT / "schemas" / "agent-handoff.schema.json",
    REPO_ROOT / "schemas" / "ledger-entry.schema.json",
    REPO_ROOT / "schemas" / "mission-action.schema.json",
    REPO_ROOT / "schemas" / "mission-acceptance-criteria.schema.json",
    REPO_ROOT / "schemas" / "mission-artifact-package.schema.json",
    REPO_ROOT / "schemas" / "mission-branch-record.schema.json",
    REPO_ROOT / "schemas" / "mission-decision.schema.json",
    REPO_ROOT / "schemas" / "mission-meta-eval.schema.json",
    REPO_ROOT / "schemas" / "release-candidate-review.schema.json",
    REPO_ROOT / "schemas" / "research-sanity-report.schema.json",
    REPO_ROOT / "schemas" / "mission-state.schema.json",
    REPO_ROOT / "schemas" / "research-memory-entry.schema.json",
    REPO_ROOT / "schemas" / "run-manifest.schema.json",
    REPO_ROOT / "examples" / "README.md",
    REPO_ROOT / "examples" / "translation-budget-ladder" / "project-facts.yaml",
    REPO_ROOT / "examples" / "translation-budget-ladder" / "docs" / "project-brief.md",
    REPO_ROOT / "examples" / "translation-budget-ladder" / "docs" / "benchmark-and-metrics.md",
    REPO_ROOT / "examples" / "translation-budget-ladder" / "docs" / "budget-and-baselines.md",
    REPO_ROOT / "scripts" / "mission" / "init_mission.py",
    REPO_ROOT / "scripts" / "mission" / "package_mission.py",
    REPO_ROOT / "scripts" / "mission" / "record_finding.py",
    REPO_ROOT / "scripts" / "release" / "review_release_candidate.py",
    REPO_ROOT / "scripts" / "runtime" / "run_queue.py",
    REPO_ROOT / "scripts" / "runtime" / "run_sanity_gate.py",
    REPO_ROOT / "scripts" / "runtime" / "run_stage_kernel.py",
    REPO_ROOT / "src" / "deeploop" / "artifacts" / "artifact_packager.py",
    REPO_ROOT / "src" / "deeploop" / "artifacts" / "release_automation.py",
    REPO_ROOT / "src" / "deeploop" / "autonomy" / "mission_autonomy.py",
    REPO_ROOT / "src" / "deeploop" / "platform" / "contracts.py",
    REPO_ROOT / "src" / "deeploop" / "research" / "sanity_gates.py",
    REPO_ROOT / "src" / "deeploop" / "runtime" / "self_healing_runtime.py",
    REPO_ROOT / "src" / "deeploop" / "runtime" / "stage_kernels.py",
    REPO_ROOT / "scripts" / "smoke_manifest.py",
    REPO_ROOT / "tests" / "test_artifact_packager.py",
    REPO_ROOT / "tests" / "test_end_to_end_smoke.py",
    REPO_ROOT / "tests" / "test_mission_autonomy.py",
    REPO_ROOT / "tests" / "test_repo_contract.py",
    REPO_ROOT / "tests" / "test_release_automation.py",
    REPO_ROOT / "tests" / "test_self_healing_runtime.py",
    REPO_ROOT / "tests" / "test_stage_kernels.py",
]


def main() -> int:
    if PACKAGE_REPO_ROOT != REPO_ROOT:
        raise SystemExit("Package repo root does not match script repo root.")

    missing = [path for path in REQUIRED_PATHS if not path.exists()]
    if missing:
        raise SystemExit(
            "Missing required scaffold paths:\n" + "\n".join(f"- {path}" for path in missing)
        )

    for external_dir in EXPECTED_EXTERNAL_DIRS:
        external_dir.mkdir(parents=True, exist_ok=True)

    print("deeploop repo-check: scaffold contract looks valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
