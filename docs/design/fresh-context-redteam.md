# Fresh-Context Red-Team Loop

## Overview

The fresh-context red-team is a dedicated skeptic loop that challenges DeepLoop's current favored interpretation by re-examining mission findings from first principles without anchoring bias. It operates as a structural counterweight to confirmation bias in autonomous research systems.

### Core Design Philosophy

Rather than validating existing conclusions, the fresh-context red-team systematically asks: **"What if we're wrong?"** It does so by:

1. **Fresh Reading**: Re-reading raw data and manifests without reference to existing interpretations
2. **Alternative Explanations**: Generating plausible competing hypotheses ranked by prior plausibility
3. **Falsification Checks**: Identifying specific, operationalizable conditions that would falsify the primary claim
4. **Destructive Sanity Tests**: Applying deliberately adversarial tactics from observational epidemiology
5. **Assumption Audit**: Exposing all implicit assumptions and their dependencies
6. **Confound Surface**: Cataloging unmeasured and partially-measured confounds with effect-size implications

The red-team produces durable JSON/MD artifacts and integrates findings into the mission ledger for downstream decision-making.

---

## Architecture

### Input Surface

The red-team reads:

- **Mission findings** (from self-correction, statistical-rigor, confound-guard modules)
- **Correction outputs** (alternative interpretations, reroute recommendations, blockers)
- **Run manifests** (`run_manifest.json`, `study_manifest.json`, `findings_manifest.json`)
- **Observed measurements** (accuracy metrics, effect estimates, sample counts)

### Processing Pipeline

```
mission_artifacts 
  ↓
fresh_reading_pass
  ↓ (emit alternative_explanations + non_obvious_patterns)
destructive_sanity_checks
  ↓ (emit concerns + status)
falsification_prompt_generation
  ↓ (emit operationalized tests)
assumption_audit
  ↓ (emit assumption_dependency_graph)
confound_catalog_surface
  ↓ (emit unmeasured + partially_measured confounds)
credibility_reassessment
  ↓
report_emission + ledger_integration
```

### Output Artifacts

#### 1. JSON Report (`{artifact_name}_redteam_report.json`)

Structured report with:
- `report_id`: Unique identifier for this red-team run
- `primary_finding_summary`: What is being challenged
- `fresh_reading`: Non-obvious patterns and dismissed interpretations
- `alternative_explanations`: Array of competing hypotheses with plausibility scores
- `falsification_checks`: Operationalized conditions that would falsify primary claim
- `destructive_sanity_checks`: Adversarial test results and concerns
- `assumption_audit`: Assumption dependency graph with criticality levels
- `confound_catalog`: Catalog of known/unmeasured confounds with effect bounds
- `credibility_reassessment`: Revised credibility estimate with reasoning
- `recommended_followups`: Priority-ranked follow-up experiments to resolve challenges

#### 2. Markdown Report (`{artifact_name}_redteam_report.md`)

Human-readable summary of the same analysis with:
- Summary of primary finding
- Ranked alternative explanations
- Falsification tests and feasibility
- Destructive sanity check results
- Confound summary
- Updated credibility estimate
- Follow-up priorities

#### 3. Ledger Entry

Appended to `ledger.jsonl` with:
- `kind`: "fresh-context-redteam"
- `mission_id`: Mission being analyzed
- `summary`: High-level summary of challenges raised
- `related_paths`: References to JSON and MD reports
- `metadata`: Challenge counts, alternative explanation counts, etc.

---

## Adversarial Tactics

The red-team applies five distinct adversarial frameworks:

### 1. Measurement Attacks

- Assume all metrics subject to ±10% systematic error
- Question whether effect size robust to measurement noise
- Identify ceiling/floor effects that artifactually inflate signals
- Test effect persistence under measurement perturbation

### 2. Cherry-Picking Audit

- Verify p-hacking or multiple-testing corrections documented
- Check whether subset selection was pre-registered or post-hoc
- Enumerate all "researcher degrees of freedom" applied
- Estimate effect-size inflation from multiple-testing corrections

### 3. Confound Blindness

