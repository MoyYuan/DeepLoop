# Autonomy boundary reduction

This page defines how DeepLoop should move from "asks the operator honestly" to
"needs the operator only for true safety or authority boundaries."

## Goal

Reduce unnecessary operator intervention without hiding risk or pretending away
real safety limits.

## Boundary classes

Every operator interruption should be classified as one of these:

| Class | Meaning | Desired treatment |
| --- | --- | --- |
| **Safety boundary** | Real safety, authority, licensing, or provenance review is required | Keep operator-only |
| **Governance boundary** | Public release, approval, or policy sign-off is required | Keep operator-only unless governance changes |
| **Product gap** | DeepLoop lacks recovery, triage, replanning, or validation logic it should own | Automate in DeepLoop |
| **Substrate gap** | The substrate contract or artifact surface is still underspecified | Fix in the substrate or boundary contract |

## Reduction rule

DeepLoop should not normalize operator habits around product gaps.

If the operator keeps doing the same bounded recovery step, that is evidence the
product needs:

- better recovery
- better triage
- better replanning
- better self-verification
- better status truthfulness

## Practical targets

The next autonomy-expansion wave should focus on:

1. converting repeatable blocked-queue interventions into bounded automated
   recovery or bounded triage
2. reducing stale or misleading status/inbox surfaces
3. making retry/reroute/downscope choices easier to automate safely
4. keeping only true safety, governance, and authority gates operator-only

Managed-mode blocked queue entries now have an explicit first step in that
direction: DeepLoop runs a bounded triage pass before opening the inbox, then
surfaces the triage recommendation in the operator request instead of requiring
the operator to trigger triage manually as the first response.

## Make the remaining gap visible

Boundary reduction should be visible in product artifacts, not only in design
notes.

The mission runtime and operator monitor should surface:

- operator-request class counts
- soft-gate counts and risk classes
- bounded recovery outcomes
- the latest unresolved temporary gap, if one is still open

That visibility is part of the promotion bar: DeepLoop should be able to show
which stops are permanent boundaries versus temporary product/substrate gaps, and
whether the temporary class is shrinking over time.

## Promotion rule

Do not claim **high-autonomy** or **fully automatic** until the remaining
operator boundaries are mostly safety, governance, or authority boundaries and
that classification is visible in the product/docs.

## Related docs

- [Operating model](operating-model.md)
- [Release automation](release-automation.md)
- [Public autonomy roadmap](../release/public-autonomy-roadmap.md)
