"""Experimental ICA analysis for aggregated disease-count time series."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

import numpy as np
from sklearn.decomposition import FastICA
from sklearn.preprocessing import StandardScaler


class ICAInputError(ValueError):
    """Raised when the selected surveillance data cannot support ICA."""


def run_ica_analysis(records: Iterable[dict[str, Any]], n_components: int = 2) -> dict[str, Any]:
    """Run ICA on weekly case counts for the most frequently reported diseases.

    Rows are year-week periods; columns are the top disease categories by total cases.
    This is exploratory analysis, not causal attribution or outbreak prediction.
    """
    if n_components < 2 or n_components > 5:
        raise ICAInputError("components must be between 2 and 5")

    values: dict[tuple[int, int], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    totals: dict[str, float] = defaultdict(float)
    for row in records:
        try:
            year = int(row.get("year"))
            week = int(row.get("week"))
            disease = str(row.get("disease") or "Unknown").strip() or "Unknown"
            cases = max(0.0, float(row.get("cases") or 0))
        except (TypeError, ValueError):
            continue
        values[(year, week)][disease] += cases
        totals[disease] += cases

    if len(values) < max(5, n_components + 1):
        raise ICAInputError(
            f"ICA needs at least {max(5, n_components + 1)} distinct year-week periods; found {len(values)}."
        )

    ranked_diseases = [name for name, total in sorted(totals.items(), key=lambda kv: kv[1], reverse=True) if total > 0]
    features = ranked_diseases[: max(n_components, min(5, len(ranked_diseases)))]
    if len(features) < n_components:
        raise ICAInputError("ICA needs at least as many non-empty disease features as requested components.")

    periods = sorted(values)
    matrix = np.asarray([[values[period].get(feature, 0.0) for feature in features] for period in periods], dtype=float)
    # Drop constant columns; ICA cannot identify a source from a constant signal.
    keep_mask = np.std(matrix, axis=0) > 1e-9
    matrix = matrix[:, keep_mask]
    features = [name for name, keep in zip(features, keep_mask) if keep]
    if matrix.shape[1] < n_components:
        raise ICAInputError("Not enough varying disease-count series remain after removing constant columns.")
    if matrix.shape[0] <= n_components:
        raise ICAInputError("There must be more reporting periods than ICA components.")

    standardized = StandardScaler().fit_transform(matrix)
    model = FastICA(
        n_components=n_components,
        random_state=42,
        max_iter=1500,
        tol=0.001,
        whiten="unit-variance",
    )
    signals = model.fit_transform(standardized)
    mixing = model.mixing_

    signal_rows = []
    for idx, (year, week) in enumerate(periods):
        row: dict[str, Any] = {"period": f"{year}-W{week:02d}"}
        for component_idx in range(n_components):
            row[f"IC{component_idx + 1}"] = round(float(signals[idx, component_idx]), 5)
        signal_rows.append(row)

    loadings = []
    for component_idx in range(n_components):
        loadings.append({
            "component": f"IC{component_idx + 1}",
            "disease_weights": {
                feature: round(float(mixing[feature_idx, component_idx]), 5)
                for feature_idx, feature in enumerate(features)
            },
        })

    return {
        "method": "FastICA",
        "experimental": True,
        "n_components": n_components,
        "sample_count": len(periods),
        "features": features,
        "signals": signal_rows,
        "loadings": loadings,
        "interpretation_note": (
            "ICA finds statistically independent combinations of the selected case-count signals. "
            "Component signs/order can vary between runs; weights are not causal effects and do not by themselves predict outbreaks."
        ),
    }
