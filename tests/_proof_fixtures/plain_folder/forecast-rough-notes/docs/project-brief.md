# Project brief

## Goal

Use this folder as the only researcher input to produce a cautious first-pass
weekly demand forecast from `data/store_demand_sample.csv`.

## Rough notes

- Target variable is `next_week_units`.
- Compare against a simple last-week-repeat baseline before trying anything more ambitious.
- Keep the latest week as the holdout slice and avoid promo or post-period leakage.
- Metrics are still rough; start with a defensible forecasting metric and surface any operator clarification that still matters.
- Finish with a bounded final report and artifact-readiness summary rather than a publication claim.

## Important rule

This folder is researcher input only. Do not place DeepLoop-owned runtime state,
generated configs, build code, or experiment implementation code inside this
folder.
