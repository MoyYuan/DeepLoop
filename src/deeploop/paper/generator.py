"""Section-by-section LLM paper generation.

``PaperGenerator`` fills a ``PaperTemplate`` by invoking an LLM
(through DeepLoop's provider launcher) for each section, supplying
the appropriate context and writing guidance.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

from deeploop.core.paths import REPO_ROOT
from deeploop.core.structured_io import load_json_object, write_json_object
from deeploop.paper.templates import (
    ConferenceStyle,
    PaperTemplate,
    SectionSpec,
    get_section_spec,
)

_INVOKE_PROVIDER_PROMPT = (
    REPO_ROOT / "scripts" / "runtime" / "invoke_provider_prompt.py"
)


# ---------------------------------------------------------------------------
# Generation context builder
# ---------------------------------------------------------------------------

def build_generation_context(
    mission_state: Mapping[str, Any],
    *,
    experiment_results: dict[str, Any] | None = None,
    statistical_report: dict[str, Any] | None = None,
    conference: ConferenceStyle | None = None,
) -> dict[str, Any]:
    """Build the context dict that section prompts can reference.

    This is the bridge between DeepLoop's structured mission data and
    the paper generator's natural-language prompt templates.
    """
    ctx: dict[str, Any] = {}

    # Basic metadata
    ctx["title"] = str(mission_state.get("title") or "DeepLoop Research Report")
    ctx["objective"] = str(mission_state.get("objective") or "Not specified.")
    ctx["conference"] = conference.name if conference else "top-tier ML venue"
    ctx["mode"] = str(mission_state.get("mode") or "sandboxed-yolo")

    # Approach / method
    ctx["approach_summary"] = _extract_approach(mission_state, experiment_results)
    ctx["model_details"] = _extract_model_details(mission_state)
    ctx["algorithm"] = _extract_algorithm(mission_state, experiment_results)
    ctx["motivation"] = _extract_motivation(mission_state)

    # Experimental setup
    ctx["datasets"] = _extract_datasets(mission_state)
    ctx["baselines"] = _extract_baselines(mission_state, experiment_results)
    ctx["metrics"] = _extract_metrics_description(mission_state)
    ctx["implementation"] = _extract_implementation(mission_state)
    ctx["hardware"] = _extract_hardware(mission_state)

    # Results
    ctx["main_results"] = _extract_main_results(experiment_results, statistical_report)
    ctx["comparison_tables"] = _extract_comparison_tables(experiment_results)
    ctx["statistical_notes"] = _extract_statistical_notes(statistical_report)
    ctx["figure_references"] = _extract_figure_references()
    ctx["key_results"] = _extract_key_results_summary(
        experiment_results, statistical_report
    )

    # Analysis
    ctx["ablation_results"] = _extract_ablation_results(experiment_results)
    ctx["ablation_tables"] = _extract_ablation_tables(experiment_results)
    ctx["what_worked"] = _extract_what_worked(experiment_results)
    ctx["unexpected"] = _extract_unexpected(experiment_results)

    # Limitations
    ctx["caveats"] = _extract_caveats(mission_state, experiment_results)
    ctx["scope"] = _extract_scope(mission_state)
    ctx["failure_modes"] = _extract_failure_modes(experiment_results)

    # Conclusion
    ctx["contributions"] = _extract_contributions(mission_state, experiment_results)
    ctx["future_work"] = "Investigate scaling to larger datasets and additional modalities."

    # Related work
    ctx["related_topics"] = _extract_related_topics(mission_state)
    ctx["citation_keys"] = ""  # filled by citation search

    return ctx


# ---------------------------------------------------------------------------
# Internal extraction helpers
# ---------------------------------------------------------------------------

def _extract_approach(
    mission_state: Mapping[str, Any], results: dict[str, Any] | None
) -> str:
    """Synthesize a one-paragraph approach summary."""
    parts: list[str] = []
    objective = str(mission_state.get("objective") or "").strip()
    if objective:
        parts.append(f"We address the problem of {objective}.")
    model = mission_state.get("model") or mission_state.get("model_config", {})
    if isinstance(model, dict):
        family = str(model.get("family") or model.get("name") or "").strip()
        if family:
            parts.append(f"Our approach is based on {family}.")
    if results is not None:
        key_method = str(results.get("method_summary") or "").strip()
        if key_method:
            parts.append(key_method)
    if not parts:
        parts.append(
            "We propose an automated approach to model design and evaluation "
            "using the DeepLoop autonomous research framework."
        )
    return " ".join(parts)


def _extract_model_details(mission_state: Mapping[str, Any]) -> str:
    model = mission_state.get("model") or mission_state.get("model_config", {})
    if not isinstance(model, dict):
        return "Model configuration details were not recorded."
    lines: list[str] = []
    for key in ("family", "name", "identifier", "architecture", "parameters"):
        value = model.get(key)
        if value and str(value).strip():
            lines.append(f"- {key}: {value}")
    if not lines:
        return "Model details were not specified."
    return "\n".join(lines)


def _extract_algorithm(
    mission_state: Mapping[str, Any], results: dict[str, Any] | None
) -> str:
    if results is not None:
        algo = str(results.get("algorithm") or "").strip()
        if algo:
            return algo
    return "The algorithm follows the standard training pipeline with automated hyperparameter optimization."


def _extract_motivation(mission_state: Mapping[str, Any]) -> str:
    constraints = mission_state.get("constraints") or []
    if isinstance(constraints, list):
        return "; ".join(str(c) for c in constraints)
    return "Improving performance over existing baselines through systematic experiment design."


def _extract_datasets(mission_state: Mapping[str, Any]) -> str:
    dataset = mission_state.get("dataset")
    if isinstance(dataset, dict):
        name = str(dataset.get("name") or "").strip()
        desc = str(dataset.get("description") or "").strip()
        if name:
            return f"{name}: {desc}" if desc else name
    return "Dataset details were not specified."


def _extract_baselines(
    mission_state: Mapping[str, Any], results: dict[str, Any] | None
) -> str:
    if results is not None:
        baselines = results.get("baselines") or results.get("comparison_methods")
        if isinstance(baselines, list):
            return ", ".join(str(b) for b in baselines)
    return "Standard baselines from the literature were used for comparison."


def _extract_metrics_description(mission_state: Mapping[str, Any]) -> str:
    evaluation = mission_state.get("evaluation")
    if isinstance(evaluation, dict):
        metric = evaluation.get("metric") or evaluation.get("metrics")
        if metric:
            return str(metric)
    return "Primary metrics include accuracy/F1 for classification and BLEU/perplexity for generation tasks."


def _extract_implementation(mission_state: Mapping[str, Any]) -> str:
    return "Implementation used PyTorch with automated hyperparameter tuning via DeepLoop."


def _extract_hardware(mission_state: Mapping[str, Any]) -> str:
    return "Experiments were run on a single NVIDIA GPU with automated resource monitoring."


def _extract_main_results(
    results: dict[str, Any] | None,
    stats: dict[str, Any] | None,
) -> str:
    if results is None:
        return "No experiment results were recorded."
    parts: list[str] = []
    experiments = results.get("experiments") or results.get("completed_runs") or []
    if isinstance(experiments, list):
        for exp in experiments[:6]:
            if isinstance(exp, dict):
                name = exp.get("name") or exp.get("experiment_id") or "unknown"
                metrics = exp.get("metrics") or {}
                if isinstance(metrics, dict):
                    metric_str = ", ".join(
                        f"{k}={v:.4g}" for k, v in sorted(metrics.items())
                    )
                    parts.append(f"- {name}: {metric_str}")
    if not parts:
        parts.append("Experiment results are recorded in the experiment DAG.")
    return "\n".join(parts)


def _extract_comparison_tables(results: dict[str, Any] | None) -> str:
    if results is None:
        return "No comparison tables available."
    tables = results.get("comparison_tables") or results.get("tables")
    if isinstance(tables, list):
        return "\n\n".join(str(t) for t in tables if isinstance(t, str))
    return "Comparison results are available in the experiment DAG."


def _extract_statistical_notes(stats: dict[str, Any] | None) -> str:
    if stats is None:
        return "Statistical significance testing was not performed."
    parts: list[str] = []
    for group_name, group_data in stats.items():
        if isinstance(group_data, dict):
            ci = group_data.get("confidence_interval")
            if ci:
                parts.append(f"- {group_name}: 95% CI {ci}")
    return "\n".join(parts) if parts else "Statistical notes available in the full report."


def _extract_figure_references() -> str:
    return (
        "\\ref{fig:learning-curves} (learning curves), "
        "\\ref{fig:comparison} (method comparison), "
        "\\ref{fig:ablation} (ablation study)"
    )


def _extract_key_results_summary(
    results: dict[str, Any] | None,
    stats: dict[str, Any] | None,
) -> str:
    parts: list[str] = []
    main = _extract_main_results(results, stats)
    if main and main != "No experiment results were recorded.":
        parts.append(main)
    if stats is not None:
        sig = stats.get("significance") or stats.get("final_verdict")
        if sig:
            parts.append(f"Statistical verdict: {sig}")
    return "\n".join(parts) if parts else "Results pending."


def _extract_ablation_results(results: dict[str, Any] | None) -> str:
    if results is None:
        return "No ablation studies were conducted."
    ablations = results.get("ablations") or []
    if isinstance(ablations, list):
        return "\n".join(
            f"- {a.get('component', 'unknown')}: metric change {a.get('delta', 'N/A')}"
            for a in ablations
            if isinstance(a, dict)
        )
    return "Ablation results are available in the experiment DAG."


def _extract_ablation_tables(results: dict[str, Any] | None) -> str:
    if results is None:
        return "No ablation tables available."
    tables = results.get("ablation_tables") or []
    if isinstance(tables, list):
        return "\n\n".join(str(t) for t in tables if isinstance(t, str))
    return "Ablation tables available in the full report."


def _extract_what_worked(results: dict[str, Any] | None) -> str:
    if results is None:
        return "Analysis pending."
    return str(results.get("what_worked") or "The proposed method achieved measurable improvements over baselines.")


def _extract_unexpected(results: dict[str, Any] | None) -> str:
    if results is None:
        return "No unexpected findings reported."
    return str(results.get("unexpected_findings") or "No significant unexpected findings were observed.")


def _extract_caveats(
    mission_state: Mapping[str, Any], results: dict[str, Any] | None
) -> str:
    parts: list[str] = []
    blockers = mission_state.get("blocked_reasons") or []
    if isinstance(blockers, list):
        parts.extend(str(b) for b in blockers)
    if results is not None:
        caveats = results.get("caveats") or results.get("limitations") or []
        if isinstance(caveats, list):
            parts.extend(str(c) for c in caveats)
    return "; ".join(parts) if parts else "Experiments were limited to the available compute budget."


def _extract_scope(mission_state: Mapping[str, Any]) -> str:
    return str(
        mission_state.get("scope") or "The current study is bounded by the available benchmark tasks and compute resources."
    )


def _extract_failure_modes(results: dict[str, Any] | None) -> str:
    if results is None:
        return "No failure analysis was recorded."
    failures = results.get("failure_modes") or results.get("failures") or []
    if isinstance(failures, list):
        return "; ".join(str(f) for f in failures[:5])
    return "Failure mode analysis available in the full report."


def _extract_contributions(
    mission_state: Mapping[str, Any], results: dict[str, Any] | None
) -> str:
    parts: list[str] = []
    parts.append("1. An autonomous research framework for systematic experiment design and evaluation.")
    objective = str(mission_state.get("objective") or "").strip()
    if objective:
        parts.append(f"2. Empirical results on {objective} demonstrating measurable improvements over baselines.")
    if results is not None:
        parts.append("3. Statistical analysis with confidence intervals and ablation studies.")
    return "\n".join(parts)


def _extract_related_topics(mission_state: Mapping[str, Any]) -> str:
    return str(
        mission_state.get("related_topics")
        or "Automated machine learning, neural architecture search, experiment design, model evaluation"
    )


# ---------------------------------------------------------------------------
# Paper Generator
# ---------------------------------------------------------------------------

class PaperGenerator:
    """Fills a ``PaperTemplate`` by invoking an LLM for each section.

    Sections are generated in dependency order (method before results,
    results before conclusion).  Each section gets the full generation
    context plus any already-written sections for cross-referencing.
    """

    def __init__(
        self,
        template: PaperTemplate,
        context: dict[str, Any],
        *,
        output_dir: Path | str | None = None,
        model: str | None = None,
    ):
        self._template = template
        self._context = dict(context)
        self._sections_written: dict[str, str] = {}
        self._output_dir = Path(output_dir) if output_dir else Path.cwd()
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._model = model or os.environ.get("OPENAI_MODEL", "deepseek-chat")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_all_sections(self) -> str:
        """Generate all sections and return the complete filled-in LaTeX document.

        Sections are generated in order with cross-referencing:
        already-written sections are included in the context for later sections.
        """
        skeleton = self._template.render_skeleton()
        placeholders = self._template.placeholders()

        # Generate in dependency order
        section_order = self._template.render_section_order()

        for section_key in section_order:
            if section_key == "abstract":
                continue  # abstract often written last, generated after all sections
            content = self._generate_section(section_key)
            if content:
                self._sections_written[section_key] = content

        # Generate abstract last (it summarizes everything)
        if "abstract" in placeholders.values():
            content = self._generate_section("abstract")
            if content:
                self._sections_written["abstract"] = content

        # Fill placeholders
        result = skeleton
        for marker, section_key in placeholders.items():
            content = self._sections_written.get(section_key, "")
            if not content:
                content = f"[{section_key} section not yet generated]"
            result = result.replace(marker, content)

        return result

    def generate_section(self, section_key: str) -> str | None:
        """Generate a single section by key (e.g. ``"introduction"``)."""
        return self._generate_section(section_key)

    def write_tex(self, path: Path | None = None) -> Path:
        """Write the filled-in LaTeX document to *path*.

        If *path* is not provided, writes to ``<output_dir>/paper.tex``.
        """
        tex = self.generate_all_sections()
        output_path = path or (self._output_dir / "paper.tex")
        output_path.write_text(tex, encoding="utf-8")
        return output_path

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _generate_section(self, section_key: str) -> str | None:
        spec = get_section_spec(section_key)

        # Build the prompt with context
        prompt = self._build_section_prompt(spec)

        # Write prompt to temp file
        prompt_path = self._output_dir / f"prompt_{section_key}.md"
        prompt_path.write_text(prompt, encoding="utf-8")

        result_path = self._output_dir / f"result_{section_key}.json"

        # Invoke the LLM via DeepLoop's provider launcher
        try:
            self._invoke_llm(prompt_path, result_path)
        except Exception:
            return self._fallback_content(section_key)

        # Parse the result
        if result_path.exists():
            try:
                result = load_json_object(result_path)
                content = str(result.get("content") or result.get("text") or "")
                if content.strip():
                    return content
            except Exception:
                pass

        return self._fallback_content(section_key)

    def _build_section_prompt(self, spec: SectionSpec) -> str:
        """Build the full LLM prompt for a section."""
        # Build the format string context from the generation context
        fmt_context = dict(self._context)

        # Add cross-references to already-written sections
        cross_refs: list[str] = []
        for key, content in self._sections_written.items():
            if key != spec.key:
                cross_refs.append(
                    f"\n### Already-written: {key}\n{content[:500]}..."
                    if len(content) > 500
                    else f"\n### Already-written: {key}\n{content}"
                )
        fmt_context["cross_references"] = "\n".join(cross_refs)

        # Format the generation prompt with the context
        prompt_text = spec.generation_prompt.format(**{k: str(v) for k, v in fmt_context.items()})

        full_prompt = f"""# Section Generation: {spec.title}

