import json
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
PROOF_FIXTURE_ROOT = REPO_ROOT / "tests" / "_proof_fixtures" / "plain_folder" / "translation-budget-ladder"
PUBLIC_EXAMPLE_ROOT = REPO_ROOT / "examples" / "translation-budget-ladder"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from deeploop.core.paths import CHECKPOINT_DIR, DATA_DIR, RUNS_DIR, SCRATCH_DIR
from deeploop.runtime.stage_kernels import get_stage_registry, load_stage_registry_contract


class RepoContractTests(unittest.TestCase):
    def test_external_paths_are_outside_repo(self) -> None:
        for path in (DATA_DIR, CHECKPOINT_DIR, RUNS_DIR, SCRATCH_DIR):
            self.assertIn("deeploop", str(path))
            self.assertNotIn(REPO_ROOT, path.parents)

    def test_repo_does_not_assume_fixed_substrate_repos(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/smoke_manifest.py"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        manifest = json.loads((RUNS_DIR / "scaffold_smoke_manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("substrate_repos", manifest)

    def test_readme_mentions_operator_modes(self) -> None:
        readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
        self.assertIn("human-directed", readme_text)
        self.assertIn("sandboxed-yolo", readme_text)
        self.assertIn("managed", readme_text)
        self.assertIn("operator inbox", readme_text)
        self.assertIn("substrate", readme_text)
        self.assertIn("ownsbehavior", readme_text.replace("*", "").replace(" ", ""))
        self.assertIn("runtime telemetry", readme_text)
        self.assertIn("inner-loop progress", readme_text)
        self.assertIn("skills for reusable methods", readme_text)
        self.assertIn("public alpha", readme_text)
        self.assertIn("fully automatic", readme_text)
        self.assertIn("multi-substrate", readme_text)
        self.assertIn("autonomy governance", readme_text)
        self.assertIn("public-bootstrap-check", readme_text)
        self.assertIn("linux with python 3.11", readme_text)
        self.assertNotIn("assumes these substrate repos exist", readme_text)

    def test_public_trust_surfaces_exist(self) -> None:
        security_doc = REPO_ROOT / "SECURITY.md"
        conduct_doc = REPO_ROOT / "CODE_OF_CONDUCT.md"
        changelog_doc = REPO_ROOT / "CHANGELOG.md"
        self.assertTrue(security_doc.exists(), f"missing security doc: {security_doc}")
        self.assertTrue(conduct_doc.exists(), f"missing conduct doc: {conduct_doc}")
        self.assertTrue(changelog_doc.exists(), f"missing changelog: {changelog_doc}")
        security_text = security_doc.read_text(encoding="utf-8").lower()
        conduct_text = conduct_doc.read_text(encoding="utf-8").lower()
        changelog_text = changelog_doc.read_text(encoding="utf-8").lower()
        self.assertIn("public github issues", security_text)
        self.assertIn("supported scope", security_text)
        self.assertIn("respectful", conduct_text)
        self.assertIn("unacceptable behavior", conduct_text)
        self.assertIn("0.1.0", changelog_text)
        self.assertIn("public alpha", changelog_text)

    def test_release_governance_surfaces_classify_boundaries(self) -> None:
        governance_doc = REPO_ROOT / "docs" / "release" / "autonomy-governance.md"
        governance_cfg = REPO_ROOT / "configs" / "autonomy" / "operator-boundaries.yaml"
        self.assertTrue(governance_doc.exists(), f"missing governance doc: {governance_doc}")
        self.assertTrue(governance_cfg.exists(), f"missing governance config: {governance_cfg}")
        governance_text = governance_doc.read_text(encoding="utf-8").lower()
        self.assertIn("hard-gate", governance_text)
        self.assertIn("authority-boundary", governance_text)
        self.assertIn("operator-review", governance_text)
        self.assertIn("unrecoverable-failure", governance_text)
        self.assertIn("temporary deeploop product gap", governance_text)
        self.assertIn("temporary substrate gap", governance_text)
        self.assertIn("provenance-review", governance_text)
        self.assertIn("licensing-review", governance_text)
        self.assertIn("release-operator", governance_text)
        config = yaml.safe_load(governance_cfg.read_text(encoding="utf-8"))
        self.assertIn("operator_request_classes", config)
        self.assertIn("hard-gate", config["operator_request_classes"])
        self.assertIn("authority-boundary", config["operator_request_classes"])
        self.assertIn("operator-review", config["operator_request_classes"])
        self.assertIn("unrecoverable-failure", config["operator_request_classes"])
        self.assertIn("release_governance", config)
        self.assertIn("required_approvals", config["release_governance"])

    def test_policy_placement_doc_mentions_taxonomy_and_antipattern(self) -> None:
        policy_text = (REPO_ROOT / "docs" / "design" / "policy-placement.md").read_text(encoding="utf-8").lower()
        self.assertIn("canonical placement rule", policy_text)
        self.assertIn("universal runtime or product invariant", policy_text)
        self.assertIn("reusable method", policy_text)
        self.assertIn("domain-specific", policy_text)
        self.assertIn("machine-wide instructions", policy_text)
        self.assertIn("do not use skills", policy_text)

    def test_testing_strategy_surfaces_and_targets_exist(self) -> None:
        testing_doc = REPO_ROOT / "docs" / "reference" / "testing-strategy.md"
        acceptance_doc = REPO_ROOT / "docs" / "reference" / "acceptance-campaign.md"
        acceptance_runner = REPO_ROOT / "scripts" / "testing" / "run_acceptance_campaign.py"
        project_runner = REPO_ROOT / "scripts" / "mission" / "run_project.py"
        bootstrap_preflight = REPO_ROOT / "scripts" / "public_bootstrap_preflight.py"
        self.assertTrue(testing_doc.exists(), f"missing testing strategy doc: {testing_doc}")
        self.assertTrue(acceptance_doc.exists(), f"missing acceptance campaign doc: {acceptance_doc}")
        self.assertTrue(acceptance_runner.exists(), f"missing acceptance runner: {acceptance_runner}")
        self.assertTrue(project_runner.exists(), f"missing project runner: {project_runner}")
        self.assertTrue(bootstrap_preflight.exists(), f"missing bootstrap preflight: {bootstrap_preflight}")
        testing_text = testing_doc.read_text(encoding="utf-8").lower()
        acceptance_text = acceptance_doc.read_text(encoding="utf-8").lower()
        self.assertIn("four-tier", testing_text)
        self.assertIn("make test-unit", testing_text)
        self.assertIn("make test-integration", testing_text)
        self.assertIn("make test-smoke", testing_text)
        self.assertIn("make test-real", testing_text)
        self.assertIn("proof_matrix_review.json", testing_text)
        self.assertIn("make test-acceptance", testing_text)
        self.assertIn("translation-paper-scale", acceptance_text)
        self.assertIn("acceptance_review.json", acceptance_text)

        makefile_text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("test-unit:", makefile_text)
        self.assertIn("test-integration:", makefile_text)
        self.assertIn("test-smoke:", makefile_text)
        self.assertIn("test-real:", makefile_text)
        self.assertIn("test-proof-matrix:", makefile_text)
        self.assertIn("public-bootstrap-preflight:", makefile_text)
        self.assertIn("test-acceptance:", makefile_text)

    def test_release_docs_expose_public_posture_and_roadmap(self) -> None:
        release_readme = REPO_ROOT / "docs" / "release" / "README.md"
        roadmap_doc = REPO_ROOT / "docs" / "release" / "public-autonomy-roadmap.md"
        foundations_doc = REPO_ROOT / "docs" / "release" / "public-alpha-foundations.md"
        bootstrap_doc = REPO_ROOT / "docs" / "release" / "portable-bootstrap.md"
        multisubstrate_doc = REPO_ROOT / "docs" / "release" / "multi-substrate-proof.md"
        release_maintenance_doc = REPO_ROOT / "docs" / "release" / "release-maintenance.md"
        autonomy_doc = REPO_ROOT / "docs" / "design" / "autonomy-boundary-reduction.md"
        release_design = REPO_ROOT / "docs" / "design" / "release-automation.md"
        examples_doc = REPO_ROOT / "docs" / "how-to" / "examples.md"
        starter_doc = REPO_ROOT / "docs" / "how-to" / "plain-folder-starter.md"
        contributor_doc = REPO_ROOT / "docs" / "contributors" / "index.md"
        mkdocs_config = REPO_ROOT / "mkdocs.yml"

        self.assertTrue(release_readme.exists(), f"missing release README: {release_readme}")
        self.assertTrue(roadmap_doc.exists(), f"missing public roadmap doc: {roadmap_doc}")
        self.assertTrue(foundations_doc.exists(), f"missing foundations doc: {foundations_doc}")
        self.assertTrue(bootstrap_doc.exists(), f"missing bootstrap doc: {bootstrap_doc}")
        self.assertTrue(multisubstrate_doc.exists(), f"missing multi-substrate doc: {multisubstrate_doc}")
        self.assertTrue(release_maintenance_doc.exists(), f"missing release maintenance doc: {release_maintenance_doc}")
        self.assertTrue(autonomy_doc.exists(), f"missing autonomy doc: {autonomy_doc}")
        self.assertTrue(examples_doc.exists(), f"missing examples doc: {examples_doc}")
        self.assertTrue(starter_doc.exists(), f"missing plain-folder starter doc: {starter_doc}")
        self.assertTrue(contributor_doc.exists(), f"missing contributor doc: {contributor_doc}")

        release_text = release_readme.read_text(encoding="utf-8").lower()
        roadmap_text = roadmap_doc.read_text(encoding="utf-8").lower()
        foundations_text = foundations_doc.read_text(encoding="utf-8").lower()
        bootstrap_text = bootstrap_doc.read_text(encoding="utf-8").lower()
        multisubstrate_text = multisubstrate_doc.read_text(encoding="utf-8").lower()
        release_maintenance_text = release_maintenance_doc.read_text(encoding="utf-8").lower()
        autonomy_text = autonomy_doc.read_text(encoding="utf-8").lower()
        design_text = release_design.read_text(encoding="utf-8").lower()
        examples_text = examples_doc.read_text(encoding="utf-8").lower()
        starter_text = starter_doc.read_text(encoding="utf-8").lower()
        contributor_text = contributor_doc.read_text(encoding="utf-8").lower()
        mkdocs_text = mkdocs_config.read_text(encoding="utf-8").lower()

        self.assertIn("public alpha", release_text)
        self.assertIn("fully automatic", release_text)
        self.assertIn("public autonomy roadmap", release_text)
        self.assertIn("public alpha", roadmap_text)
        self.assertIn("multi-substrate", roadmap_text)
        self.assertIn("operator boundaries", roadmap_text)
        self.assertIn("non-translation", roadmap_text)
        self.assertIn("literature-gap-map", roadmap_text)
        self.assertIn("forecast-rough-notes", roadmap_text)
        self.assertIn("follow-up pr tracking", roadmap_text)
        self.assertIn("license", foundations_text)
        self.assertIn("pyproject.toml", foundations_text)
        self.assertIn("public ci", foundations_text)
        self.assertIn("supported-environment contract", bootstrap_text)
        self.assertIn("public-bootstrap-check", bootstrap_text)
        self.assertIn("public-bootstrap-preflight", bootstrap_text)
        self.assertIn("<project-folder>", bootstrap_text)
        self.assertIn("--project-root", bootstrap_text)
        self.assertIn("plain-artifacts bootstrap", bootstrap_text)
        self.assertIn("no project-local `.deeploop/` contract", bootstrap_text)
        self.assertIn("run_project.py", bootstrap_text)
        self.assertIn("--until-complete", bootstrap_text)
        self.assertIn("<mission-config.yaml>", bootstrap_text)
        self.assertIn("2-3", multisubstrate_text)
        self.assertIn("bounded-real", multisubstrate_text)
        self.assertIn("proof_matrix_review.json", multisubstrate_text)
        self.assertIn("0.x", release_maintenance_text)
        self.assertIn("changelog", release_maintenance_text)
        self.assertIn("public-bootstrap-check", release_maintenance_text)
        self.assertIn("docker-release-validate", release_maintenance_text)
        self.assertIn("docker clean-room", release_text)
        self.assertIn("safety boundary", autonomy_text)
        self.assertIn("product gap", autonomy_text)
        self.assertIn("scope boundary", design_text)
        self.assertIn("public-release story", design_text)
        self.assertIn("examples/translation-budget-ladder", examples_text)
        self.assertIn("proof-case.yaml", examples_text)
        self.assertIn("translation-budget-ladder", starter_text)
        self.assertIn("examples/translation-budget-ladder", starter_text)
        self.assertIn("public-bootstrap-check", starter_text)
        self.assertIn("contributors and developers", contributor_text)
        self.assertIn("design notes", contributor_text)
        self.assertIn("deep dives", contributor_text)
        self.assertIn("how-to/examples.md", mkdocs_text)
        self.assertIn("how-to/plain-folder-starter.md", mkdocs_text)
        self.assertIn("contributors/index.md", mkdocs_text)
        self.assertIn("release/public-autonomy-roadmap.md", mkdocs_text)
        self.assertIn("release/public-alpha-foundations.md", mkdocs_text)
        self.assertIn("release/portable-bootstrap.md", mkdocs_text)
        self.assertIn("release/release-maintenance.md", mkdocs_text)
        self.assertIn("release/multi-substrate-proof.md", mkdocs_text)
        self.assertIn("design/autonomy-boundary-reduction.md", mkdocs_text)

    def test_substrate_boundary_contract_exists(self) -> None:
        boundary_doc = REPO_ROOT / "docs" / "design" / "substrate-boundary.md"
        boundary_config = REPO_ROOT / "configs" / "runtime" / "substrate-boundary.yaml"
        self.assertTrue(boundary_doc.exists(), f"missing boundary doc: {boundary_doc}")
        self.assertTrue(boundary_config.exists(), f"missing boundary config: {boundary_config}")

        boundary_text = boundary_doc.read_text(encoding="utf-8").lower()
        config = yaml.safe_load(boundary_config.read_text(encoding="utf-8"))
        self.assertIn("minimal fact/contract", boundary_text)
        self.assertIn("build-surface rule", boundary_text)
        self.assertIn("additional trusted datasets", boundary_text)
        self.assertIn("build repo code", boundary_text)
        self.assertIn("allowed_surface_classes", config)
        self.assertIn("forbidden_substrate_entrypoint_terms", config)
        self.assertIn("forbidden_substrate_config_terms", config)
        self.assertIn("minimal_project_repo_surfaces", config)
        self.assertIn("deeploop_scientific_freedom", config)
        self.assertIn("migration-shim", config["allowed_surface_classes"])
        self.assertTrue(any("build repo code" in item for item in config["ownership"]["deeploop"]))
        self.assertTrue(any("brief" in item for item in config["minimal_project_repo_surfaces"]))
        self.assertTrue(any("datasets" in item for item in config["deeploop_scientific_freedom"]))

    def test_rule_surfaces_repeat_minimal_substrate_and_build_ownership(self) -> None:
        operating_model_text = (REPO_ROOT / "docs" / "design" / "operating-model.md").read_text(encoding="utf-8").lower()
        placement_text = (REPO_ROOT / "docs" / "design" / "policy-placement.md").read_text(encoding="utf-8").lower()
        operator_text = (REPO_ROOT / "docs" / "guide" / "operator.md").read_text(encoding="utf-8").lower()
        multisubstrate_text = (REPO_ROOT / "docs" / "release" / "multi-substrate-proof.md").read_text(encoding="utf-8").lower()

        self.assertIn("minimal fact/contract substrate", operating_model_text)
        self.assertIn("build repo code", operating_model_text)
        self.assertIn("additional trusted datasets", operating_model_text)
        self.assertIn("minimal fact/contract substrate", placement_text)
        self.assertIn("build repo code", placement_text)
        self.assertIn("minimal fact/contract substrate", operator_text)
        self.assertIn("generated configs", operator_text)
        self.assertIn("additional trusted datasets", operator_text)
        self.assertIn("minimal facts and contracts", multisubstrate_text)
        self.assertIn("build code", multisubstrate_text)

    def test_stage_kernel_registry_contract_matches_code(self) -> None:
        contract = load_stage_registry_contract()
        self.assertEqual(
            {entry["id"] for entry in contract["stages"]},
            set(get_stage_registry()),
        )
        self.assertEqual(contract["version"], 1)
        readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
        self.assertIn("stage-kernel", readme_text)

    def test_repo_check_script_succeeds(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/repo_check.py"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_provider_setup_contract_surfaces_exist(self) -> None:
        provider_doc = REPO_ROOT / "docs" / "reference" / "provider-setup.md"
        provider_config = REPO_ROOT / "configs" / "runtime" / "provider-setup-registry.yaml"
        self.assertTrue(provider_doc.exists(), f"missing provider setup doc: {provider_doc}")
        self.assertTrue(provider_config.exists(), f"missing provider setup config: {provider_config}")

        provider_text = provider_doc.read_text(encoding="utf-8").lower()
        self.assertIn("machine-level provider setup", provider_text)
        self.assertIn("mission/runtime provider-model selection", provider_text)
        self.assertIn("copilot cli", provider_text)
        self.assertIn("openai-compatible api providers", provider_text)
        self.assertIn("anthropic api providers", provider_text)
        self.assertIn("local-transformers", provider_text)
        self.assertIn("vllm", provider_text)
        self.assertIn("configs/runtime/provider-setup-registry.yaml", provider_text)
        self.assertIn("configs/runtime/provider-selection-registry.yaml", provider_text)
        self.assertIn("keep secrets out of repo config", provider_text)

        config = yaml.safe_load(provider_config.read_text(encoding="utf-8"))
        self.assertEqual(config["version"], 1)
        self.assertEqual(config["scope"]["layer"], "machine-level-provider-availability")
        self.assertIn("mission/runtime provider-model selection", config["scope"]["excludes"])
        self.assertEqual(
            config["related_runtime_surfaces"]["mission_runtime_selection"],
            "configs/runtime/provider-selection-registry.yaml",
        )
        self.assertEqual(
            set(config["first_class_provider_families"]),
            {
                "copilot-cli",
                "openai-compatible-api",
                "anthropic-api",
                "local-transformers",
                "vllm",
            },
        )
        self.assertEqual(set(config["provider_families"]), set(config["first_class_provider_families"]))
        self.assertEqual(config["provider_families"]["copilot-cli"]["runtime_integration"], "implemented")
        self.assertEqual(config["provider_families"]["openai-compatible-api"]["runtime_integration"], "implemented")
        self.assertEqual(config["provider_families"]["anthropic-api"]["runtime_integration"], "deferred")
        self.assertIn(
            "HUGGING_FACE_HUB_TOKEN",
            config["provider_families"]["local-transformers"]["expected_env_vars"]["optional"],
        )
        self.assertIn(
            "CUDA_VISIBLE_DEVICES",
            config["provider_families"]["vllm"]["expected_env_vars"]["optional"],
        )

        readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
        getting_started_text = (REPO_ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8").lower()
        bootstrap_text = (REPO_ROOT / "docs" / "release" / "portable-bootstrap.md").read_text(encoding="utf-8").lower()
        reference_index_text = (REPO_ROOT / "docs" / "reference" / "index.md").read_text(encoding="utf-8").lower()
        docs_home_text = (REPO_ROOT / "docs" / "index.md").read_text(encoding="utf-8").lower()
        mkdocs_text = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8").lower()
        self.assertIn("docs/reference/provider-setup.md", readme_text)
        self.assertIn("reference/provider-setup.md", getting_started_text)
        self.assertIn("reference/provider-selection.md", getting_started_text)
        self.assertIn("../reference/provider-setup.md", bootstrap_text)
        self.assertIn("../reference/provider-selection.md", bootstrap_text)
        self.assertIn("provider setup", reference_index_text)
        self.assertIn("reference/provider-setup.md", docs_home_text)
        self.assertIn("reference/provider-selection.md", docs_home_text)
        self.assertIn("reference/provider-setup.md", mkdocs_text)
        self.assertIn("reference/provider-selection.md", mkdocs_text)

    def test_provider_selection_contract_surfaces_exist(self) -> None:
        selection_doc = REPO_ROOT / "docs" / "reference" / "provider-selection.md"
        selection_config = REPO_ROOT / "configs" / "runtime" / "provider-selection-registry.yaml"
        self.assertTrue(selection_doc.exists(), f"missing provider selection doc: {selection_doc}")
        self.assertTrue(selection_config.exists(), f"missing provider selection config: {selection_config}")

        selection_text = selection_doc.read_text(encoding="utf-8").lower()
        self.assertIn("mission/runtime provider", selection_text)
        self.assertIn("machine-level provider setup", selection_text)
        self.assertIn("configs/runtime/provider-selection-registry.yaml", selection_text)
        self.assertIn("configs/runtime/backend-policy.yaml", selection_text)
        self.assertIn("configs/runtime/recursive-agent-runtime-provider.example.yaml", selection_text)
        self.assertIn("configs/sandbox/agent-launch-policy.yaml", selection_text)
        self.assertIn("configs/manifests/run-manifest-template.json", selection_text)
        self.assertIn("keep secrets out of repo config", selection_text)
        self.assertIn("copilot cli", selection_text)
        self.assertIn("openai-compatible api providers", selection_text)
        self.assertIn("anthropic api providers", selection_text)
        self.assertIn("local-transformers", selection_text)
        self.assertIn("vllm", selection_text)

        config = yaml.safe_load(selection_config.read_text(encoding="utf-8"))
        self.assertEqual(config["version"], 1)
        self.assertEqual(config["scope"]["layer"], "mission-runtime-provider-selection")
        self.assertEqual(
            set(config["first_class_provider_families"]),
            {
                "copilot-cli",
                "openai-compatible-api",
                "anthropic-api",
                "local-transformers",
                "vllm",
            },
        )
        self.assertEqual(config["selection_profiles"]["control-plane-copilot-cli"]["backend"], "copilot-cli")
        self.assertEqual(
            config["selection_profiles"]["local-transformers-execution"]["backend"],
            "local-transformers",
        )
        self.assertEqual(config["selection_profiles"]["vllm-execution"]["backend"], "vllm")
        self.assertEqual(
            config["selection_profiles"]["openai-compatible-api-control-plane"]["status"],
            "implemented",
        )
        self.assertEqual(
            config["selection_profiles"]["anthropic-api-control-plane"]["status"],
            "reserved-runtime-adapter",
        )
        self.assertEqual(
            config["related_runtime_surfaces"]["provider_setup_registry"],
            "configs/runtime/provider-setup-registry.yaml",
        )
        self.assertEqual(
            config["related_runtime_surfaces"]["run_manifest_template"],
            "configs/manifests/run-manifest-template.json",
        )
        self.assertIn("no-cross-provider-fallback", config["fallback_profiles"])
        self.assertIn("local-inference-backend-ladder", config["fallback_profiles"])

        readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
        getting_started_text = (REPO_ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8").lower()
        bootstrap_text = (REPO_ROOT / "docs" / "release" / "portable-bootstrap.md").read_text(encoding="utf-8").lower()
        reference_index_text = (REPO_ROOT / "docs" / "reference" / "index.md").read_text(encoding="utf-8").lower()
        docs_home_text = (REPO_ROOT / "docs" / "index.md").read_text(encoding="utf-8").lower()
        mkdocs_text = (REPO_ROOT / "mkdocs.yml").read_text(encoding="utf-8").lower()
        recursive_runtime_text = (
            REPO_ROOT / "docs" / "design" / "recursive-agent-runtime.md"
        ).read_text(encoding="utf-8").lower()
        self.assertIn("docs/reference/provider-selection.md", readme_text)
        self.assertIn("reference/provider-selection.md", getting_started_text)
        self.assertIn("../reference/provider-selection.md", bootstrap_text)
        self.assertIn("provider selection", reference_index_text)
        self.assertIn("reference/provider-selection.md", docs_home_text)
        self.assertIn("reference/provider-selection.md", mkdocs_text)
        self.assertIn("provider_selection", recursive_runtime_text)

    def test_mission_init_script_materializes_mission_bundle(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/mission/run_project.py", "--help"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("--project-root", completed.stdout)
        self.assertIn("--until-complete", completed.stdout)

    def test_autoexecutor_queue_config_exists(self) -> None:
        queue_path = REPO_ROOT / "configs" / "runtime" / "translation-long-run-baseline-queue.yaml"
        self.assertTrue(queue_path.exists(), f"missing public example queue: {queue_path}")

    def test_tiny_autopilot_proof_assets_exist(self) -> None:
        self.assertTrue(PROOF_FIXTURE_ROOT.exists(), f"missing proof fixture: {PROOF_FIXTURE_ROOT}")
        self.assertTrue(PUBLIC_EXAMPLE_ROOT.exists(), f"missing public example: {PUBLIC_EXAMPLE_ROOT}")
        starter_doc = REPO_ROOT / "docs" / "how-to" / "plain-folder-starter.md"
        self.assertTrue(starter_doc.exists(), f"missing starter doc: {starter_doc}")
        self.assertTrue((PUBLIC_EXAMPLE_ROOT / "project-facts.yaml").exists())
        self.assertTrue((PROOF_FIXTURE_ROOT / "project-facts.yaml").exists())
        self.assertTrue((PROOF_FIXTURE_ROOT / "proof-case.yaml").exists())

    def test_public_example_surface_is_linked_from_onboarding_docs(self) -> None:
        examples_readme = REPO_ROOT / "examples" / "README.md"
        readme_text = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
        getting_started_text = (REPO_ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8").lower()
        docs_home_text = (REPO_ROOT / "docs" / "index.md").read_text(encoding="utf-8").lower()
        reference_index_text = (REPO_ROOT / "docs" / "reference" / "index.md").read_text(encoding="utf-8").lower()
        bootstrap_text = (REPO_ROOT / "docs" / "release" / "portable-bootstrap.md").read_text(encoding="utf-8").lower()
        self.assertTrue(examples_readme.exists(), f"missing examples readme: {examples_readme}")
        self.assertIn("examples/translation-budget-ladder", readme_text)
        self.assertIn("examples/translation-budget-ladder", getting_started_text)
        self.assertIn("how-to/examples.md", getting_started_text)
        self.assertIn("how-to/examples.md", docs_home_text)
        self.assertIn("../how-to/examples.md", bootstrap_text)
        self.assertIn("../how-to/examples.md", reference_index_text)

    def test_public_example_matches_translation_proof_fixture_public_files(self) -> None:
        example_files = {
            path.relative_to(PUBLIC_EXAMPLE_ROOT).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(PUBLIC_EXAMPLE_ROOT.rglob("*"))
            if path.is_file()
        }
        fixture_files = {
            path.relative_to(PROOF_FIXTURE_ROOT).as_posix(): path.read_text(encoding="utf-8")
            for path in sorted(PROOF_FIXTURE_ROOT.rglob("*"))
            if path.is_file() and path.name != "proof-case.yaml"
        }

        self.assertNotIn("proof-case.yaml", example_files)
        self.assertIn("proof-case.yaml", {path.name for path in PROOF_FIXTURE_ROOT.rglob("*") if path.is_file()})
        self.assertEqual(example_files, fixture_files)

    def test_mission_advance_and_meta_eval_scripts_run(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/testing/run_plain_folder_proof_matrix.py",
                "--list",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        case_ids = {json.loads(line)["case_id"] for line in completed.stdout.splitlines() if line.strip()}
        self.assertIn("forecast-rough-notes", case_ids)
        self.assertIn("translation-budget-ladder", case_ids)
        self.assertIn("literature-gap-map", case_ids)
        self.assertIn("replication-heavy-redteam", case_ids)

    def test_mission_package_script_runs(self) -> None:
        package = subprocess.run(
            [
                sys.executable,
                "scripts/mission/package_mission.py",
                "--help",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(package.returncode, 0, package.stdout + package.stderr)
        self.assertIn("--mission-state", package.stdout)


if __name__ == "__main__":
    unittest.main()
