# DeepLoop Self-Correction Engine Design

## Overview

The self-correction engine is a deterministic subsystem that:
1. **Reads** mission/manifest artifacts and execution logs
2. **Classifies** failures into structured categories
3. **Recommends** recovery actions (continue/reroute/stop)
4. **Maintains** durable ledgers and decision artifacts

This enables mission resilience and intelligent recovery without human intervention.

## Architecture

### Components

```
self-correction-engine/
├── config (self-correction.yaml)
├── artifacts (JSON/MD outputs)
│   ├── ledger.jsonl (sequential decisions)
│   ├── manifest.json (classified failures)
│   └── analysis.md (human-readable report)
├── classification module
├── recovery router
└── ledger writer
```

### Data Flow

```
mission artifacts (manifest, logs)
    ↓
[failure detector]
    ↓
[failure classifier] → manifest.json
    ↓
[recovery router] → decision (continue/reroute/stop)
    ↓
[ledger writer] → ledger.jsonl + analysis.md
```

## Failure Classification

### Classes

1. **data_quality** (recoverable, medium severity)
   - Dataset corruption or validation failures
   - Examples: missing columns, type mismatches, distribution shifts

2. **model_training** (recoverable, high severity)
   - Convergence failures, NaN losses, gradient issues
   - Examples: divergent training, unstable gradients

3. **execution_resource** (recoverable, high severity)
   - OOM, timeout, compute unavailability
   - Examples: insufficient memory, quota exceeded

4. **validation_gate** (recoverable, medium severity)
   - Autonomy gates, sanity checks, statistical rigor gates
   - Examples: rigor threshold not met, contract violation

5. **manifest_incompleteness** (recoverable, medium severity)
   - Missing metrics, malformed artifacts, schema violations
   - Examples: missing accuracy field, invalid JSON

6. **unknown** (recoverable, low severity)
   - Transient or unclassified failures
   - Examples: transient network errors, unclear error messages

### Classification Logic

```
IF error_pattern IN known_patterns:
    class = lookup_pattern_to_class(error_pattern)
    confidence = pattern_match_strength
ELSE:
    class = unknown
    confidence = 0.5
```

## Recovery Routing

### Decision Matrix

| Failure Class | Severity | Retry Possible | Reroute Options | Decision |
|---------------|----------|----------------|-----------------|----------|
| data_quality | medium | Yes | adjust split/preprocessing | reroute |
| model_training | high | Yes | reduce capacity, tune LR | reroute |
| execution_resource | high | Yes | reduce batch size | reroute |
| validation_gate | medium | Yes | rerun with adjusted params | reroute |
| manifest_incompleteness | medium | No | fail-safe continue | continue |
| unknown | low | Yes | continue with monitoring | continue |

### Recovery Strategies

1. **continue**: Proceed to next phase
   - For transient failures and validation warnings
   - Logs flag for human review

2. **reroute**: Modify approach and retry
   - Reduce computational scope
   - Adjust hyperparameters
   - Switch fallback methodology

3. **stop**: Escalate to human
   - Resource exhaustion without recovery options
   - Fundamental incompatibilities
   - Multiple failed recovery attempts

## Artifacts

### ledger.jsonl

Sequential decisions in append-only format:
```json
{"timestamp": "2025-01-15T10:30:45Z", "mission_id": "translation-full-01", "failure_class": "data_quality", "confidence": 0.92, "action": "reroute", "reason": "Schema mismatch in split_family", "retry_count": 1}
```

### manifest.json

Structured failure classification:
```json
{
  "mission_id": "translation-full-01",
  "analysis_timestamp": "2025-01-15T10:30:45Z",
  "failures": [
    {
      "id": "fail-001",
      "timestamp": "2025-01-15T10:25:30Z",
      "classification": "data_quality",
      "confidence": 0.92,
      "error_message": "...",
      "source_artifact": "experiment_001/manifest.json",
      "recovery_action": "reroute",
      "retry_attempt": 1
    }
  ],
  "recommendation": "continue",
  "ledger_reference": "mission-artifacts/self-correction/ledger.jsonl"
}
```

### analysis.md

Human-readable markdown report:
```markdown
# Self-Correction Analysis Report
**Mission:** translation-full-01  
**Timestamp:** 2025-01-15T10:30:45Z

## Summary
- Total failures analyzed: 3
- Resolved via recovery: 2
- Unresolved: 1

## Failures
1. **data_quality** (confidence: 0.92)
   - Source: experiment_001/manifest.json
   - Issue: Missing lexicalization_gap in metrics
   - Action: Reroute (adjust preprocessing)
   - Result: Success

## Recommendation
**Action:** CONTINUE  
**Reason:** All recoverable failures have been addressed
```

## Deterministic Behavior

The engine ensures:
1. **Reproducibility**: Same inputs → same classification
2. **Auditability**: All decisions logged with timestamps and confidence scores
3. **Durability**: Artifacts persist across system restarts
4. **Consensus**: Classification based on multiple error signals (pattern, context, history)

## Concrete Target: translation pilot Mission

For the translation-full mission:
- **Manifest location:** `~/workspaces/repos/translation-pilot/.deeploop/missions/translation-full.yaml`
- **Expected artifacts:** Baseline run outputs, experiment manifests
- **Target failures:** Model convergence, data validation, gate failures
- **Recovery priority:** Maintain experimental integrity while enabling retry

## Integration Points

1. **Mission Progress**: Read from the project-owned follow-up planner and mission-state artifacts
2. **Ledger**: Write to `ledger.py` append-only store
3. **Autonomy Gates**: Classify gate failures and recommend recovery
4. **Execution Profiles**: Adjust resource allocations for reroute decisions
