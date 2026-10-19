# Synthetic anomaly-screening validation

This feature provides a deterministic software test for the trailing-median + robust-MAD screening implementation. The fixture uses five synthetic periods of 10 cases followed by one synthetic period of 100 cases; exactly one high point is expected to be flagged.

- Endpoint: `GET /analytics/anomalies/demo-screening`
- UI action: **Validate detector (synthetic)** in Anomaly Detection.
- This fixture makes no database reads or writes and never inserts synthetic rows into surveillance totals.
- Results are explicitly labeled synthetic. This validates expected code behavior, not epidemiological accuracy.
- Real screening may still return `insufficient_history` when there are too few verified periods for a state/disease series.
