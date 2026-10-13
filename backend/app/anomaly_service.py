"""Explainable case-count anomaly screening for Samraksha Kendra.

This is a screening aid, not a clinical diagnosis or official outbreak declaration.
It uses only historical observations in the supplied records and never mutates them.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Iterable


def detect_case_anomalies(
    records: Iterable[dict[str, Any]],
    *,
    min_history: int = 4,
    lookback: int = 8,
    threshold: float = 3.5,
    min_cases_for_zero_mad: int = 10,
) -> list[dict[str, Any]]:
    """Return points that are unusually high against their preceding observations.

    Inputs need state, disease, year, week, cases. Duplicate rows for a state/disease/
    period are aggregated before scoring. A robust MAD score is used, with a conservative
    fallback when the historical median absolute deviation is zero.
    """
    grouped: dict[tuple[str, str], dict[tuple[int, int], int]] = defaultdict(lambda: defaultdict(int))
    for row in records:
        try:
            state = str(row.get("state") or "Unknown").strip() or "Unknown"
            disease = str(row.get("disease") or "Unknown").strip() or "Unknown"
            year = int(row.get("year"))
            week = int(row.get("week"))
            cases = max(0, int(row.get("cases") or 0))
        except (TypeError, ValueError):
            continue
        grouped[(state, disease)][(year, week)] += cases

    anomalies: list[dict[str, Any]] = []
    for (state, disease), period_values in grouped.items():
        ordered = sorted(period_values.items())
        values = [cases for _, cases in ordered]
        for idx, ((year, week), observed) in enumerate(ordered):
            history = values[max(0, idx - lookback):idx]
            if len(history) < min_history:
                continue
            baseline = float(median(history))
            mad = float(median([abs(value - baseline) for value in history]))
            if mad > 0:
                score = 0.6745 * (observed - baseline) / mad
                flagged = score >= threshold
            else:
                # A flat / all-zero baseline cannot be divided by MAD. Require a meaningful
                # absolute rise so one small nonzero count is not automatically an outbreak.
                score = None
                flagged = observed > baseline and observed >= max(min_cases_for_zero_mad, baseline * 2)
            if not flagged:
                continue
            score_for_sort = score if score is not None else float(observed - baseline)
            severity = "HIGH" if (score is not None and score >= 7.0) or observed >= 100 else (
                "MODERATE" if (score is not None and score >= 5.0) or observed >= 50 else "WATCH"
            )
            anomalies.append({
                "year": year,
                "week": week,
                "state": state,
                "disease": disease,
                "cases": observed,
                "baseline_median": round(baseline, 2),
                "mad_score": round(score, 2) if score is not None else None,
                "severity": severity,
                "method": "Trailing median + robust MAD",
                "is_synthetic": False,
                "source": "historical_screening",
                "message": f"{disease} case count ({observed}) is unusually high compared with the preceding {len(history)} observations (median {baseline:g}).",
                "_sort_score": score_for_sort,
            })
    anomalies.sort(key=lambda item: (item["_sort_score"], item["cases"]), reverse=True)
    for item in anomalies:
        item.pop("_sort_score", None)
    return anomalies[:100]
