
from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Iterable


DEFAULT_MIN_HISTORY = 4
DEFAULT_LOOKBACK = 8
DEFAULT_THRESHOLD = 3.5


def _get_value(record: Any, *names: str, default: Any = None) -> Any:
    """Read a field from either a dictionary or a database model."""
    for name in names:
        if isinstance(record, dict):
            value = record.get(name)
        else:
            value = getattr(record, name, None)

        if value is not None:
            return value

    return default


def _to_int(value: Any, default: int = 0) -> int:
    """Safely convert a value to an integer."""
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _normalise_record(record: Any) -> dict[str, Any] | None:
    """Convert a supported surveillance record into a consistent format."""
    state = str(
        _get_value(record, "state", "state_name", default="") or ""
    ).strip()

    disease = str(
        _get_value(
            record,
            "disease",
            "disease_name",
            "disease_label",
            default="",
        )
        or ""
    ).strip()

    year = _to_int(_get_value(record, "year"))
    week = _to_int(
        _get_value(record, "week", "epidemiological_week", "epi_week")
    )

    cases = _to_int(
        _get_value(
            record,
            "cases",
            "case_count",
            "total_cases",
            "confirmed_cases",
            default=None,
        ),
        default=-1,
    )

    if not state or not disease:
        return None

    if year <= 0 or week < 1 or week > 53:
        return None

    if cases < 0:
        return None

    return {
        "state": state,
        "disease": disease,
        "year": year,
        "week": week,
        "cases": cases,
        "record_id": _get_value(record, "record_id", "id"),
        "source_url": _get_value(
            record, "source_url", "source", "url"
        ),
    }


def _period_key(year: int, week: int) -> tuple[int, int]:
    return year, week


def _prepare_periods(
    records: Iterable[Any],
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], int]:
    """
    Group records by state and disease, then by observed year/week.

    Multiple rows in the same state/disease/week are summed. This is only
    appropriate when the source rows represent additive observations.
    The detector does not attempt to determine whether rows overlap.
    """
    grouped: dict[
        tuple[str, str],
        dict[tuple[int, int], dict[str, Any]],
    ] = defaultdict(dict)

    valid_records = 0

    for raw_record in records:
        record = _normalise_record(raw_record)
        if record is None:
            continue

        valid_records += 1

        group_key = (record["state"], record["disease"])
        period = _period_key(record["year"], record["week"])

        if period not in grouped[group_key]:
            grouped[group_key][period] = {
                "year": record["year"],
                "week": record["week"],
                "cases": 0,
                "source_rows": 0,
            }

        grouped[group_key][period]["cases"] += record["cases"]
        grouped[group_key][period]["source_rows"] += 1

    result: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for group_key, periods in grouped.items():
        result[group_key] = [
            periods[period]
            for period in sorted(periods.keys())
        ]

    return result, valid_records


def _robust_score(
    current_value: float,
    history: list[float],
) -> tuple[float | None, float, float]:
    """
    Calculate a robust modified Z-score using the median and MAD.

    Returns:
        (score, baseline_median, MAD)

    When MAD is zero, the function uses a conservative fallback:
    a score is only calculated if the current value differs from the
    baseline median. This avoids division by zero.
    """
    baseline = float(median(history))
    deviations = [abs(value - baseline) for value in history]
    mad = float(median(deviations))

    if mad > 0:
        score = 0.6745 * (current_value - baseline) / mad
        return score, baseline, mad

    if current_value == baseline:
        return None, baseline, mad

    if current_value > baseline:
        return float("inf"), baseline, mad

    return float("-inf"), baseline, mad


