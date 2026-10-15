# Data Quality, Evaluation and Limitations

## Current API summary
The local summary endpoint currently reports:
- 246 loaded surveillance records
- 7,133 cases summed across source rows
- 24 deaths summed across source rows
- 26 state labels
- 36 disease labels

These are installation-specific aggregates, not verified national totals. Row counts may overlap and should not be described as unique cases without checking the underlying dataset definitions.

## Reporting-period coverage
The API currently returns five observed weekly periods:
- 2025-W24
- 2025-W25
- 2025-W41
- 2025-W47
- 2026-W09

The gaps mean this data should not be presented as a complete continuous weekly time series.

## Disease-label normalization
Examples of distinct labels include:
- Acute Diarrheal Disease / Acute Diarrhoeal Disease
- Food Poisoning / Suspected Food Poisoning

Do not combine these categories until the original source definitions and coding rules have been reviewed.

## Anomaly screening
The current exploratory request `/analytics/anomalies?min_history=2` returned five screening candidates from 13 evaluable periods across the loaded records.

The method uses a trailing median and robust median absolute deviation (MAD). The shorter history setting is exploratory and less reliable. A flag means an observation deserves review; it does not establish an outbreak, causation, or a health emergency.

## Before research or deployment use
1. Record each dataset's publisher and exact source URL.
2. Record download date, reporting period, licence and permitted uses.
3. Inspect missing values, duplicates, overlapping reports and inconsistent labels.
4. Validate calculations against source documentation.
5. Evaluate screening sensitivity and false-positive rates against reviewed historical examples.
6. Have qualified public-health personnel review any real-world alerts.
7. Keep private patient information and secrets out of the repository.
