# Public autonomy roadmap

This is the single public roadmap overview for DeepLoop's release-facing
autonomy story. Use [Release posture](README.md) for the current claim and trust
evidence, and use
[Public alpha foundations](public-alpha-foundations.md) for the minimum
repo-facing floor.

## True now / current claim

Release posture owns the full evidence pack. In roadmap terms, what is true now
is still intentionally narrow:

- DeepLoop is share-ready as a **bounded-support autonomous research autopilot**
  on the documented Linux + Python 3.11 path
- the current contract still includes explicit operator boundaries, governance
  boundaries, and release approval boundaries
- outside researchers can install the repo on the documented path, run the
  bootstrap checks, and evaluate the first mission flow without hidden claim
  inflation

This bucket still does **not** justify:

- broad OS or runner portability claims
- minimal-operator autonomy everywhere
- approval-free release promotion
- broad multi-substrate superiority claims

Initial foundations from the near-term product wave now exist on the supported
path:

- measurable adaptation runs can emit and surface a deterministic
  metric-ratchet result
- missions can opt into deterministic routing rules for narrow measurable cases
- operator surfaces now expose temporary-gap categories, auto-recovered versus
  escalated counts, and managed-mode staged recovery hints

Those additions improve the supported path, but they do **not** by themselves
widen the public claim beyond bounded-support alpha.

The next step is to harden and widen those foundations carefully, not pretend
the broad autonomy problem is already solved.

## Next / near-term credibility work

The near-term goal is a smaller set of stronger claims, not a bigger slogan.
These items strengthen the current bounded-support story and widen it only where
evidence becomes real.

| Work item | Why it sits in the near term | Honest outcome if it lands |
| --- | --- | --- |
| **Harden metric ratchets** | Metric-ratchet evidence now exists on the supported path; the near-term job is to make its thresholds and release use harder to game | Clearer pass/fail release evidence for the current claim |
| **Expand deterministic routing carefully** | Deterministic routing v1 exists for narrow measurable cases; the near-term job is to keep it opt-in, explicit, and provable as it expands | More reproducible mission behavior on the supported path without pretending the planner disappeared |
| **Reduce operator-gap work** | Telemetry now makes temporary-gap categories and escalations visible; the near-term job is to shrink repeated operator stops into bounded retry, reroute, or replanning | Fewer operator stops without hiding real safety boundaries |
| **Broader portability** | The current Linux-centered support contract is still too narrow for stronger public claims | A slightly wider but still explicit support matrix |
| **Stronger multi-substrate proof** | DeepLoop should show bounded-real behavior on 2-3 materially different substrates before making stronger autonomy claims | Better evidence that the current model is not tied to one substrate shape |

Near-term work should stay honest about scope. It is meant to improve
credibility, reduce product-gap friction, and widen proof carefully. It does
**not** put distributed execution or broad superiority claims on the immediate
promise surface.

## Later / exploratory bets

These bets may matter later, but they should remain off the immediate promise
surface until the near-term credibility work lands first.

Scratchpad -> formalization stays in this bucket on purpose.

| Bet | Why it is later or exploratory |
| --- | --- |
| **Scratchpad -> formalization** | Explicitly deferred. Worth exploring if it can turn ad-hoc lessons into reusable runtime structure, but the mechanism, evidence bar, and user value are still too unsettled for the near-term promise surface |
| **Portability beyond the next supported matrix** | Only honest after the smaller, explicit portability expansion is already working in public |
| **Distributed execution** | Potentially valuable for scale, but not required to prove the current public-alpha claim and too easy to over-promise early |
| **Broad superiority or "fully automatic for everyone" claims** | Off-limits until comparative evidence, portability proof, and operator-gap reduction are much stronger than they are today |

## Related docs

- [Release posture](README.md)
- [Public alpha foundations](public-alpha-foundations.md)
- [Portable bootstrap](portable-bootstrap.md)
- [Autonomy governance](autonomy-governance.md)
- [Multi-substrate proof](multi-substrate-proof.md)
- [Release maintenance](release-maintenance.md)