- List all known confounds that were not controlled
- Propose unmeasured confounds likely to impact effect size
- Calculate bounds on effect size after confound adjustment (if possible)
- Identify confounds most likely to reverse primary finding

### 4. Interaction Pathologies

- Check whether sample stratification reveals effect heterogeneity
- Test whether effect reverses in opposite subgroups
- Examine whether effect interacts with measurement domain
- Identify domains where effect disappears

### 5. Alternate Causal Routes

- Propose causal paths other than primary interpretation
- Weight plausibility by observational priors
- Generate interventions that would discriminate competing paths
- Identify which causal route would require strongest evidence

---

## Fresh-Reading Mode

The fresh-reading pass treats mission findings as raw observations and asks:

- What patterns jump out when I ignore existing interpretations?
- What non-obvious connections exist in the data?
- What interpretations do I initially dismiss, and why?
- Are there measurements I would expect to see that are absent?

This mode produces:
- **raw_observations**: Direct transcriptions of key measurements
- **non_obvious_patterns**: Unexpected regularities or asymmetries
- **dismissed_interpretations**: Alternative framings initially unconvincing

---

## Alternative Explanations

For each alternative explanation, the red-team records:

- **hypothesis**: The competing claim
- **plausibility_score**: Prior odds ratio (0.0 to 1.0)
- **mechanism**: How this alternative would generate the observed data
- **supporting_observations**: Data points consistent with this hypothesis
- **contradicting_observations**: Data points inconsistent with this hypothesis
- **required_assumptions**: What would need to be true for this hypothesis to hold

Hypotheses are ranked by plausibility and filtered by evidence standards (minimum credibility threshold).

---

## Falsification Checks

For each falsification check, the red-team records:

- **primary_claim**: The statement being tested
- **falsification_condition**: Specific condition that would falsify the claim
- **operationalization**: How to measure/test this condition
- **expected_result_if_true**: What we'd observe if primary claim holds
- **expected_result_if_false**: What we'd observe if primary claim is false
- **feasibility**: "low", "medium", or "high"

Falsification checks are operationalized to enable downstream testing.

---

## Destructive Sanity Checks

The red-team applies five tactical frameworks:

| Tactic | Severity | Example Check |
|--------|----------|---|
| **Measurement Attacks** | HIGH | Does effect persist under ±10% measurement perturbation? |
| **Cherry-Picking Audit** | HIGH | Are all subgroup analyses reported, or were some excluded? |
| **Confound Blindness** | HIGH | What unmeasured confounds would reverse the effect? |
| **Interaction Pathologies** | MEDIUM | Does effect reverse in any demographic subgroup? |
| **Alternate Causal Routes** | MEDIUM | Could X→Z without Y as intermediate? |

Each check produces:
- **status**: "passed", "failed", or "unclear"
- **concern**: What could be wrong
- **mitigation_if_present**: What evidence would address the concern

---

## Assumption Audit

The red-team exposes the assumption dependency graph:

- **assumption_id**: Unique identifier
- **text**: The assumption statement
- **justification**: Why this assumption is reasonable
- **depends_on**: Other assumptions this depends on
- **criticality**: "low", "medium", or "high"
- **test_status**: "untested", "supported", or "violated"

Produces a directed acyclic graph (DAG) of assumptions, enabling identification of critical vulnerabilities.

---

## Confound Catalog

For each known or proposed confound:

- **confound_name**: What is the confound
- **mechanism_description**: How it could affect the finding
- **expected_direction**: Positive, negative, or uncertain bias
- **estimated_effect_magnitude**: "negligible" to "large"
- **control_status**: "measured_and_controlled", "measured_only", "unmeasured", or "partially_measured"
- **adjustment_estimate**: Effect size after adjustment (if available)

Confounds are prioritized by plausibility and potential effect-size impact.

---

## Credibility Reassessment

After all challenges, the red-team produces:

- **original_credibility_estimate**: Pre-redteam estimate
- **reasons_for_reduction**: Specific challenges that lower credibility
- **reasons_for_stability**: Specific findings that support primary claim despite challenges
- **revised_credibility_estimate**: Post-redteam estimate
- **confidence_in_reassessment**: How confident are we in the revision (0.0 to 1.0)