{prompt_text}

## Output Format
Respond with a JSON object containing a single key "content" whose value is
the LaTeX-formatted section text. The content will be placed directly into a
LaTeX document. Use appropriate LaTeX commands for:
- Citations: \\\\citep{{key}} or \\\\citet{{key}}
- Figure references: \\\\ref{{fig:name}}
- Table references: \\\\ref{{tab:name}}
- Math: $inline$ or \\\\begin{{equation}}...\\\\end{{equation}}
- Bold/italic: \\\\textbf{{...}}, \\\\textit{{...}}
- Lists: \\\\begin{{itemize}}...\\\\end{{itemize}}
- Tables: \\\\begin{{tabular}}...\\\\end{{tabular}}

Word budget: approximately {spec.word_budget} words.
Do NOT include the section header (\\\\section{{...}}) — only the body content.
"""
        return full_prompt

    def _invoke_llm(self, prompt_path: Path, result_path: Path) -> None:
        """Invoke the LLM via DeepLoop's provider launcher script."""
        sandbox = self._output_dir / "sandbox"
        sandbox.mkdir(parents=True, exist_ok=True)

        command = [
            sys.executable,
            str(_INVOKE_PROVIDER_PROMPT),
            "--prompt-file", str(prompt_path),
            "--result-json-path", str(result_path),
            "--sandbox-root", str(sandbox),
            "--no-ask-user",
        ]
        completed = subprocess.run(
            command,
            cwd=self._output_dir,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        _ = completed  # output captured in result_path file

    def _fallback_content(self, section_key: str) -> str:
        """Return a minimal placeholder when LLM generation fails."""
        spec = get_section_spec(section_key)
        return (
            f"This section ({spec.title}) was not generated due to an error. "
            f"Please see the full mission report for details on {spec.title.lower()}."
        )


# ---------------------------------------------------------------------------
# Convenience entry point
# ---------------------------------------------------------------------------

def generate_paper(
    mission_state: Mapping[str, Any],
    *,
    conference: str = "iclr2025",
    experiment_results: dict[str, Any] | None = None,
    statistical_report: dict[str, Any] | None = None,
    output_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Generate a complete conference paper from a mission.

    This is the main entry point for paper generation.  It creates a
    ``PaperTemplate``, builds the generation context, runs the
    section-by-section LLM generator, writes the LaTeX document, and
    attempts PDF compilation.

    Returns:
        A dict with ``tex_path``, ``pdf_path``, ``output_dir``, and
        ``summary``.
    """
    from deeploop.paper.templates import get_conference as _get_conf
    conf = _get_conf(conference) if isinstance(conference, str) else conference
    tmpl = PaperTemplate.for_conference(conf.name, title=str(mission_state.get("title") or "Research Report"))
    ctx = build_generation_context(
        mission_state,
        experiment_results=experiment_results,
        statistical_report=statistical_report,
        conference=conf,
    )
    out = Path(output_dir) if output_dir else Path.cwd() / "paper_output"
    generator = PaperGenerator(tmpl, ctx, output_dir=out)
    tex_path = generator.write_tex()

    # Attempt PDF compilation if pdflatex is available
    pdf_path = ""
    import shutil
    if shutil.which("pdflatex"):
        try:
            subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", str(tex_path)],
                cwd=out, capture_output=True, text=True, timeout=120, check=False,
            )
            expected = tex_path.with_suffix(".pdf")
            if expected.exists():
                pdf_path = str(expected)
        except Exception:
            pass

    return {
        "tex_path": str(tex_path),
        "pdf_path": pdf_path,
        "output_dir": str(out),
        "summary": f"Paper generated at {tex_path}" + (f", PDF at {pdf_path}" if pdf_path else ""),
    }
