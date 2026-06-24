"""Conference-grade LaTeX template management.

Provides a ``PaperTemplate`` class that loads conference-specific
style files and renders a complete paper skeleton with placeholder
markers that the section generator can fill in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Conference definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConferenceStyle:
    """Metadata and LaTeX requirements for a specific venue."""

    name: str
    """Short identifier (``"iclr2025"``, ``"neurips2025"``, ``"icml2025"``)."""

    document_class: str = "article"
    """LaTeX document class with options (e.g. ``"article"``)."""

    style_packages: tuple[str, ...] = ()
    """Required ``\\usepackage{...}`` lines."""

    author_block: str = "\\author{DeepLoop Autonomous Research}"
    """LaTeX for the author block (may include ``\\thanks``, affiliations)."""

    title_page_extra: str = ""
    """Extra LaTeX inserted on the title page (e.g. abstract formatting)."""

    page_limit: int = 9
    """Page limit for the main text (excluding references/appendices)."""

    anonymize: bool = False
    """Whether the venue requires double-blind anonymization."""

    required_sections: tuple[str, ...] = (
        "abstract",
        "introduction",
        "related-work",
        "method",
        "experimental-setup",
        "results",
        "analysis",
        "limitations",
        "conclusion",
    )
    """Ordered list of required section keys."""

    optional_sections: tuple[str, ...] = (
        "background",
        "preliminaries",
        "ablation",
        "appendix",
    )
    """Sections that may be included but are not mandatory."""


# ---------------------------------------------------------------------------
# Pre-built conference definitions
# ---------------------------------------------------------------------------

ICLR_STYLE = ConferenceStyle(
    name="iclr2025",
    document_class="article",
    style_packages=(
        "\\usepackage[preprint]{iclr2025_conference}",
        "\\usepackage{times}",
        "\\usepackage{graphicx}",
        "\\usepackage{amsmath}",
        "\\usepackage{amssymb}",
        "\\usepackage{booktabs}",
        "\\usepackage{hyperref}",
        "\\usepackage{xcolor}",
        "\\usepackage{algorithm}",
        "\\usepackage{algorithmic}",
        "\\usepackage{subfigure}",
        "\\usepackage{natbib}",
        "\\usepackage{multirow}",
        "\\usepackage{makecell}",
    ),
    author_block=(
        "\\author{Anonymous Authors}\n"
        "\\newcommand{\\theauthor}{Anonymous Authors}"
    ),
    title_page_extra=(
        "\\iclrheader\n"
        "\\maketitle\n"
    ),
    anonymize=True,
    page_limit=9,
)

NEURIPS_STYLE = ConferenceStyle(
    name="neurips2025",
    document_class="article",
    style_packages=(
        "\\usepackage{neurips_2025}",
        "\\usepackage{times}",
        "\\usepackage{graphicx}",
        "\\usepackage{amsmath}",
        "\\usepackage{amssymb}",
        "\\usepackage{booktabs}",
        "\\usepackage{hyperref}",
        "\\usepackage{xcolor}",
        "\\usepackage{algorithm}",
        "\\usepackage{algorithmic}",
        "\\usepackage{subfigure}",
        "\\usepackage{natbib}",
        "\\usepackage{multirow}",
        "\\usepackage{makecell}",
        "\\usepackage{cleveref}",
    ),
    author_block=(
        "\\author{Anonymous Authors}"
    ),
    title_page_extra=(
        "\\begin{abstract}<<ABSTRACT>>\\end{abstract}\n"
        "\\maketitle\n"
    ),
    anonymize=True,
    page_limit=9,
)

ICML_STYLE = ConferenceStyle(
    name="icml2025",
    document_class="article",
    style_packages=(
        "\\usepackage{icml2025}",
        "\\usepackage{times}",
        "\\usepackage{graphicx}",
        "\\usepackage{amsmath}",
        "\\usepackage{amssymb}",
        "\\usepackage{booktabs}",
        "\\usepackage{hyperref}",
        "\\usepackage{xcolor}",
        "\\usepackage{algorithm}",
        "\\usepackage{algorithmic}",
        "\\usepackage{subfigure}",
        "\\usepackage{natbib}",
        "\\usepackage{multirow}",
        "\\usepackage{makecell}",
    ),
    author_block=(
        "\\author{Anonymous Authors}"
    ),
    title_page_extra=(
        "\\maketitle\n"
    ),
    anonymize=True,
    page_limit=8,
)


# Registry for quick lookup
_CONFERENCES: dict[str, ConferenceStyle] = {
    "iclr2025": ICLR_STYLE,
    "iclr": ICLR_STYLE,
    "neurips2025": NEURIPS_STYLE,
    "neurips": NEURIPS_STYLE,
    "icml2025": ICML_STYLE,
    "icml": ICML_STYLE,
}


# ---------------------------------------------------------------------------
# Section definitions
# ---------------------------------------------------------------------------

@dataclass
class SectionSpec:
    """Defines one section of the paper: its LaTeX structure, generation
    prompt, and context requirements."""

    key: str
    """Machine-readable key (``"introduction"``, ``"results"``, ...)."""

    title: str
    """Human-readable section title (``"Introduction"``)."""

    latex_command: str
    """LaTeX sectioning command, e.g. ``"\\section{<<TITLE>>}"``."""

    generation_prompt: str
    """Prompt template for the LLM that writes this section.

    May include ``{context}``, ``{title}``, ``{objective}``, and other
    template variables that the generator fills in.
    """

    context_keys: tuple[str, ...] = ()
    """Keys into the generation context dict that this section needs."""

    word_budget: int = 400
    """Approximate word budget for this section."""


# Shipped section specifications
_SECTION_SPECS: list[SectionSpec] = [
    SectionSpec(
        key="abstract",
        title="Abstract",
        latex_command="\\begin{abstract}<<CONTENT>>\\end{abstract}",
        generation_prompt=(
            "Write a concise abstract for a machine learning research paper "
            "titled \"{title}\". The paper's objective is: {objective}.\n\n"
            "Key results: {key_results}\n\n"
            "Write 150-250 words. Be specific about the contribution, method, "
            "and quantitative results. Use academic style suitable for a "
            "top-tier ML venue ({conference})."
        ),
        context_keys=("title", "objective", "key_results", "conference"),
        word_budget=200,
    ),
    SectionSpec(
        key="introduction",
        title="Introduction",
        latex_command="\\section{<<TITLE>>}\n<<CONTENT>>",
        generation_prompt=(
            "Write the Introduction section for a machine learning research "
            "paper titled \"{title}\".\n\n"
            "Objective: {objective}\n"
            "Motivation and gap: {motivation}\n"
            "Proposed approach: {approach_summary}\n\n"
            "Structure the introduction as: (1) problem context and importance, "
            "(2) limitations of existing approaches, (3) our proposed approach "
            "and key insight, (4) main contributions (as a numbered list), "
            "(5) paper roadmap. Write 400-600 words in academic style. "
            "Do NOT include subsection headers. Target venue: {conference}."
        ),
        context_keys=("title", "objective", "motivation", "approach_summary", "conference"),
        word_budget=500,
    ),
    SectionSpec(
        key="related-work",
        title="Related Work",
        latex_command="\\section{<<TITLE>>}\n<<CONTENT>>",
        generation_prompt=(
            "Write the Related Work section for a machine learning paper "
            "titled \"{title}\".\n\n"
            "Our approach: {approach_summary}\n"
            "Related topics to cover: {related_topics}\n"
            "Key citations with BibTeX keys: {citation_keys}\n\n"
            "Organize by topic area, not chronologically. For each area, "
            "describe 2-4 representative works, their contributions, and "
            "their limitations relative to our approach. Use \\citep{{...}} "
            "for citations. Write 400-600 words. Target venue: {conference}."
        ),
        context_keys=("title", "approach_summary", "related_topics", "citation_keys", "conference"),
        word_budget=500,
    ),
    SectionSpec(
        key="method",
        title="Method",
        latex_command="\\section{<<TITLE>>}\n<<CONTENT>>",
        generation_prompt=(
            "Write the Method section for a machine learning research paper "
            "titled \"{title}\".\n\n"
            "Approach description: {approach_summary}\n"
            "Model details: {model_details}\n"
            "Algorithm description: {algorithm}\n\n"
            "Provide formal problem setup, notation, and a clear description "
            "of the proposed method. Use mathematical notation where appropriate "
            "(\\begin{{equation}}...\\end{{equation}} or inline $...$). "
            "Include algorithm pseudocode if relevant. Write 500-800 words. "
            "Target venue: {conference}."
        ),
        context_keys=("title", "approach_summary", "model_details", "algorithm", "conference"),
        word_budget=600,
    ),
    SectionSpec(
        key="experimental-setup",
        title="Experimental Setup",
        latex_command="\\section{<<TITLE>>}\n<<CONTENT>>",
        generation_prompt=(
            "Write the Experimental Setup section for a machine learning "
            "paper titled \"{title}\".\n\n"
            "Datasets: {datasets}\n"
            "Baselines: {baselines}\n"
            "Evaluation metrics: {metrics}\n"
            "Implementation details: {implementation}\n"
            "Hardware: {hardware}\n\n"
            "Describe each dataset, the baselines used for comparison, the "
            "evaluation protocol (train/val/test splits, cross-validation), "
            "hyperparameters, and compute resources. Be specific enough for "
            "reproducibility. Use \\texttt{{...}} for code/config references. "
            "Write 300-500 words. Target venue: {conference}."
        ),
        context_keys=("title", "datasets", "baselines", "metrics", "implementation", "hardware", "conference"),
        word_budget=400,
    ),
    SectionSpec(
        key="results",
        title="Results",
        latex_command="\\section{<<TITLE>>}\n<<CONTENT>>",
        generation_prompt=(
            "Write the Results section for a machine learning research paper "
            "titled \"{title}\".\n\n"
            "Main results: {main_results}\n"
            "Comparison tables (LaTeX): {comparison_tables}\n"
            "Statistical notes: {statistical_notes}\n"
            "Figures referenced: {figure_references}\n\n"
            "Present the quantitative results clearly. Reference each figure "
            "and table with \\ref{{...}}. Describe the key findings: which "
            "method performs best, by how much, and whether the difference "
            "is statistically significant. Report confidence intervals and "
            "p-values where available. Do NOT interpret results here (save "
            "that for Analysis). Write 400-600 words. "
            "Target venue: {conference}."
        ),
        context_keys=("title", "main_results", "comparison_tables", "statistical_notes", "figure_references", "conference"),
        word_budget=500,
    ),
    SectionSpec(
        key="analysis",
        title="Analysis and Discussion",
        latex_command="\\section{<<TITLE>>}\n<<CONTENT>>",
        generation_prompt=(
            "Write the Analysis and Discussion section for a machine learning "
            "paper titled \"{title}\".\n\n"
            "Ablation results: {ablation_results}\n"
            "Ablation tables (LaTeX): {ablation_tables}\n"
            "What worked: {what_worked}\n"
            "Unexpected findings: {unexpected}\n\n"
            "Interpret the results: why does the proposed method outperform "
            "baselines? What do the ablation studies reveal about each "
            "component's contribution? Discuss any surprising or unexpected "
            "outcomes. Connect findings back to the motivation in the "
            "introduction. Write 300-500 words. Target venue: {conference}."
        ),
        context_keys=("title", "ablation_results", "ablation_tables", "what_worked", "unexpected", "conference"),
        word_budget=400,
    ),
    SectionSpec(
        key="limitations",
        title="Limitations",
        latex_command="\\section{<<TITLE>>}\n<<CONTENT>>",
        generation_prompt=(
            "Write the Limitations section for a machine learning research "
            "paper titled \"{title}\".\n\n"
            "Known caveats: {caveats}\n"
            "Scope boundary: {scope}\n"
            "Failure modes observed: {failure_modes}\n\n"
            "Honestly describe the limitations of the proposed approach: "
            "what it cannot do, where it fails, assumptions that may not "
            "hold, and scope of the experimental validation. Be specific. "
            "Write 150-250 words. Target venue: {conference}."
        ),
        context_keys=("title", "caveats", "scope", "failure_modes", "conference"),
        word_budget=200,
    ),
    SectionSpec(
        key="conclusion",
        title="Conclusion",
        latex_command="\\section{<<TITLE>>}\n<<CONTENT>>",
        generation_prompt=(
            "Write the Conclusion section for a machine learning research "
            "paper titled \"{title}\".\n\n"
            "Main contributions: {contributions}\n"
            "Key results summary: {key_results}\n"
            "Future work: {future_work}\n\n"
            "Summarize the paper's contributions and main findings. "
            "Briefly mention promising directions for future work. "
            "Do NOT introduce new results. Write 150-250 words. "
            "Target venue: {conference}."
        ),
        context_keys=("title", "contributions", "key_results", "future_work", "conference"),
        word_budget=200,
    ),
]


# Index by key for fast lookup
_SECTION_SPEC_BY_KEY: dict[str, SectionSpec] = {
    spec.key: spec for spec in _SECTION_SPECS
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_conferences() -> list[str]:
    """Return the canonical identifiers of supported conferences."""
    return sorted({"iclr2025", "neurips2025", "icml2025"})


def get_conference(name: str) -> ConferenceStyle:
    """Look up a conference style by name (e.g. ``"iclr2025"``).

    Raises:
        KeyError: If *name* is not recognized.
    """
    key = name.strip().lower()
    if key not in _CONFERENCES:
        available = ", ".join(sorted(_CONFERENCES))
        raise KeyError(f"Unknown conference `{name}`. Available: {available}.")
    return _CONFERENCES[key]


def list_sections() -> list[str]:
    """Return the canonical section keys in default order."""
    return [spec.key for spec in _SECTION_SPECS]


def get_section_spec(key: str) -> SectionSpec:
    """Look up a section specification by key.

    Raises:
        KeyError: If *key* is not recognized.
    """
    if key not in _SECTION_SPEC_BY_KEY:
        available = ", ".join(_SECTION_SPEC_BY_KEY)
        raise KeyError(f"Unknown section `{key}`. Available: {available}.")
    return _SECTION_SPEC_BY_KEY[key]


@dataclass
class PaperTemplate:
    """A complete paper template for a specific conference.

    Renders a skeleton LaTeX document with all sections and placeholder
    markers ready for a section-by-section LLM generator to fill in.
    """

    conference: ConferenceStyle
    title: str = "Research Report"
    sections: list[SectionSpec] = field(default_factory=lambda: list(_SECTION_SPECS))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render_skeleton(self) -> str:
        """Render a compilable LaTeX document skeleton.

        Every section body is replaced with a unique placeholder marker
        that ``PaperGenerator`` can target for LLM-driven filling.
        """
        lines: list[str] = []

        # Preamble
        lines.append(f"\\documentclass{{{self.conference.document_class}}}")
        for pkg in self.conference.style_packages:
            lines.append(pkg)
        lines.append("")

        # Title
        if self.conference.anonymize:
            lines.append(f"\\title{{{self.title}}}")
        else:
            lines.append(f"\\title{{{self.title}}}")
            lines.append(self.conference.author_block)
        lines.append("")

        lines.append("\\begin{document}")
        lines.append("")

        # Title page
        if self.conference.anonymize:
            lines.append(self.conference.author_block)
        if self.conference.title_page_extra:
            lines.append(self.conference.title_page_extra.strip())
        lines.append("")

        # Abstract (special handling — many conferences use a custom env)
        abstract_spec = _SECTION_SPEC_BY_KEY.get("abstract")
        if abstract_spec and "abstract" in {s.key for s in self.sections}:
            lines.append(
                abstract_spec.latex_command.replace("<<CONTENT>>", "<<ABSTRACT_CONTENT>>")
            )
            lines.append("")

        # Regular sections
        for spec in self.sections:
            if spec.key == "abstract":
                continue  # handled above
            placeholder = f"<<{spec.key.upper().replace('-', '_')}_CONTENT>>"
            cmd = spec.latex_command.replace("<<TITLE>>", spec.title).replace(
                "<<CONTENT>>", placeholder
            )
            lines.append(cmd)
            lines.append("")

        # Bibliography
        lines.append("\\bibliographystyle{plainnat}")
        lines.append("\\bibliography{references}")
        lines.append("")

        # Appendix for optional sections
        appendix_specs = [s for s in self.sections if s.key in self.conference.optional_sections]
        if appendix_specs:
            lines.append("\\appendix")
            lines.append("")
            for spec in appendix_specs:
                placeholder = f"<<{spec.key.upper().replace('-', '_')}_CONTENT>>"
                cmd = spec.latex_command.replace("<<TITLE>>", spec.title).replace(
                    "<<CONTENT>>", placeholder
                )
                lines.append(cmd)
                lines.append("")

        lines.append("\\end{document}")
        return "\n".join(lines) + "\n"

    def render_section_order(self) -> list[str]:
        """Return the ordered list of section keys for this template."""
        return [s.key for s in self.sections]

    @classmethod
    def for_conference(cls, name: str, *, title: str = "Research Report") -> "PaperTemplate":
        """Factory: create a template for a named conference."""
        conf = get_conference(name)
        required = [
            s for s in _SECTION_SPECS
            if s.key in conf.required_sections
        ]
        # Inject optional sections that have specs
        for opt_key in conf.optional_sections:
            opt_spec = _SECTION_SPEC_BY_KEY.get(opt_key)
            if opt_spec is not None:
                required.append(opt_spec)
        return cls(conference=conf, title=title, sections=required)

    # ------------------------------------------------------------------
    # Placeholder extraction (used by the generator)
    # ------------------------------------------------------------------

    def placeholders(self) -> dict[str, str]:
        """Return a mapping of placeholder marker → section key."""
        mapping: dict[str, str] = {}
        for spec in self.sections:
            marker = f"<<{spec.key.upper().replace('-', '_')}_CONTENT>>"
            mapping[marker] = spec.key
        if _SECTION_SPEC_BY_KEY.get("abstract"):
            mapping["<<ABSTRACT_CONTENT>>"] = "abstract"
        return mapping
