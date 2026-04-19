# DeepLoop Utility Scorer Design

## Overview

The Utility Scorer is a deterministic system for ranking and prioritizing experiment branches based on multi-factor scoring. It combines evidence quality, replication gaps, cost/risk profiles, novelty proxies, and expected information gain to produce actionable recommendations for DeepLoop mission orchestration.

## Objectives

1. **Quantify branch value** using rigorous multi-factor scoring
2. **Rank experiments** for continued execution, deferral, pruning, or prioritization
3. **Integrate autonomy artifacts** (sanity, self-correction, statistical-rigor, confound-guard)
4. **Produce durable JSON/Markdown reports** linked to mission ledger
5. **Enable deterministic decision-making** for autonomous experiment management

## Architecture

### Scoring Factors

The utility score combines five weighted dimensions:

#### 1. Evidence Quality (weight: 0.25)
- **Source**: Statistical-rigor evaluation results
- **Metrics**:
  - Effective sample size (normalized 0-1)
  - Uncertainty interval width (inverted: narrower = higher quality)
  - Primary metric estimate reliability
- **Range**: [0, 1]

#### 2. Replication Gap (weight: 0.20)
- **Source**: Self-correction and sanity-gates outputs
- **Metrics**:
  - Consistency across branches (higher = better replicated)
  - Stability across conditions
  - Pass rate on sanity checks
- **Range**: [0, 1]

#### 3. Cost/Risk Profile (weight: 0.20)
- **Source**: Runtime metadata and resource consumption
- **Metrics**:
  - GPU hours consumed (normalized inverse)
  - Memory usage (normalized inverse)
  - Failure/retry count (lower = better)
  - Wall-clock time efficiency
- **Range**: [0, 1]

#### 4. Novelty Proxy (weight: 0.20)
- **Source**: Sanity-gates findings and hypothesis deviation
- **Metrics**:
  - Divergence from baseline expectation
  - Finding-to-baseline ratio
  - Unexpectedness score (higher for surprising results)
- **Range**: [0, 1]

#### 5. Expected Information Gain (weight: 0.15)
- **Source**: Confound-guard evaluation and mechanistic understanding
- **Metrics**:
  - Confound-guard pass rate
  - Localization clarity (if mechanistic)
  - Gap closure potential
- **Range**: [0, 1]

### Multi-Factor Score Formula

```
utility_score = (
    0.25 * evidence_quality +
    0.20 * replication_gap +
    0.20 * cost_risk_profile +
    0.20 * novelty_proxy +
    0.15 * expected_information_gain
)
```

**Adjusted Score** (if critical gates fail):
- If evidence_quality < 0.3: apply -0.15 penalty
- If confound_risk > 0.7: apply -0.20 penalty
- If cost > 2x median: apply -0.10 penalty

## Recommendation Logic

### Recommendation States

- **PRIORITIZE**: score ≥ 0.80 AND evidence_quality ≥ 0.60
  - High value, well-supported findings
  - Candidate for immediate follow-up or publication

- **CONTINUE**: 0.60 ≤ score < 0.80 OR (score ≥ 0.50 AND novelty_proxy > 0.70)
  - Worth pursuing with potential improvements
  - May warrant mechanistic follow-up or replication

- **DEFER**: 0.40 ≤ score < 0.60
  - Low priority but not hopeless
  - Revisit after higher-priority branches complete

- **PRUNE**: score < 0.40 OR (confound_risk > 0.8 AND evidence_quality < 0.4)
  - Insufficient value for current resource constraints
  - May be resurrected with additional context

## Integration Points

### Input Artifacts

1. **Mission state** (`mission_state.json`)
   - Mission ID, phase, constraints
   - Budget and resource limits

2. **Statistical-rigor reports** (JSON)
   - Sample size, confidence intervals
   - Warning flags
   - Promotion guidance

3. **Self-correction ledger** (JSONL)
   - Correction history
   - Stability assessments
   - Branch consistency

4. **Sanity-gates reports** (JSON)
   - Check pass/fail status
   - Finding summary
   - Deviation from baseline

5. **Confound-guard reports** (JSON)
   - Confound risk assessment
   - Threat prioritization
   - Mitigation guidance

### Output Artifacts

1. **Utility report** (JSON)
   - Scored branches with full factor breakdown
   - Recommendations with justification
   - Ledger metadata

2. **Utility summary** (Markdown)
   - Human-readable branch rankings
   - Factor contribution analysis
   - Decision guidance

3. **Ledger entry** (JSONL append)
   - Utility score summary
   - Top recommendation
   - Related artifact paths

## Usage

### Command-line Interface

```bash
python scripts/mission/run_utility_scorer.py \
  --mission-state /path/to/mission_state.json \
  --branches /path/to/branches \
  --contract configs/autonomy/utility-scorer.yaml \
  --artifact-name my-study
```

### Programmatic API

```python
from deeploop.research.utility_scorer import evaluate_utility_score

result = evaluate_utility_score(
    branches_dir=Path("/runs/mission/branches"),
    mission_state_path=Path("/runs/mission/mission_state.json"),
    contract_path=Path("configs/autonomy/utility-scorer.yaml"),
)

# result contains:
# - scored_branches: list of (id, score, factors, recommendation)
# - ranked_branches: sorted by utility descending
# - report_json_path: path to full report
# - report_markdown_path: path to summary
# - summary: top-level statistics
```

## Determinism and Validation

### Deterministic Properties

- All floating-point operations use consistent rounding (6 decimal places)
- Factor calculations are order-independent
- No random sampling or stochastic components
- Identical inputs always produce identical scores

### Validation Rules

- Verify all source artifacts exist and are parseable
- Check that weights sum to 1.0
- Validate score components are in [0, 1]
- Ensure recommendations are aligned with scores
- Verify ledger entries link correct artifacts

## Future Enhancements

1. **Adaptive weighting** based on mission phase
2. **Historical scoring** to track branch evolution
3. **Portfolio optimization** across all branches
4. **Predictive modeling** of information gain
5. **Calibration** against manual expert rankings

## References

- [Statistical rigor](statistical-rigor.md)
- [Self-correction](self-correction.md)
- [Research sanity gates](research-sanity-gates.md)
- [Confound guard](confound-guard.md)
- [Mission orchestrator](mission-orchestrator.md)
