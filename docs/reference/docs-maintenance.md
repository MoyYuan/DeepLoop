# Docs maintenance

Use this page when you are adding, moving, or updating documentation.

## Canonical content map

| Surface | Primary audience | What belongs here |
| --- | --- | --- |
| `README.md` | New repo visitors | Short project summary and links into the docs site |
| `docs/index.md` | Everyone | Canonical docs home and audience-based routing |
| `docs/getting-started.md` and `docs/guide/` | Operators and newcomers | Task-based instructions and operator workflows |
| `docs/concepts/` | Non-technical and mixed readers | Plain-language explanations and mental models |
| `docs/reference/` | Technical users and advanced operators | Supported technical contracts and advanced runtime references |
| `docs/contributors/` | Contributors and maintainers | Entry point for maintainer/developer material inside the docs site |
| `docs/design/` | Maintainers | Detailed design notes and implementation references |
| `docs/wiki/` | Maintainers who need extra context | Companion deep dives and historical framing, not the main entry path |
| `docs/research/` and `docs/release/` | Research and release owners | Topic-specific notes, policies, and handoff material |

## Update triggers

When these areas change, update the related docs in the same change set.

| If you change... | Update at least... |
| --- | --- |
| `manage_mission.py`, operator commands, or mission control flow | `docs/getting-started.md`, `docs/guide/operator.md`, `docs/guide/faq.md`, relevant README snippets |
| Runtime behavior, state transitions, executor behavior, or boundaries | `docs/concepts/architecture.md`, `docs/concepts/glossary.md`, `docs/reference/index.md`, related `docs/design/` pages |
| Research evaluation assumptions or artifact expectations | `docs/research/README.md`, `docs/wiki/research-and-release.md`, relevant design notes |
| Packaging, release review, or approval flow | `docs/release/README.md`, `docs/reference/index.md`, `docs/design/release-automation.md` |
| Docs structure or page ownership | `docs/index.md`, `docs/reference/index.md`, this page, and any affected landing pages |

## Placement rules

1. Put the simplest reader path in `docs/guide/` or `docs/concepts/`.
2. Put technical maps in `docs/reference/`.
3. Put detailed design rationale and implementation notes in `docs/design/`.
4. Route maintainer-heavy material through `docs/contributors/` before linking directly to `docs/design/` or `docs/wiki/` from user-facing pages.
5. Keep `docs/wiki/` secondary. If a page becomes important for ordinary readers, move or summarize it into the canonical structure.
6. Do not create another general docs home page. The docs home stays `docs/index.md`; contributor landing pages should stay clearly scoped to contributors.

## Review checklist

Before you consider a docs change complete, check that:

1. the page has one clear audience
2. the page does not duplicate a simpler page without adding value
3. commands and file paths still match the repo
4. navigation points readers back to the canonical docs path
5. terminology matches the current runtime and operator language

## Validation

Run:

```text
python scripts/repo_check.py
python -m unittest tests.test_repo_contract -q
make docs-build
```

Use a full docs sweep after larger runtime or information-architecture changes,
especially if `docs/design/` or `docs/wiki/` moved.
