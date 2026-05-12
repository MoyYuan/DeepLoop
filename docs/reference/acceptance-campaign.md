# Acceptance campaign

DeepLoop's **four tiers** are the engineering ladder:

1. unit
2. integration
3. smoke
4. bounded real

Above them sits a separate **acceptance campaign**: an expensive real-project
confidence surface that should be used before major releases when you need more
than the broader multi-surface evidence bundle.

## Canonical campaign

The first canonical acceptance campaign is:

- **`translation-paper-scale`**

Use it through:

```text
make test-acceptance
```

or directly:

```text
python scripts/testing/run_acceptance_campaign.py --campaign translation-paper-scale
```

## What it does today

The current implementation is an **acceptance bootstrap** built on the real
DeepLoop -> translation pilot end-to-end proof path that already exists in the repo.

It:

- initializes a real translation pilot mission
- runs the baseline queue
- generates and executes follow-ups
- runs direct intervention
- collects self-correction, meta-eval, and packaging artifacts
- writes a DeepLoop-owned acceptance review on top

That acceptance review is the durable pass/fail record for the campaign.

## What passing means

The current acceptance review requires:

- green baseline queue execution, or safe reuse of already-existing baseline
  manifests
- green follow-up queue execution
- completed direct intervention
- presence of the core proof artifacts:
  - mechanistic manifest
  - intervention manifest
  - self-correction report
  - meta-eval report
  - package manifest
  - package summary

## Output artifacts

The campaign writes:

- the existing translation pilot proof summary
- `acceptance_review.json`
- `acceptance_review.md`

next to the proof summary under the mission proof root.

## Final acceptance bundle

The translation pilot acceptance campaign is no longer the only final exam. The
stronger public claim depends on a bundle:

1. an eligible-for-promotion proof-matrix review across materially different
   plain-folder workflow shapes
2. a passing fresh-clone / fresh-home onboarding proof on the documented public
   path
3. a real promotable release-candidate review for at least one mission package
   with the required durable reviews
4. autonomy-gap evidence showing covered temporary gaps are being reduced by
   bounded recovery
5. this acceptance campaign when you need an additional real-project exam on top
   of those broader artifacts

## How to use it

- use the normal four tiers for ordinary engineering work
- use `test-acceptance` as the real-project confidence layer, not as the only
  final exam
- if it fails, treat each failure as a product/substrate/governance ownership
  question and fix the right layer

## Honesty note

This runner is the canonical acceptance surface now, but it is still a
bootstrap toward a broader full paper-scale campaign. The contract is
meant to stay stable while the real campaign grows stronger.
