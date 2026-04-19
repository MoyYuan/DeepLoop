# Novelty-Refresh Loop Design

## Overview

The novelty-refresh loop is a deterministic subsystem within DeepLoop that periodically:

1. **Re-evaluates mission novelty** against the current state of prior-art literature and internal findings
2. **Detects branch shifts** (e.g., shifts in research direction, hypothesis, or scope)
3. **Flags stale literature** that may no longer be representative of the state of the art
4. **Emits a novelty delta memo** summarizing changes in novelty position, risks, and recommended follow-up actions

## Design Principles

### Deterministic and Replay-Safe

- The loop operates on immutable artifacts (prior-art docs, mission state snapshots, findings ledger)
- No live API calls; all inputs are local and versioned
- Same inputs → same output, enabling audit trails and validation

### Lightweight Surface

- No new web dependencies
- Leverages existing mission artifacts (novelty-positioning.md, evaluation-contract.md, etc.)
- Outputs are JSON + Markdown, integrating with the existing ledger system

### Branch Shift Detection

When a mission branch shift is detected (e.g., scope expansion, hypothesis revision, or new experimental direction), the loop:
1. Compares the new mission state against the previous state
2. Flags what has changed (goals, constraints, prior-art references)
3. Re-evaluates novelty in light of the shift

### Staleness Checks

The loop maintains **literature-staleness thresholds** per category (mechanistic-interpretability, activation-steering, etc.):
- **Warn** if recent literature falls within `warn_before_months`
- **Block** if no updates exist within `max_age_months`

## Data Flow

```
┌─────────────────────────────────────────┐
│  Mission Artifacts (local)              │
│  - novelty-positioning.md               │
│  - evaluation-contract.md               │
│  - mechanistic-localization-plan.md     │
│  - causal-intervention-plan.md          │
└────────────┬────────────────────────────┘
             │
             ▼
    ┌────────────────────┐
    │  Branch Shift      │
    │  Detector          │
    └────────┬───────────┘
             │
             ▼
┌────────────────────────────────────────────────┐
│  Novelty Assessor                              │
│  - Extract key claims and prior-art refs       │
│  - Score dimensions (behavioral, mechanistic, │
│    intervention, rigor)                        │
│  - Compare against Ralph vs AutoResearch memo  │
│  - Cross-check with findings ledger            │
└────────────┬─────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────┐
│  Literature Staleness Checker                  │
│  - Verify recency of cited work                │
│  - Warn if approaching age threshold           │
│  - Suggest fresh references                    │
└────────────┬─────────────────────────────────┘
             │
             ▼
┌────────────────────────────────────────────────┐
│  Delta Memo Emitter                            │
│  - Novelty score (1-5)                         │
│  - Branch shifts (list)                        │
│  - Stale literature warnings                   │
│  - Follow-up recommendations                   │
│  - Output: JSON + Markdown                     │
│  - Ledger entry: kind=novelty-refresh          │
└─────────────────────────────────────────────────┘
```

## Novelty Assessment Dimensions

Each dimension is scored 1–5:

### 1. Behavioral Characterization
- **How well does the project characterize failure modes vs. prior work?**
- Evidence sources: evaluation-contract.md, baseline results
- High score: The project identifies specific, previously-undocumented asymmetry failure modes

### 2. Mechanistic Localization
- **Does localization go beyond generic factual memory understanding?**
- Evidence sources: mechanistic-localization-plan.md, ablation studies
- High score: The project pinpoints asymmetry-specific internal mechanisms, not just "factual knowledge is stored in MLPs"

### 3. Intervention Novelty
- **Are interventions specific to asymmetry, or just generic steering methods?**
- Evidence sources: causal-intervention-plan.md, side-effect analysis
- High score: Targeted, asymmetry-specific interventions with bounded collateral damage

### 4. Empirical Rigor
- **How robust is the evidence against prior-art baselines?**
- Evidence sources: replication count, statistical validation
- High score: Multiple runs, proper controls, comparisons against prior methods

## Output: Novelty Delta Memo

### JSON Structure

```json
{
  "timestamp": "2024-04-12T17:30:00Z",
  "mission_id": "translation-full-mission",
  "novelty_status": {
    "overall_score": 3.5,
    "score_range": [1, 5],
    "interpretation": "Moderate novelty with clear differentiation in mechanistic focus"
  },
  "branch_shifts": [
    {
      "detected_at": "2024-04-12T17:25:00Z",
      "shift_type": "scope_expansion",
      "from": "baseline_plus_localization",
      "to": "baseline_plus_localization_plus_intervention_scope_added",
      "impact": "Increases novelty potential via asymmetry-specific interventions"
    }
  ],
  "dimension_scores": {
    "behavioral_characterization": 4,
    "mechanistic_localization": 3,
    "intervention_novelty": 3,
    "empirical_rigor": 2
  },
  "prior_art_alignment": [
    {
      "reference": "translation pilot (original paper)",
      "coverage": "benchmark_design",
      "differentiation": "Our work adds mechanistic and intervention layers"
    },
    {
      "reference": "ROME, MEMIT",
      "coverage": "factual_memory_localization",
      "differentiation": "We specialize to asymmetry-specific reasoning, not generic facts"
    }
  ],
  "literature_staleness": {
    "category": "mechanistic_interpretability",
    "last_major_update": "2023-11",
    "age_months": 5,
    "max_age_months": 12,
    "status": "fresh",
    "note": "Transformer circuits and mechanistic interpretability remain active; no staleness warning"
  },
  "recommendations": [
    {
      "priority": "high",
      "type": "literature_review",
      "action": "Review recent papers on activation steering for relational reasoning"
    },
    {
      "priority": "medium",
      "type": "replication",
      "action": "Replicate asymmetry failures across model scales (1B, 7B, 70B)"
    }
  ],
  "caveats": {
    "evaluation_scope": "Assessment based on current mission artifacts and findings ledger",
    "assumed_constraints": "No live web search; relies on prior-art refs already in docs",
    "unverified_claims": [
      "Intervention success rates pending experimental validation"
    ]
  }
}
```

