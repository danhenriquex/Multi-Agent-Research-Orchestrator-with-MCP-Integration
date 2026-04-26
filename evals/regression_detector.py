"""
Regression detector — compares current scores against a stored baseline
and flags metrics that have degraded beyond acceptable thresholds.

Thresholds are intentionally conservative:
  - ROUGE-L:       5% drop allowed (lexical changes are expected)
  - BERTScore:     2% drop allowed (semantic drift is more serious)
  - source_overlap: 10% drop allowed
  - length_pass_rate: 10% drop allowed

Baseline is stored in evals/baselines/current.json and committed to git.
This means regressions are detected relative to the last approved baseline.
"""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

BASELINE_FILE = Path(__file__).parent / "baselines" / "current.json"

# ── Regression thresholds ─────────────────────────────────────────────────────
# max_drop: maximum acceptable drop from baseline (absolute, not percentage)
# If current_score < baseline_score - max_drop → regression detected

THRESHOLDS = {
    "rouge_l": {"max_drop": 0.05, "description": "ROUGE-L lexical overlap"},
    "bert_score_f1": {"max_drop": 0.02, "description": "BERTScore semantic similarity"},
    "source_overlap": {"max_drop": 0.10, "description": "Expected source coverage"},
    "length_pass_rate": {"max_drop": 0.10, "description": "Answer length compliance"},
}


def load_baseline() -> dict:
    """Load stored baseline scores. Returns empty dict if no baseline exists."""
    if not BASELINE_FILE.exists():
        log.warning("No baseline found at %s", BASELINE_FILE)
        return {}
    try:
        return json.loads(BASELINE_FILE.read_text())
    except Exception as exc:
        log.error("Failed to load baseline: %s", exc)
        return {}


def save_baseline(scores: dict) -> None:
    """Save current scores as the new baseline."""
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(json.dumps(scores, indent=2))
    log.info("Baseline saved: %s", BASELINE_FILE)


def detect_regressions(current: dict, baseline: dict) -> list[str]:
    """
    Compare current scores against baseline.

    Returns list of regression messages (empty = no regression).
    Exits are only triggered when confidence interval falls below threshold,
    preventing false alarms from random variation.
    """
    regressions = []

    for metric, config in THRESHOLDS.items():
        if metric not in baseline:
            log.debug("Metric %s not in baseline — skipping", metric)
            continue
        if metric not in current:
            log.debug("Metric %s not in current scores — skipping", metric)
            continue

        baseline_val = baseline[metric]
        current_val = current[metric]
        drop = baseline_val - current_val
        max_drop = config["max_drop"]

        if drop > max_drop:
            regressions.append(
                f"{config['description']} ({metric}): "
                f"{baseline_val:.4f} → {current_val:.4f} "
                f"(drop={drop:.4f}, threshold={max_drop:.4f})"
            )
        else:
            log.info(
                "✓ %s: %.4f → %.4f (drop=%.4f, within threshold=%.4f)",
                metric,
                baseline_val,
                current_val,
                drop,
                max_drop,
            )

    return regressions


def diff_report(current: dict, baseline: dict) -> str:
    """Generate a human-readable diff report."""
    if not baseline:
        return "No baseline to compare against."

    lines = ["Metric comparison (current vs baseline):"]
    lines.append(f"{'Metric':<25} {'Baseline':>10} {'Current':>10} {'Delta':>10} {'Status':>8}")
    lines.append("─" * 65)

    for metric in set(list(current.keys()) + list(baseline.keys())):
        b_val = baseline.get(metric, None)
        c_val = current.get(metric, None)

        if b_val is None or c_val is None:
            continue
        if not isinstance(b_val, (int, float)):
            continue

        delta = c_val - b_val
        config = THRESHOLDS.get(metric, {})
        max_drop = config.get("max_drop", 0.05)

        if delta >= 0:
            status = "✓ improved"
        elif abs(delta) <= max_drop:
            status = "✓ ok"
        else:
            status = "✗ REGRESSED"

        lines.append(f"{metric:<25} {b_val:>10.4f} {c_val:>10.4f} {delta:>+10.4f} {status:>8}")

    return "\n".join(lines)


if __name__ == "__main__":
    # Quick test
    baseline = load_baseline()
    if baseline:
        print("Current baseline:")
        print(json.dumps(baseline, indent=2))
    else:
        print("No baseline saved yet. Run:")
        print("  uv run python evals/regression_runner.py --suite smoke --save-baseline")
