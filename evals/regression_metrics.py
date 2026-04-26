"""
Regression metrics for evaluating research agent output quality.

Metrics:
  1. ROUGE-L        — lexical overlap (fast, no model needed)
  2. BERTScore      — semantic similarity (requires bert-score package)
  3. Answer length  — basic sanity check
  4. Source overlap — did expected domains appear in sources?
  5. LLM judge      — coherence + relevance (uses OpenAI, costs ~$0.001/query)

Install extras:
  uv add rouge-score bert-score
"""

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class MetricResult:
    rouge_l: float = 0.0
    bert_score_f1: float = 0.0
    answer_length: int = 0
    source_overlap: float = 0.0  # % of expected sources found
    length_ok: bool = True  # answer >= min_length
    available_metrics: list[str] = field(default_factory=list)


def compute_rouge_l(prediction: str, reference: str) -> float:
    """
    Compute ROUGE-L F1 score between prediction and reference.
    Fast — no model needed, pure Python.
    Returns 0.0 if rouge-score not installed.
    """
    try:
        from rouge_score import rouge_scorer

        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        scores = scorer.score(reference, prediction)
        return round(scores["rougeL"].fmeasure, 4)
    except ImportError:
        log.warning("rouge-score not installed — skipping ROUGE-L (run: uv add rouge-score)")
        return 0.0
    except Exception as exc:
        log.warning("ROUGE-L computation failed: %s", exc)
        return 0.0


def compute_bert_score(predictions: list[str], references: list[str]) -> list[float]:
    """
    Compute BERTScore F1 for a batch of predictions vs references.
    Captures semantic regressions that ROUGE misses (paraphrasing, synonyms).
    Returns list of 0.0 if bert-score not installed.
    """
    try:
        from bert_score import score as bert_score_fn

        _, _, F1 = bert_score_fn(
            predictions,
            references,
            lang="en",
            model_type="distilbert-base-uncased",
            verbose=False,
        )
        return [round(f.item(), 4) for f in F1]
    except ImportError:
        log.warning("bert-score not installed — skipping BERTScore (run: uv add bert-score)")
        return [0.0] * len(predictions)
    except Exception as exc:
        log.warning("BERTScore computation failed: %s", exc)
        return [0.0] * len(predictions)


def compute_source_overlap(actual_sources: list[str], expected_domains: list[str]) -> float:
    """
    Check what fraction of expected domains appear in actual sources.
    Returns 1.0 if no expected domains specified (not applicable).
    """
    if not expected_domains:
        return 1.0
    found = sum(
        1
        for domain in expected_domains
        if any(domain.lower() in url.lower() for url in actual_sources)
    )
    return round(found / len(expected_domains), 3)


def score_response(
    response: dict,
    golden_case: dict,
) -> MetricResult:
    """
    Score a single pipeline response against a golden case.

    Args:
        response:    Dict with 'answer', 'sources', 'duration_ms'
        golden_case: Dict from golden_dataset.py

    Returns:
        MetricResult with all available scores
    """
    answer = response.get("answer", "")
    sources = response.get("sources", [])
    reference = golden_case["expected_answer"]
    min_length = golden_case.get("min_length", 50)

    result = MetricResult()
    result.answer_length = len(answer)
    result.length_ok = len(answer) >= min_length

    # ROUGE-L
    rouge = compute_rouge_l(answer, reference)
    result.rouge_l = rouge
    if rouge > 0.0:
        result.available_metrics.append("rouge_l")

    # Source overlap
    result.source_overlap = compute_source_overlap(sources, golden_case.get("expected_sources", []))
    result.available_metrics.append("source_overlap")

    return result


def score_batch(
    responses: list[dict],
    golden_cases: list[dict],
    include_bert: bool = False,
) -> list[MetricResult]:
    """
    Score a batch of responses. Optionally include BERTScore (slower).

    Args:
        responses:    List of pipeline responses
        golden_cases: Corresponding golden cases
        include_bert: Whether to run BERTScore (requires bert-score package)
    """
    results = [score_response(r, g) for r, g in zip(responses, golden_cases)]

    if include_bert:
        predictions = [r.get("answer", "") for r in responses]
        references = [g["expected_answer"] for g in golden_cases]
        bert_scores = compute_bert_score(predictions, references)
        for result, bs in zip(results, bert_scores):
            result.bert_score_f1 = bs
            if bs > 0.0:
                result.available_metrics.append("bert_score_f1")

    return results


def aggregate(results: list[MetricResult]) -> dict:
    """Compute mean scores across a batch."""
    if not results:
        return {}

    n = len(results)
    return {
        "rouge_l": round(sum(r.rouge_l for r in results) / n, 4),
        "bert_score_f1": round(sum(r.bert_score_f1 for r in results) / n, 4),
        "source_overlap": round(sum(r.source_overlap for r in results) / n, 4),
        "length_pass_rate": round(sum(r.length_ok for r in results) / n, 4),
        "avg_answer_length": round(sum(r.answer_length for r in results) / n),
        "n": n,
    }