### Markdown Structure

```markdown
# Novelty Delta Memo: translation-full-mission

**Generated:** 2024-04-12 17:30 UTC  
**Mission Phase:** execution

## Novelty Status Summary

Overall novelty score: **3.5 / 5**

The project shows moderate but credible novelty through:
- Clear differentiation in mechanistic focus (vs. benchmark-only prior work)
- Asymmetry-specific intervention design (vs. generic steering methods)
- Structured side-effect evaluation

## Prior-Art Alignment

| Reference | Coverage | Our Differentiation |
| --------- | -------- | ------------------- |
| translation pilot (original) | Benchmark design | Adds mechanistic + intervention layers |
| ROME, MEMIT | Factual memory localization | Specializes to asymmetry-specific reasoning |
| Activation steering | Generic inference-time edits | Targets asymmetry-specific representations |

## Branch Shift Detection

**Shift detected at 2024-04-12 17:25 UTC**
- **Type:** Scope expansion
- **From:** baseline + localization
- **To:** baseline + localization + intervention scope added
- **Impact:** Increases novelty potential via asymmetry-specific interventions (+0.3 score delta)

## Literature Staleness Check

| Category | Age | Max Age | Status | Note |
| -------- | --- | ------- | ------ | ---- |
| Mechanistic interpretability | 5 mo | 12 mo | ✅ Fresh | Transformer circuits remain active |
| Activation steering | 3 mo | 18 mo | ✅ Fresh | Recent papers on relational editing |
| Factual knowledge editing | 4 mo | 12 mo | ✅ Fresh | ROME, MEMIT remain standard references |

## Assessment Dimensions

### 1. Behavioral Characterization: 4/5
Clear documentation of asymmetry failure modes distinct from generic factual recall issues.

### 2. Mechanistic Localization: 3/5
Good plan for localization but limited empirical validation so far. Potential to reach 4/5 with ablation evidence.

### 3. Intervention Novelty: 3/5
Asymmetry-specific design is clear in plan; pending empirical validation of side-effect bounds.

### 4. Empirical Rigor: 2/5
Baseline runs complete; needs replication across model scales and statistical validation.

## Follow-Up Recommendations

### High Priority
1. **Literature Review:** Recent papers on activation steering for relational reasoning (2023–2024)
2. **Replication:** Asymmetry failures across model scales (1B, 7B, 70B)

### Medium Priority
3. **Ablation Study:** Validate that asymmetry localization is distinct from generic factual memory
4. **Side-Effect Analysis:** Quantify collateral impact of interventions on unrelated behavior

### Low Priority
5. **Archive:** Periodically refresh this memo as new findings accrue

## Caveat & Boundaries

- **Scope:** Assessment based on current mission artifacts and findings ledger; no live web search
- **Assumptions:** Prior-art references already in docs are sufficient; no new papers discovered
- **Unverified:** Intervention success rates pending experimental validation

---

*Next refresh trigger:* Phase transition or branch shift detected
```

## Integration with Ledger

Each novelty-refresh run appends a ledger entry:

```json
{
  "created_at": "2024-04-12T17:30:00Z",
  "kind": "novelty-refresh",
  "mission_id": "translation-full-mission",
  "summary": "Novelty-refresh: score 3.5/5, scope expansion shift detected, literature fresh",
  "status": "success",
  "related_paths": [
    "configs/autonomy/novelty-refresh.yaml",
    "docs/research/novelty-positioning.md",
    "runs/novelty_refresh/novelty-delta-report-20240412T173000Z.json",
    "runs/novelty_refresh/novelty-delta-report-20240412T173000Z.md"
  ],
  "metadata": {
    "novelty_score": 3.5,
    "branch_shifts_detected": 1,
    "stale_literature_count": 0,
    "dimensions": {
      "behavioral_characterization": 4,
      "mechanistic_localization": 3,
      "intervention_novelty": 3,
      "empirical_rigor": 2
    }
  }
}
```

## Validation & Testing

- Parse mission artifacts (YAML, Markdown, JSON) without errors
- Ensure deterministic output for same inputs
- Verify ledger entry creation
- Check that stale-literature warnings are accurate
- Validate JSON schema against reported novelty structure