def detect_case_anomalies(
    records: Iterable[Any],
    min_history: int = DEFAULT_MIN_HISTORY,
    lookback: int = DEFAULT_LOOKBACK,
    threshold: float = DEFAULT_THRESHOLD,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """
    Screen observed state/disease/week counts for unusually high values.

    This is a historical screening method, not an outbreak diagnosis.

    Important limitations:
    - Missing weeks are not inserted as zero-case weeks.
    - Only previously observed periods are used as the baseline.
    - The periods may not be consecutive calendar weeks.
    - Same-week rows are summed, so source-row additivity must be checked.
    """
    if min_history < 1:
        raise ValueError("min_history must be at least 1.")

    if lookback < 1:
        raise ValueError("lookback must be at least 1.")

    if threshold <= 0:
        raise ValueError("threshold must be greater than 0.")

    if max_results < 1:
        raise ValueError("max_results must be at least 1.")

    grouped, _ = _prepare_periods(records)
    anomalies: list[dict[str, Any]] = []

    for (state, disease), periods in grouped.items():
        for index, current in enumerate(periods):
            # Only use earlier observed periods. Never use the current
            # observation in its own baseline.
            history_periods = periods[max(0, index - lookback):index]

            if len(history_periods) < min_history:
                continue

            history = [
                float(item["cases"])
                for item in history_periods
            ]

            current_cases = float(current["cases"])

            score, baseline, mad = _robust_score(
                current_cases,
                history,
            )

            if score is None or score <= threshold:
                continue

            previous_cases = history[-1] if history else None

            anomalies.append(
                {
                    "state": state,
                    "disease": disease,
                    "year": current["year"],
                    "week": current["week"],
                    "cases": int(current_cases),
                    "baseline_median": baseline,
                    "baseline_mad": mad,
                    "robust_score": (
                        "positive_infinity"
                        if score == float("inf")
                        else score
                    ),
                    "previous_observed_cases": (
                        int(previous_cases)
                        if previous_cases is not None
                        else None
                    ),
                    "change_from_baseline": current_cases - baseline,
                    "baseline_observed_periods": len(history_periods),
                    "current_period_source_rows": current["source_rows"],
                    "screening_method": "Trailing median + robust MAD",
                    "requires_human_review": True,
                }
            )

    anomalies.sort(
        key=lambda item: (
            item["robust_score"] == "positive_infinity",
            (
                item["robust_score"]
                if isinstance(item["robust_score"], (int, float))
                else float("inf")
            ),
            item["cases"],
        ),
        reverse=True,
    )

    return anomalies[:max_results]


def get_anomaly_diagnostics(
    records: Iterable[Any],
    min_history: int = DEFAULT_MIN_HISTORY,
    lookback: int = DEFAULT_LOOKBACK,
) -> dict[str, Any]:
    """
    Explain how much of the supplied data can be evaluated.

    A group is a state/disease combination. An observed period is a
    year/week with at least one valid record.
    """
    grouped, valid_record_count = _prepare_periods(records)

    total_groups = len(grouped)
    total_observed_periods = sum(
        len(periods) for periods in grouped.values()
    )

    evaluable_periods = 0
    skipped_periods = 0
    groups_with_evaluable_periods = 0

    for periods in grouped.values():
        group_evaluable = 0

        for index in range(len(periods)):
            history_length = min(index, lookback)

            if history_length >= min_history:
                evaluable_periods += 1
                group_evaluable += 1
            else:
                skipped_periods += 1

        if group_evaluable:
            groups_with_evaluable_periods += 1

    return {
        "valid_source_records": valid_record_count,
        "state_disease_groups": total_groups,
        "observed_periods": total_observed_periods,
        "minimum_history_required": min_history,
        "maximum_lookback_periods": lookback,
        "evaluable_periods": evaluable_periods,
        "periods_skipped_for_insufficient_history": skipped_periods,
        "groups_with_enough_history_for_at_least_one_evaluation": (
            groups_with_evaluable_periods
        ),
        "notes": [
            "Only observed periods are evaluated.",
            "Observed periods may not be consecutive calendar weeks.",
            "Missing weeks are not interpreted as zero cases.",
            (
                "Multiple rows in the same state/disease/week are summed; "
                "confirm that the source rows are additive before interpreting "
                "aggregated counts."
            ),
            (
                "No detected anomaly does not establish that no outbreak "
                "exists."
            ),
        ],
    }


def run_synthetic_anomaly_screening_fixture() -> dict[str, Any]:
    """Validate the anomaly detector with labelled synthetic values only.

    Independent of PostgreSQL; never mutates surveillance rows.
    """
    from datetime import datetime, timezone

    current_year = datetime.now(timezone.utc).year
    case_counts = [10, 10, 10, 10, 10, 100]
    records = [
        {
            "year": current_year,
            "week": week,
            "state": "SYNTHETIC DEMO",
            "district": "DEMO ONLY",
            "disease": "Synthetic disease signal",
            "cases": cases,
            "deaths": 0,
        }
        for week, cases in enumerate(case_counts, start=1)
    ]
    anomalies = detect_case_anomalies(records, min_history=4, lookback=8)
    for item in anomalies:
        item["is_synthetic"] = True
        item["source"] = "synthetic_validation_fixture"
        item["district"] = "DEMO ONLY"
        item["message"] = (
            "SYNTHETIC FIXTURE ONLY: the final 100-case point exceeds the prior "
            "five flat 10-case observations. This validates detector logic; it is "
            "not a real disease report."
        )
    passed = len(anomalies) == 1 and anomalies[0].get("cases") == 100
    return {
        "status": "passed" if passed else "failed",
        "is_synthetic": True,
        "fixture_name": "flat baseline with one controlled spike",
        "input_periods": len(records),
        "input_case_counts": case_counts,
        "expected_flags": 1,
        "count": len(anomalies),
        "items": anomalies,
        "message": (
            "Expected synthetic spike detected; no database reads or writes were performed."
            if passed else "Detector did not flag the expected synthetic spike."
        ),
        "caution": (
            "Synthetic validation only. These generated values are not surveillance data, "
            "must not be counted in dashboard totals, and do not represent an outbreak. "
            "Real-data screening requires sufficient verified historical observations "
            "and human review."
        ),
    }