The revised estimate balances challenges against stable evidence.

---

## Configuration

The fresh-context-redteam configuration (YAML) defines:

```yaml
challenge_modes:           # Which challenge types to enable
adversarial_tactics:       # Specific adversarial tactics to apply
evidence_standards:        # Thresholds for credibility, sample sizes, etc.
report_structure:          # What sections to include in reports
substrates:                # Project-specific configurations
  translation-pilot:       # translation pilot is first target
    preferred_challenge_artifacts:
      - baseline_findings
      - mechanistic_hypothesis
      - intervention_predictions
```

---

## Integration with Mission Ledger

Each red-team run appends a ledger entry with:

```json
{
  "created_at": "2024-01-15T10:30:00Z",
  "kind": "fresh-context-redteam",
  "mission_id": "translation-full-mission",
  "summary": "Red-teamed baseline findings: 3 alternative explanations, 5 confounds identified",
  "status": "complete",
  "related_paths": [
    "runs/fresh_context_redteam/baseline_redteam_report.json",
    "runs/fresh_context_redteam/baseline_redteam_report.md"
  ],
  "metadata": {
    "artifact_name": "translation-full-baseline",
    "challenges_raised": 12,
    "alternative_explanations_count": 3,
    "falsification_checks_count": 5
  }
}
```

This enables downstream systems to query red-team findings alongside other autonomy signals.

---

## translation pilot Mission as First Target

The fresh-context-redteam is designed to target the translation pilot mission artifacts first:

1. **baseline_findings**: Challenge the baseline measurements
2. **mechanistic_hypothesis**: Red-team the proposed mechanistic explanation
3. **intervention_predictions**: Test intervention predictions against alternatives

This prevents the research system from confidently advancing on potentially fragile foundations.

---

## Usage

### Via Script

```bash
python scripts/mission/run_fresh_context_redteam.py \
  --artifact-name translation-full-baseline \
  --mission-state /path/to/mission_state.json \
  -v
```

### Programmatically

```python
from deeploop.fresh_context_redteam import evaluate_fresh_context_redteam

result = evaluate_fresh_context_redteam(
    artifact_name="translation-full-baseline",
    mission_state_path=Path("path/to/mission_state.json"),
)

print(f"Report: {result['report_json_path']}")
print(f"Challenges raised: {result['challenges_raised']}")
```

### Output

- JSON report: `runs/fresh_context_redteam/{artifact}_redteam_report.json`
- Markdown report: `runs/fresh_context_redteam/{artifact}_redteam_report.md`
- Ledger entry: Appended to `ledger.jsonl`

---

## Validation Gates

The fresh-context-redteam is deterministic and validates:

- ✓ Configuration YAML is well-formed
- ✓ Artifact manifests are readable
- ✓ Measurement data is accessible
- ✓ JSON reports are schema-valid
- ✓ Ledger entries are well-formed
- ✓ Reports contain all required sections

All validations are recorded in test suite `test_fresh_context_redteam.py`.

---

## Limitations and follow-on work

**Current Limitations:**
- The current implementation can run from mission findings plus whatever
  manifests or artifact summaries are already available; it is not yet a full
  raw-manifest reader for every mission flow.
- Credibility reassessment uses fixed heuristic weights rather than Bayesian
  updating.
- Confound effects are usually estimated qualitatively unless upstream artifacts
  already provide quantitative bounds.

**Possible follow-on work (not current release claims):**
- Tighter manifest ingestion once upstream artifact schemas stabilize
- Probabilistic credibility reassessment with explicit priors
- Richer alternative-hypothesis generation from confound catalogs and artifact
  metadata
- Better feedback hooks into self-correction and statistical-rigor modules
- Ranking follow-up experiments by expected information value

---

## Related Documentation

- `docs/design/self-correction.md` — Failure classification and recovery routing
- `docs/design/statistical-rigor.md` — Rigor gates and evidence standards
- `docs/design/confound-guard.md` — Confound detection and adjustment
- `docs/design/experiment-ledger.md` — Durable artifact tracking and integration
