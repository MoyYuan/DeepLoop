PYTHON ?= python3
MISSION ?=
QUEUE ?=
MISSION_STATE ?=

.PHONY: setup repo-check test test-unit test-integration public-bootstrap-preflight public-bootstrap-check test-smoke test-real test-proof-matrix test-acceptance smoke-manifest lint docs-build docs-serve mission-smoke sanity-gate-smoke record-finding autoexec-smoke mission-advance mission-run mission-meta-eval mission-package mission-release-review mission-release-promote mission-monitor mission-agent-loop
SANITY_CONFIG ?=
SANITY_ARTIFACT ?= research-artifact
LAUNCH_METADATA ?=
PACKAGE_MANIFEST ?=
RELEASE_APPROVALS ?=

setup:
	@PYTHONPATH=src $(PYTHON) -c 'from deeploop.core.paths import EXPECTED_EXTERNAL_DIRS; [path.mkdir(parents=True, exist_ok=True) for path in EXPECTED_EXTERNAL_DIRS]'
	@echo "deeploop scaffold ready"
	@echo "Create env with: conda env create -n deeploop -f environment.yml"
	@echo "Create local inference env with: conda env create -n llm -f environment.llm.yml"

repo-check:
	@$(PYTHON) scripts/repo_check.py

test:
	@$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -q

test-unit:
	@$(PYTHON) scripts/testing/run_test_tier.py --tier unit

test-integration:
	@$(PYTHON) scripts/testing/run_test_tier.py --tier integration

public-bootstrap-check:
	@$(MAKE) setup
	@$(MAKE) public-bootstrap-preflight
	@$(MAKE) repo-check
	@$(PYTHON) -m unittest tests.test_project_contract tests.test_project_runner tests.test_public_bootstrap -q

public-bootstrap-preflight:
	@$(PYTHON) scripts/public_bootstrap_preflight.py

test-smoke:
	@$(PYTHON) scripts/testing/run_test_tier.py --tier smoke

test-real:
	@$(PYTHON) scripts/testing/run_test_tier.py --tier real

test-proof-matrix:
	@$(PYTHON) scripts/testing/run_plain_folder_proof_matrix.py

test-acceptance:
	@$(PYTHON) scripts/testing/run_acceptance_campaign.py --campaign translation-paper-scale

smoke-manifest:
	@$(PYTHON) scripts/smoke_manifest.py

docs-build:
	@$(PYTHON) -m mkdocs build --strict

docs-serve:
	@$(PYTHON) -m mkdocs serve

mission-smoke:
	@test -n "$(MISSION)" || (echo "Usage: make mission-smoke MISSION=..." && exit 1)
	@$(PYTHON) scripts/mission/init_mission.py --config $(MISSION) --force

sanity-gate-smoke:
	@test -n "$(SANITY_CONFIG)" || (echo "Usage: make sanity-gate-smoke SANITY_CONFIG=... MISSION_STATE=..." && exit 1)
	@test -n "$(MISSION_STATE)" || (echo "Usage: make sanity-gate-smoke SANITY_CONFIG=... MISSION_STATE=..." && exit 1)
	@$(PYTHON) scripts/runtime/run_sanity_gate.py --config $(SANITY_CONFIG) --mission-state $(MISSION_STATE) --artifact-name $(SANITY_ARTIFACT)

record-finding:
	@test -n "$(MISSION_STATE)" || (echo "Usage: make record-finding MISSION_STATE=... SUMMARY='...'" && exit 1)
	@test -n "$(SUMMARY)" || (echo "Usage: make record-finding MISSION_STATE=... SUMMARY='...'" && exit 1)
	@$(PYTHON) scripts/mission/record_finding.py --mission-state $(MISSION_STATE) --summary "$(SUMMARY)"

autoexec-smoke:
	@test -n "$(QUEUE)" || (echo "Usage: make autoexec-smoke QUEUE=..." && exit 1)
	@$(PYTHON) scripts/runtime/run_queue.py --config $(QUEUE)

mission-advance:
	@test -n "$(MISSION_STATE)" || (echo "Usage: make mission-advance MISSION_STATE=..." && exit 1)
	@echo "mission-advance is a compatibility alias for the supported mission-run surface."
	@$(PYTHON) scripts/mission/run_mission.py --mission-state $(MISSION_STATE)

mission-run:
	@test -n "$(MISSION_STATE)" || (echo "Usage: make mission-run MISSION_STATE=..." && exit 1)
	@$(PYTHON) scripts/mission/run_mission.py --mission-state $(MISSION_STATE)

mission-meta-eval:
	@test -n "$(MISSION_STATE)" || (echo "Usage: make mission-meta-eval MISSION_STATE=..." && exit 1)
	@echo "mission-meta-eval is a compatibility alias for the supported mission-package surface."
	@$(PYTHON) scripts/mission/package_mission.py --mission-state $(MISSION_STATE)

mission-package:
	@test -n "$(MISSION_STATE)" || (echo "Usage: make mission-package MISSION_STATE=..." && exit 1)
	@$(PYTHON) scripts/mission/package_mission.py --mission-state $(MISSION_STATE)

mission-release-review:
	@$(PYTHON) scripts/release/review_release_candidate.py --package-manifest $(PACKAGE_MANIFEST) $(if $(RELEASE_APPROVALS),--approvals $(RELEASE_APPROVALS),)

mission-release-promote:
	@$(PYTHON) scripts/release/review_release_candidate.py --package-manifest $(PACKAGE_MANIFEST) $(if $(RELEASE_APPROVALS),--approvals $(RELEASE_APPROVALS),) --promote

mission-monitor:
	@test -n "$(MISSION_STATE)" || (echo "Usage: make mission-monitor MISSION_STATE=... LAUNCH_METADATA=..." && exit 1)
	@test -n "$(LAUNCH_METADATA)" || (echo "Usage: make mission-monitor MISSION_STATE=... LAUNCH_METADATA=..." && exit 1)
	@$(PYTHON) scripts/mission/monitor_mission.py --mission-state $(MISSION_STATE) --launch-metadata $(LAUNCH_METADATA)

mission-agent-loop:
	@test -n "$(CONFIG)" || (echo "Usage: make mission-agent-loop CONFIG=..." && exit 1)
	@$(PYTHON) scripts/mission/run_recursive_agent_loop.py --config $(CONFIG)

lint:
	@echo "No repo-wide linter is enforced yet; add one only with documented policy."
