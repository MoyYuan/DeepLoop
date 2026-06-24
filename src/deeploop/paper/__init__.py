"""DeepLoop paper generation system.

Produces conference-ready research papers from mission artifacts,
experiment results, and statistical analyses.  Inspired by AI-Scientist's
multi-pass writeup pipeline but built for DeepLoop's structured evidence
model.
"""

from deeploop.paper.templates import (
    ConferenceStyle,
    PaperTemplate,
    SectionSpec,
    get_conference,
    get_section_spec,
    list_conferences,
    list_sections,
)
from deeploop.paper.generator import (
    PaperGenerator,
    build_generation_context,
    generate_paper,
)
from deeploop.paper.figures import FigurePipeline, TablePipeline
from deeploop.paper.citations import BibliographyManager, CitationSearch
from deeploop.paper.reviewer import PaperRefiner, PaperReviewer, Review
from deeploop.paper.stats_integration import StatBlock, StatisticalNarrative

__all__ = [
    # Templates
    "ConferenceStyle",
    "PaperTemplate",
    "SectionSpec",
    "get_conference",
    "get_section_spec",
    "list_conferences",
    "list_sections",
    # Generator
    "PaperGenerator",
    "build_generation_context",
    "generate_paper",
    # Figures & tables
    "FigurePipeline",
    "TablePipeline",
    # Citations
    "BibliographyManager",
    "CitationSearch",
    # Review
    "PaperRefiner",
    "PaperReviewer",
    "Review",
    # Stats
    "StatBlock",
    "StatisticalNarrative",
]
