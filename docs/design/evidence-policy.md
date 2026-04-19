# DeepLoop evidence policy

DeepLoop needs explicit claim states so autonomous runs do not turn into
overclaiming.

## Evidence states

- **exploratory**: first-pass result or observation
- **replicated**: result supported by a follow-up check or repeated run
- **paper-candidate**: strong enough to consider for manuscript-facing reporting
- **release-candidate**: strong enough for artifact packaging review

## Promotion rules

- no jump from exploratory directly to paper-candidate
- no release-candidate promotion without provenance and licensing review
- paper-candidate and release-candidate always require human approval

## Why this matters

Ralph-style completion loops and AutoResearch-style keep/discard loops are both
useful, but neither alone protects against premature scientific claims.
