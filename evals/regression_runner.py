"""
Regression runner — runs the research pipeline against the golden dataset
and computes quality scores.

Usage:
  # Smoke test (5 cases, ~2 min)
  uv run python evals/regression_runner.py --suite smoke

  # Full benchmark (all cases, ~15 min)
  uv run python evals/regression_runner.py --suite full

  # With BERTScore (slower but catches semantic regressions)
  uv run python evals/regression_runner.py --suite smoke --bert

  # Save scores as new baseline
  uv run python evals/regression_runner.py --suite smoke --save-baseline

  # Compare against existing baseline (CI mode)
  uv run python evals/regression_runner.py --suite smoke --check-regression
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

import httpx

# Add evals dir to path
sys.path.insert(0, str(Path(__file__).parent))
from golden_dataset import get_full_cases, get_smoke_cases
from regression_detector import detect_regressions, load_baseline, save_baseline
from regression_metrics import MetricResult, aggregate, score_batch

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")
N_RUNS = int(os.getenv("EVAL_N_RUNS", "1"))  # set to 3 for confidence intervals


async def run_query(client: httpx.AsyncClient, query: str) -> dict:
    """Run a single query against the orchestrator."""
    try:
        resp = await client.post(
            f"{ORCHESTRATOR_URL}/research",
            json={"query": query},
            timeout=120.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        log.error("Query failed: %s — %s", query[:60], exc)
        return {"answer": "", "sources": [], "error": str(exc)}


async def run_suite(
    cases: list[dict],
    include_bert: bool = False,
    n_runs: int = 1,
) -> tuple[list[dict], list[MetricResult], dict]:
    """
    Run all cases through the pipeline and score them.

    If n_runs > 1, runs each query multiple times and computes
    confidence intervals (reduces false alarms from random variation).

    Returns:
        (responses, metric_results, aggregated_scores)
    """
    responses = []

    async with httpx.AsyncClient() as client:
        for i, case in enumerate(cases, 1):
            log.info("[%d/%d] %s", i, len(cases), case["query"][:70])

            if n_runs > 1:
                # Multi-run for statistical confidence
                run_responses = []
                for run in range(n_runs):
                    r = await run_query(client, case["query"])
                    run_responses.append(r)
                    log.info(
                        "  run %d/%d: answer_len=%d",
                        run + 1,
                        n_runs,
                        len(r.get("answer", "")),
                    )

                # Use the response closest to mean answer length
                lengths = [len(r.get("answer", "")) for r in run_responses]
                median_len = sorted(lengths)[len(lengths) // 2]
                best = min(
                    run_responses,
                    key=lambda r: abs(len(r.get("answer", "")) - median_len),
                )
                responses.append(best)
            else:
                r = await run_query(client, case["query"])
                responses.append(r)

    # Score all responses
    results = score_batch(responses, cases, include_bert=include_bert)

    # Compute aggregates
    scores = aggregate(results)

    return responses, results, scores


def print_results(cases: list[dict], responses: list[dict], results: list[MetricResult]):
    """Print per-case results table."""
    print(f"\n{'─' * 80}")
    print(f"{'ID':<25} {'ROUGE-L':>8} {'BERTScore':>10} {'Src%':>6} {'Len':>6} {'OK':>4}")
    print(f"{'─' * 80}")
    for case, resp, result in zip(cases, responses, results):
        ok = "✓" if result.length_ok and result.rouge_l > 0.1 else "✗"
        print(
            f"{case['id']:<25} "
            f"{result.rouge_l:>8.3f} "
            f"{result.bert_score_f1:>10.3f} "
            f"{result.source_overlap:>6.2f} "
            f"{result.answer_length:>6} "
            f"{ok:>4}"
        )
    print(f"{'─' * 80}")


async def main():
    parser = argparse.ArgumentParser(description="Run regression evaluation suite")
    parser.add_argument("--suite", choices=["smoke", "full"], default="smoke")
    parser.add_argument("--bert", action="store_true", help="Include BERTScore")
    parser.add_argument("--n-runs", type=int, default=N_RUNS)
    parser.add_argument("--save-baseline", action="store_true", help="Save scores as new baseline")
    parser.add_argument(
        "--check-regression",
        action="store_true",
        help="Compare against baseline (CI mode)",
    )
    args = parser.parse_args()

    cases = get_smoke_cases() if args.suite == "smoke" else get_full_cases()
    log.info(
        "Suite: %s | Cases: %d | Runs/case: %d | BERTScore: %s",
        args.suite,
        len(cases),
        args.n_runs,
        args.bert,
    )

    # ── Verify orchestrator is reachable ──────────────────────────────────────
    try:
        async with httpx.AsyncClient() as client:
            health = await client.get(f"{ORCHESTRATOR_URL}/health", timeout=10.0)
            health.raise_for_status()
        log.info("Orchestrator healthy at %s", ORCHESTRATOR_URL)
    except Exception as exc:
        log.error("Orchestrator not reachable at %s: %s", ORCHESTRATOR_URL, exc)
        sys.exit(1)

    # ── Run suite ─────────────────────────────────────────────────────────────
    t0 = time.time()
    responses, results, scores = await run_suite(cases, args.bert, args.n_runs)
    elapsed = round(time.time() - t0, 1)

    # ── Print results ─────────────────────────────────────────────────────────
    print_results(cases, responses, results)
    print(f"\nAggregate scores ({args.suite} suite, {elapsed}s):")
    for k, v in scores.items():
        print(f"  {k:<25} {v}")

    # ── Save baseline ─────────────────────────────────────────────────────────
    if args.save_baseline:
        save_baseline(scores)
        log.info("Baseline saved to evals/baselines/current.json")

    # ── Regression check ──────────────────────────────────────────────────────
    if args.check_regression:
        baseline = load_baseline()
        if not baseline:
            log.warning("No baseline found — saving current scores as baseline")
            save_baseline(scores)
            sys.exit(0)

        regressions = detect_regressions(scores, baseline)
        if regressions:
            print(f"\n{'=' * 60}")
            print("REGRESSION DETECTED — deployment blocked")
            print(f"{'=' * 60}")
            for r in regressions:
                print(f"  ✗ {r}")
            print(f"{'=' * 60}\n")
            sys.exit(1)
        else:
            print("\n✓ No regressions detected (compared against baseline)")
            sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
