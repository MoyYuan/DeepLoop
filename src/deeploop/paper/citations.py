"""Citation search via Semantic Scholar API and bibliography management.

``CitationSearch`` queries Semantic Scholar (free, no key needed) for
relevant papers. ``BibliographyManager`` builds a ``.bib`` file and
tracks which citations appear in which sections.
"""

from __future__ import annotations

import json
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Citation Search
# ---------------------------------------------------------------------------

class CitationSearch:
    """Search Semantic Scholar for papers relevant to a query.

    Uses the public Semantic Scholar API (rate-limited to ~1 request/sec).
    Results are cached per session to avoid redundant API calls.
    """

    _BASE_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    def __init__(self, cache_dir: Path | str | None = None):
        self._cache_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "deeploop" / "citations"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._session_cache: dict[str, list[dict[str, Any]]] = {}

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Search for papers matching *query*.

        Returns a list of dicts with keys: ``title``, ``authors``, ``year``,
        ``venue``, ``citation_count``, ``bibtex_key``, ``bibtex_entry``,
        ``arxiv_id``, ``abstract``.
        """
        if query in self._session_cache:
            return self._session_cache[query]

        # Check file cache
        cache_path = self._cache_dir / f"{_safe_filename(query)}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                self._session_cache[query] = cached
                return cached
            except Exception:
                pass

        results = self._query_api(query, limit=limit)
        self._session_cache[query] = results

        # Persist to file cache
        try:
            cache_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        except Exception:
            pass

        return results

    def _query_api(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """Call the Semantic Scholar search API."""
        params = {
            "query": query,
            "limit": min(limit, 100),
            "fields": "title,authors,year,venue,citationCount,externalIds,abstract",
        }
        url = f"{self._BASE_URL}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "DeepLoop/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            return []

        papers = data.get("data") or []
        results: list[dict[str, Any]] = []
        for paper in papers:
            title = str(paper.get("title") or "")
            authors_list = paper.get("authors") or []
            authors = ", ".join(
                a.get("name", "") for a in authors_list if isinstance(a, dict)
            )[:200]
            year = paper.get("year")
            venue = str(paper.get("venue") or "")
            citations = int(paper.get("citationCount", 0) or 0)
            external = paper.get("externalIds") or {}
            arxiv_id = str(external.get("ArXiv") or "")
            abstract = str(paper.get("abstract") or "")[:500]

            bibtex_key = _make_bibtex_key(authors_list, year, title)
            bibtex_entry = _make_bibtex_entry(bibtex_key, authors_list, title, year, venue, arxiv_id)

            results.append({
                "title": title,
                "authors": authors,
                "year": year,
                "venue": venue,
                "citation_count": citations,
                "bibtex_key": bibtex_key,
                "bibtex_entry": bibtex_entry,
                "arxiv_id": arxiv_id,
                "abstract": abstract,
            })

            # Respect rate limit
            time.sleep(1.2)

        return results

    def search_for_claims(self, claims: list[str]) -> list[dict[str, Any]]:
        """Search for supporting citations for each claim.

        Deduplicates results by title.
        """
        seen: set[str] = set()
        all_results: list[dict[str, Any]] = []
        for claim in claims:
            for paper in self.search(claim, limit=5):
                title = paper.get("title", "")
                if title.lower() not in seen:
                    seen.add(title.lower())
                    all_results.append(paper)
        return all_results


# ---------------------------------------------------------------------------
# Bibliography Manager
# ---------------------------------------------------------------------------

class BibliographyManager:
    """Manages a ``.bib`` file and tracks citation usage across paper sections."""

    def __init__(self, output_dir: Path | str = "."):
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, str] = {}  # bibtex_key → bibtex_entry
        self._usage: dict[str, list[str]] = {}  # bibtex_key → [section_key, ...]

    def add_entry(self, bibtex_key: str, bibtex_entry: str) -> None:
        """Register a bibliography entry."""
        if bibtex_key not in self._entries:
            self._entries[bibtex_key] = bibtex_entry

    def add_entries_from_search(self, papers: list[dict[str, Any]]) -> None:
        """Register all papers from a CitationSearch result list."""
        for paper in papers:
            key = paper.get("bibtex_key", "")
            entry = paper.get("bibtex_entry", "")
            if key and entry:
                self.add_entry(key, entry)

    def record_usage(self, bibtex_key: str, section: str) -> None:
        """Record that a citation was used in a specific section."""
        if bibtex_key not in self._usage:
            self._usage[bibtex_key] = []
        if section not in self._usage[bibtex_key]:
            self._usage[bibtex_key].append(section)

    def write_bib(self, path: Path | None = None) -> Path:
        """Write the ``.bib`` file."""
        output_path = path or (self._output_dir / "references.bib")
        entries = sorted(self._entries.values())
        output_path.write_text("\n\n".join(entries) + "\n", encoding="utf-8")
        return output_path

    def unused_entries(self) -> list[str]:
        """Return bibtex keys that were added but never cited."""
        return [k for k in self._entries if k not in self._usage]

    def cited_entries(self) -> list[str]:
        """Return bibtex keys that appear at least once in the paper."""
        return list(self._usage.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_filename(query: str) -> str:
    """Convert a search query into a safe filename."""
    import re
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", query.strip().lower())[:80]
    return safe or "citation_cache"


def _make_bibtex_key(authors: list[dict[str, Any]], year: Any, title: str) -> str:
    """Generate a BibTeX citation key (e.g. ``smith2025deep``)."""
    first_author = ""
    if authors:
        first = authors[0]
        if isinstance(first, dict):
            first_author = str(first.get("name", "")).split()[-1].lower()
    first_author = first_author or "unknown"
    year_str = str(year or "????")
    title_words = title.lower().split()[:2]
    title_part = "".join(w[:4] for w in title_words if w.isalpha()) or "paper"
    return f"{first_author}{year_str}{title_part}"


def _make_bibtex_entry(
    key: str,
    authors: list[dict[str, Any]],
    title: str,
    year: Any,
    venue: str,
    arxiv_id: str,
) -> str:
    """Build a BibTeX entry string."""
    author_str = " and ".join(
        a.get("name", "Unknown") for a in authors if isinstance(a, dict)
    ) or "Unknown Author"
    year_str = str(year) if year else ""
    entry_type = "article"
    lines = [f"@{entry_type}{{{key},"]
    lines.append(f"  title = {{{title}}},")
    lines.append(f"  author = {{{author_str}}},")
    if year_str:
        lines.append(f"  year = {{{year_str}}},")
    if venue:
        lines.append(f"  journal = {{{venue}}},")
    if arxiv_id:
        lines.append(f"  archivePrefix = {{arXiv}},")
        lines.append(f"  eprint = {{{arxiv_id}}},")
    lines.append("}")
    return "\n".join(lines)
