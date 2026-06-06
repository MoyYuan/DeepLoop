# Self-optimization engine

DeepLoop now has a deterministic self-optimization surface that learns from runtime
telemetry, findings history, and mission artifacts to drive autonomous profile and
branch adjustments.

## Purpose

The engine integrates signals from multiple autonomy components (utility scorer, 
self-correction, statistical-rigor, confound-guard, and sanity-gates) to emit 
bounded, auditable optimization recommendations:

- **Branch expansion**: Recommend creating additional experiment branches when conditions show high utility and strong consistency
- **Branch shrinkage**: Recommend pruning low-utility branches when cost outweighs evidence gain
- **Profile adjustment**: Tune execution parameters (retry strategy, batch sizing, checkpoint intervals) to improve efficiency
- **Resource reallocation**: Shift computational budget toward higher-utility targets

## Contract

The machine-readable contract lives at `configs/autonomy/self-optimization.yaml`.

The optimization strategy includes:

### Data sources
- **Utility scorer**: Multi-factor branch rankings (evidence quality, cost, novelty, information gain)
- **Self-correction**: Branch health assessment and recovery actions
- **Statistical rigor**: Evidence quality and power analysis
- **Confound guard**: Confounding factor detection and risk assessment
- **Sanity gates**: Pre-execution validation and readiness metrics

### Decision strategies
- **Aggressive branching**: High utility + low variance + sufficient evidence → expand branches
- **Targeted slice exploration**: High utility but low evidence in subspaces → branch specific dimensions
- **Low-utility consolidation**: Low utility + high variance → prune 30% of branches
- **Evidence deficit halt**: Low utility + low evidence + high cost → pause or merge branches
- **Profile retuning**: When optimization vectors exist → adjust execution parameters
- **Resource reallocation**: Shift budget toward highest-expected-gain branches

### Bounded constraints
- Maximum 5 recommendations per run
- Maximum 20% branch changes per optimization cycle
- Minimum 2 observations before recommendation (except single strong signals)
- Can act on single strong signal with lower confidence if needed

## Runtime integration

- **Module**: `src/deeploop/research/self_optimization.py`
- **Runner**: `scripts/mission/run_self_optimization.py`
- **Durable artifacts**:
  - Mission-linked: `~/.deeploop/runs/deeploop/self_optimization/<mission_id>/`
  - JSON report: `self_optimization_report_{timestamp}.json`
  - Recommendations: `optimization_recommendations_{timestamp}.yaml`
- **Ledger integration**:
  - `self-optimization` entries capture recommendation summary
  - Metadata includes signal sources, confidence scores, and constraints applied

## First substrate: translation pilot

The engine operates on translation pilot mission artifacts, ingesting:
- Utility scores from multiple model families (Qwen 2B, 4B, 7B variants)
- Self-correction assessments of baseline, localization, and intervention branches
- Statistical rigor reports on effective sample sizes and confidence intervals
- Confound risk flags from parameter sweep analysis
- Sanity gate pass rates and warning counts

Example scenarios:

1. **High-utility baseline, low variance** → Recommend expanding from 3 to 5 branches
2. **Baseline accuracy collapse + high cost** → Recommend pausing baseline, pivoting to localization
3. **Strong statistical rigor but poor cost efficiency** → Recommend profile optimization (reduce batch size, checkpoint frequency)
4. **Elevated confound risk on specific model families** → Recommend isolation strategy or expert escalation

## Output structure

### JSON Report
```json
{
  "timestamp": "2024-04-12T15:30:00+00:00",
  "mission_id": "translation-full",
  "optimization_phase": "post-baseline",
  "signal_summary": {
    "utility_score": 0.78,
    "evidence_quality": 450,
    "cost_efficiency": 0.65,
    "confound_risk": 0.35,
    "branch_health": "healthy",
    "consistency_signal": 0.85,
    "sources_consulted": ["utility_scorer", "self_correction", "statistical_rigor"]
  },
  "recommendations": [
    {
      "recommendation_id": "rec-expand-high-utility",
      "category": "expansion",
      "target": "branch_count",
      "action": "recommend_branch_expansion",
      "confidence_level": 0.78,
      "rationale": "High utility score (0.78) with strong consistency signals warrant branch expansion.",
      "estimated_impact": {
        "new_branches": 2,
        "expected_utility_gain": 0.1
      }
    }
  ],
  "decision_rationale": "Utility score 0.78. Branch health: healthy. Recommending: expansion.",
  "bounded_constraints_applied": ["Limited to top 5 recommendations"],
  "next_observation_window_days": 6
}
```

### Recommendations YAML
```yaml
timestamp: "2024-04-12T15:30:00+00:00"
mission_id: "translation-full"
total_recommendations: 1
recommendations:
  - recommendation_id: rec-expand-high-utility
    category: expansion
    target: branch_count
    action: recommend_branch_expansion
    confidence_level: 0.78
    rationale: "High utility score (0.78) with strong consistency signals warrant branch expansion."
    estimated_impact:
      new_branches: 2
      expected_utility_gain: 0.1
    fallback_action: maintain_current_strategy
```

## Integration with mission progression

Self-optimization runs after key mission milestones:
1. **Post-baseline**: After self-correction classifies baseline branches
2. **Post-localization**: After statistical-rigor validates localization evidence
3. **Post-intervention-prep**: Before committing to full intervention branches

The engine reads mission_state.json to infer the current phase and contextualize recommendations.

## Determinism and reproducibility

All recommendations are derived from:
1. Timestamped artifact ingestion
2. Deterministic thresholds (configurable in YAML)
3. Explicit decision tree logic
4. Bounded output constraints
5. Full signal attribution (sources_consulted)

Ledger entries capture all metadata needed to audit and reproduce decisions.

## Extending the engine

To add new optimization signals:

1. Add a new entry to `data_sources` in self-optimization.yaml
2. Implement a `_load_<signal>_signals()` function in `src/deeploop/research/self_optimization.py`
3. Update `SignalSummary` to include the new signal
4. Add decision logic in `_make_recommendations()` to use the signal
5. Update this documentation with the new strategy

Example: Adding a "throughput" signal for scheduling optimization.
