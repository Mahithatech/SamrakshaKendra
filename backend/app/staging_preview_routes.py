"""Read-only API for NCDC staging records, kept separate from live surveillance."""
from __future__ import annotations
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.database import engine

router = APIRouter(prefix="/admin/ncdc-staging", tags=["Admin · NCDC staging preview"])


def _items(rows: list[Any]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        item = dict(row)
        for key, value in list(item.items()):
            if hasattr(value, "isoformat"):
                item[key] = value.isoformat()
        result.append(item)
    return result


@router.get("/summary", summary="Read-only preview of NCDC records awaiting review")
def ncdc_staging_summary(
    limit: int = Query(default=100, ge=1, le=500),
    review_status: str | None = Query(default=None),
):
    allowed_statuses = {
        "pending_supervisor_review", "promoted_to_live_surveillance",
    }
    if review_status is not None and review_status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Unsupported staging review_status")
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT to_regclass('public.ncdc_outbreak_staging')")).scalar()
            if not exists:
                return {
                    "status": "not_initialized", "total_records": 0,
                    "status_counts": {}, "totals": {"known_cases_sum": None, "known_deaths_sum": None, "unknown_case_rows": 0, "unknown_death_rows": 0},
                    "by_state": [], "items": [],
                    "data_note": "The NCDC staging table is not initialized. No live data was changed.",
                }
            status_rows = conn.execute(text("""
                SELECT COALESCE(review_status, 'unknown') AS review_status, COUNT(*) AS records
                FROM public.ncdc_outbreak_staging GROUP BY COALESCE(review_status, 'unknown')
            """)).mappings().all()
            status_counts = {str(r["review_status"]): int(r["records"]) for r in status_rows}
            overall = conn.execute(text("""
                SELECT COUNT(*) AS total_records,
                       SUM(cases) AS known_cases_sum,
                       SUM(deaths) AS known_deaths_sum,
                       SUM(CASE WHEN cases IS NULL THEN 1 ELSE 0 END) AS unknown_case_rows,
                       SUM(CASE WHEN deaths IS NULL THEN 1 ELSE 0 END) AS unknown_death_rows
                FROM public.ncdc_outbreak_staging
            """)).mappings().one()
            state_rows = conn.execute(text("""
                SELECT state, COUNT(*) AS records, SUM(cases) AS known_cases_sum,
                       SUM(deaths) AS known_deaths_sum,
                       SUM(CASE WHEN cases IS NULL THEN 1 ELSE 0 END) AS unknown_case_rows
                FROM public.ncdc_outbreak_staging
                GROUP BY state ORDER BY SUM(cases) DESC NULLS LAST, state ASC LIMIT 36
            """)).mappings().all()
            params: dict[str, Any] = {"limit": limit}
            status_clause = ""
            if review_status:
                status_clause = "WHERE review_status = :review_status"
                params["review_status"] = review_status
            rows = conn.execute(text(f"""
                SELECT record_id, report_year, report_week, state, district, disease,
                       cases, deaths, outbreak_start_date, reporting_date, current_status,
                       source_url, source_validation_status, review_status, imported_at
                FROM public.ncdc_outbreak_staging
                {status_clause}
                ORDER BY report_year DESC, report_week DESC, record_id ASC
                LIMIT :limit
            """), params).mappings().all()
        totals = dict(overall)
        for key, value in list(totals.items()):
            if value is not None:
                totals[key] = int(value)
        return {
            "status": "available", "total_records": int(totals.pop("total_records", 0)),
            "status_counts": status_counts, "totals": totals,
            "by_state": _items(list(state_rows)), "items": _items(list(rows)),
            "returned_items": len(rows),
            "data_note": "These are separate NCDC staging candidates. They are not included in live surveillance totals until explicitly approved and promoted. Unknown values remain unknown. Staging sums may overlap and must not be interpreted as unique national case counts.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"NCDC staging preview unavailable ({type(exc).__name__}).") from exc
