from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import CHECKPOINT_DIR, DATA_DIR, RUNS_DIR, SCRATCH_DIR


def main() -> int:
    for path in (DATA_DIR, CHECKPOINT_DIR, RUNS_DIR, SCRATCH_DIR):
        path.mkdir(parents=True, exist_ok=True)

    manifest = {
        "project": "deeploop",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Scaffold-only DeepLoop manifest.",
        "modes_file": str(REPO_ROOT / "configs" / "operating-model" / "modes.yaml"),
        "autonomy_gates_file": str(REPO_ROOT / "configs" / "autonomy" / "gates.yaml"),
        "evidence_policy_file": str(REPO_ROOT / "configs" / "autonomy" / "evidence-policy.yaml"),
        "state_machine_file": str(REPO_ROOT / "configs" / "autonomy" / "state-machine.yaml"),
        "inference_profiles_file": str(
            REPO_ROOT / "configs" / "execution-profiles" / "inference-families.yaml"
        ),
        "training_profiles_file": str(
            REPO_ROOT / "configs" / "execution-profiles" / "training-presets.yaml"
        ),
        "evaluation_plan_file": str(REPO_ROOT / "configs" / "evaluation" / "system-metrics.yaml"),
        "ledger_policy_file": str(REPO_ROOT / "configs" / "ledger" / "policy.yaml"),
        "runtime_backend_policy_file": str(REPO_ROOT / "configs" / "runtime" / "backend-policy.yaml"),
        "provider_setup_registry_file": str(REPO_ROOT / "configs" / "runtime" / "provider-setup-registry.yaml"),
        "runtime_provider_selection_file": str(REPO_ROOT / "configs" / "runtime" / "provider-selection-registry.yaml"),
        "sandbox_policy_file": str(REPO_ROOT / "configs" / "sandbox" / "agent-launch-policy.yaml"),
        "mission_template_file": str(REPO_ROOT / "examples" / "templates" / "mission-config.template.yaml"),
        "resource_tiers_file": str(REPO_ROOT / "configs" / "resource-tiers" / "tiers.yaml"),
        "memory_registry_file": str(REPO_ROOT / "configs" / "memory" / "registry.yaml"),
        "manifest_schema_file": str(REPO_ROOT / "schemas" / "run-manifest.schema.json"),
        "memory_schema_file": str(REPO_ROOT / "schemas" / "research-memory-entry.schema.json"),
        "mission_state_schema_file": str(REPO_ROOT / "schemas" / "mission-state.schema.json"),
        "ledger_entry_schema_file": str(REPO_ROOT / "schemas" / "ledger-entry.schema.json"),
        "agent_handoff_schema_file": str(REPO_ROOT / "schemas" / "agent-handoff.schema.json"),
    }

    manifest_path = RUNS_DIR / "scaffold_smoke_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"smoke-manifest: wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
