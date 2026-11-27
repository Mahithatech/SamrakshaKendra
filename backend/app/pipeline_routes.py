"""Authenticated operations for the automated ingestion and validation pipeline.

In the current app, a global bearer-token middleware protects HTTP routes. These
endpoints still require a valid reviewer token; they never disable authentication.
"""
from __future__ import annotations
import re
import asyncio
import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from .auth_security import decode_access_token
from .database import SessionLocal, engine
from .ingestion_pipeline import (
    _insert_event,
    _latest_anomalies,
    _persist_anomaly_events,
    cron_token_matches,
    emit_pending_events,
    ensure_pipeline_schema,
    is_allowed_source_url,
    pipeline_enabled,
    pipeline_interval_seconds,
    run_pipeline_cycle,
)

from .synthetic_ingestion import generate_synthetic_records

router = APIRouter(tags=["Automated Source Ingestion Pipeline"])

def _insert_audit(
    connection,
    candidate_id: str,
    action: str,
    actor: str,
    note: str,
    details: dict | None = None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO public.sk_candidate_audit
                (audit_id, candidate_id, action, actor, action_at, note, details)
            VALUES
                (gen_random_uuid()::text, :candidate_id, :action, :actor,
                 NOW(), :note, CAST(:details AS jsonb))
        """),
        {
            "candidate_id": candidate_id,
            "action": action,
            "actor": actor,
            "note": note,
            "details": json.dumps(details or {}),
        },
    )


class CandidateDecision(BaseModel):
    action: Literal["approve", "reject"]
    reviewer_note: str = Field(min_length=8, max_length=1500)

class CandidateCorrection(BaseModel):
    report_year: int = Field(ge=2000, le=2100)
    report_week: int = Field(ge=1, le=53)
    state: str = Field(min_length=2, max_length=180)
    district: str = Field(min_length=2, max_length=180)
    disease: str = Field(min_length=3, max_length=180)
    reporting_start_date: date
    reporting_end_date: date
    cases: int = Field(ge=0)
    deaths: int | None = Field(default=None, ge=0)
    correction_note: str = Field(min_length=8, max_length=1500)


class CandidatePromotion(BaseModel):
    duplicate_override: bool = False
    override_reason: str | None = Field(default=None, max_length=1500)

def _reviewer_from_header(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required. Sign in to continue.")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="A Bearer access token is required.")
    claims = decode_access_token(token.strip())
    if not claims:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return str(claims.get("sub") or claims.get("username") or claims.get("user") or "authenticated_reviewer")[:160]


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value

def _extract_ncdc_record_id(raw_excerpt: str | None) -> str | None:
    """Extract the original NCDC identifier at the beginning of an excerpt."""
    if not raw_excerpt:
        return None

    match = re.match(
        r"^\s*([A-Za-z]{2,3}/[A-Za-z]{2,3}/\d{4}/\d{1,2}/\d+)\b",
        str(raw_excerpt),
    )
    return match.group(1).upper() if match else None


def _find_candidate_duplicates(connection, candidate: dict) -> list[dict]:
    """
    Find possible duplicates in live IDSP, legacy staging and candidate staging.

    Original NCDC record ID equality is the strongest identity match.
    Matching core outbreak fields without the same ID is only a possible match.
    """
    source_id = _extract_ncdc_record_id(candidate.get("raw_excerpt"))

    common = {
        "year": candidate["report_year"],
        "week": candidate["report_week"],
        "state": str(candidate["state"]).strip().casefold(),
        "district": str(candidate["district"]).strip().casefold(),
        "disease": str(candidate["disease"]).strip().casefold(),
    }

    matches = []

    queries = [
        (
            "live_idsp",
            """
            SELECT record_id, year, week, state, district, disease,
                   cases, deaths, reporting_start_date, reporting_end_date
            FROM public.idsp_surveillance
            WHERE year=:year AND week=:week
              AND LOWER(TRIM(state))=:state
              AND LOWER(TRIM(district))=:district
              AND LOWER(TRIM(disease))=:disease
            """,
        ),
        (
            "legacy_staging",
            """
            SELECT record_id, report_year AS year, report_week AS week,
                   state, district, disease, cases, deaths,
                   outbreak_start_date AS reporting_start_date,
                   reporting_date AS reporting_end_date
            FROM public.ncdc_outbreak_staging
            WHERE report_year=:year AND report_week=:week
              AND LOWER(TRIM(state))=:state
              AND LOWER(TRIM(district))=:district
              AND LOWER(TRIM(disease))=:disease
            """,
        ),
        (
            "other_candidates",
            """
            SELECT candidate_id, raw_excerpt, report_year AS year,
                   report_week AS week, state, district, disease,
                   cases, deaths, reporting_start_date, reporting_end_date
            FROM public.sk_ingestion_candidates
            WHERE report_year=:year AND report_week=:week
              AND LOWER(TRIM(state))=:state
              AND LOWER(TRIM(district))=:district
              AND LOWER(TRIM(disease))=:disease
              AND candidate_id<>:candidate_id
            """,
        ),
    ]

    params = {
        **common,
        "candidate_id": candidate["candidate_id"],
    }

    for table_name, sql in queries:
        rows = connection.execute(text(sql), params).mappings().all()

        for row in rows:
            row = dict(row)

            if table_name == "other_candidates":
                matched_id = _extract_ncdc_record_id(row.get("raw_excerpt"))
                reference = row.get("candidate_id")
            else:
                matched_id = str(row.get("record_id") or "").strip().upper()
                reference = row.get("record_id")

            exact_id = bool(source_id and matched_id and source_id == matched_id)

            matches.append({
                "table": table_name,
                "reference": reference,
                "original_ncdc_id": matched_id,
                "match_type": "exact_match" if exact_id else "possible_match",
                "cases": row.get("cases"),
                "deaths": row.get("deaths"),
                "reporting_start_date": _iso(row.get("reporting_start_date")),
                "reporting_end_date": _iso(row.get("reporting_end_date")),
            })

    return matches


@router.post("/internal/pipeline/run-scheduled", summary="Run the pipeline from a configured external scheduler")
async def run_pipeline_scheduled(x_pipeline_token: str | None = Header(default=None, alias="X-Pipeline-Token")):
    # This single route is exempted from global Bearer middleware only because it has a separate
    # long random shared-secret guard. No admin endpoints are exempted.
    configured = os.getenv("SK_PIPELINE_CRON_TOKEN", "")
    if not configured:
        raise HTTPException(status_code=503, detail="Scheduled runner secret is not configured on the API service")
    if not cron_token_matches(configured, x_pipeline_token):
        raise HTTPException(status_code=403, detail="Scheduled runner token rejected")
    india_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    period_start = india_today - timedelta(days=india_today.weekday())

    synthetic_result = await asyncio.to_thread(
        generate_synthetic_records,
        records_per_cycle=48,
        period_start=period_start,
    )

    result = await asyncio.to_thread(run_pipeline_cycle)
    result["synthetic_generation"] = synthetic_result
    result["event_delivery"] = await emit_pending_events()
    return result


@router.get("/admin/pipeline/status", summary="Status of the automatic ingestion pipeline")
def pipeline_status():
    ensure_pipeline_schema()
    with engine.begin() as connection:
        latest = connection.execute(text("""
            SELECT run_id, status, started_at, finished_at, who_seen, ncdc_seen,
                   pdf_attempted, pdf_extracted, candidates_added, candidates_flagged,
                   anomalies_found, events_created, details, error_summary
            FROM public.sk_ingestion_runs ORDER BY started_at DESC LIMIT 1
        """)).mappings().first()
        candidate_counts = connection.execute(text("""
            SELECT review_status, COUNT(*) AS count FROM public.sk_ingestion_candidates GROUP BY review_status
        """)).mappings().all()
        document_counts = connection.execute(text("""
            SELECT source_code, extraction_status, COUNT(*) AS count
            FROM public.sk_source_documents GROUP BY source_code, extraction_status
        """)).mappings().all()
        pending_events = int(connection.execute(text("SELECT COUNT(*) FROM public.sk_pipeline_events WHERE broadcast_at IS NULL")).scalar() or 0)
        audit_count = int(connection.execute(text("SELECT COUNT(*) FROM public.sk_candidate_audit")).scalar() or 0)
    return {
        "enabled": pipeline_enabled(), "interval_seconds": pipeline_interval_seconds(),
        "latest_run": dict(latest) if latest else None,
        "candidate_counts": [dict(r) for r in candidate_counts],
        "document_counts": [dict(r) for r in document_counts],
        "pending_event_broadcasts": pending_events, "candidate_audit_entries": audit_count,
        "safety_note": "Official publication discovery and PDF extraction are automatic. Extracted rows remain in quarantine until a human approves them and explicitly promotes them.",
        "hosting_note": "The in-process scheduler runs only while this API instance is awake. Use a reliable external scheduler/worker for guaranteed runs on a host that sleeps.",
    }


@router.get("/admin/pipeline/runs", summary="Recent source ingestion and processing runs")
def pipeline_runs(limit: int = Query(default=20, ge=1, le=100)):
    ensure_pipeline_schema()
    with engine.begin() as connection:
        rows = connection.execute(text("""
            SELECT run_id, status, started_at, finished_at, who_seen, ncdc_seen,
                   pdf_attempted, pdf_extracted, candidates_added, candidates_flagged,
                   anomalies_found, events_created, details, error_summary
            FROM public.sk_ingestion_runs ORDER BY started_at DESC LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return {"items": [dict(row) for row in rows], "count": len(rows)}


@router.get("/admin/pipeline/documents", summary="Recently discovered official source publications")
def pipeline_documents(limit: int = Query(default=30, ge=1, le=100), source_code: Literal["WHO", "NCDC"] | None = None):
    ensure_pipeline_schema()
    where = "WHERE source_code=:source_code" if source_code else ""
    with engine.begin() as connection:
        rows = connection.execute(text(f"""
            SELECT source_url, source_code, title, publication_date, report_year, report_week,
                   content_sha256, byte_size, page_count, extracted_characters, extraction_status,
                   validation_status, last_error, first_seen_at, last_seen_at, last_success_at
            FROM public.sk_source_documents {where}
            ORDER BY COALESCE(publication_date, first_seen_at) DESC LIMIT :limit
        """), {"limit": limit, **({"source_code": source_code} if source_code else {})}).mappings().all()
    return {"items": [dict(row) for row in rows], "count": len(rows)}


@router.get("/admin/pipeline/candidates", summary="Rows extracted to the review-only quarantine")
def pipeline_candidates(
    review_status: Literal["pending_supervisor_review", "approved", "rejected", "promoted"] | None = "pending_supervisor_review",
    limit: int = Query(default=50, ge=1, le=200),
):
    ensure_pipeline_schema()
    where = "WHERE review_status=:review_status" if review_status else ""
    with engine.begin() as connection:
        rows = connection.execute(text(f"""
            SELECT candidate_id, source_url, source_sha256, report_year, report_week,
                   state, district, disease, reporting_start_date, reporting_end_date, cases, deaths, raw_excerpt, validation_status,
                   validation_errors, review_status, reviewed_by, reviewed_at, reviewer_note,
                   promoted_record_id, created_at, updated_at
            FROM public.sk_ingestion_candidates {where}
            ORDER BY report_year DESC, report_week DESC, created_at DESC
            LIMIT :limit
        """), {"limit": limit, **({"review_status": review_status} if review_status else {})}).mappings().all()
    return {"items": [dict(row) for row in rows], "count": len(rows),
            "note": "Candidate extraction may be incomplete or misaligned by PDF text extraction. Check the cited source PDF before approval."}


@router.get(
    "/admin/pipeline/candidates/{candidate_id}/duplicates",
    summary="Preview possible duplicates without changing records",
)
def preview_candidate_duplicates(
    candidate_id: str,
    authorization: str | None = Header(default=None),
):
    ensure_pipeline_schema()
    _reviewer_from_header(authorization)

    with engine.begin() as connection:
        row = connection.execute(text("""
            SELECT *
            FROM public.sk_ingestion_candidates
            WHERE candidate_id = :id
        """), {"id": candidate_id}).mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="Candidate not found")

        candidate = dict(row)
        matches = _find_candidate_duplicates(connection, candidate)

    exact = [m for m in matches if m["match_type"] == "exact_match"]
    possible = [m for m in matches if m["match_type"] == "possible_match"]

    return {
        "candidate_id": candidate_id,
        "duplicate_count": len(matches),
        "exact_matches": exact,
        "possible_matches": possible,
        "safe_to_review": True,
        "promotion_allowed_without_override": len(matches) == 0,
        "note": "Read-only preview. No records were inserted, updated, or deleted."
    }

@router.post("/admin/pipeline/run", summary="Run source discovery, validation and anomaly screening immediately")
async def run_pipeline_now():
    result = await asyncio.to_thread(run_pipeline_cycle)
    delivered = await emit_pending_events()
    result["event_delivery"] = delivered
    return result


@router.post("/admin/pipeline/candidates/{candidate_id}/decision", summary="Record a human decision for a staged candidate")
def decide_candidate(candidate_id: str, decision: CandidateDecision, authorization: str | None = Header(default=None)):
    ensure_pipeline_schema()
    reviewer = _reviewer_from_header(authorization)
    new_status = "approved" if decision.action == "approve" else "rejected"
    with engine.begin() as connection:
        candidate = connection.execute(text("""
            SELECT candidate_id, validation_status, validation_errors, review_status
            FROM public.sk_ingestion_candidates WHERE candidate_id=:id FOR UPDATE
        """), {"id": candidate_id}).mappings().first()
        if not candidate:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if candidate["review_status"] != "pending_supervisor_review":
            raise HTTPException(
                status_code=409,
                detail="Only pending candidates can be approved or rejected.",
                )
        errors = candidate["validation_errors"] or []
        if isinstance(errors, str):
            try: errors = json.loads(errors)
            except ValueError: errors = ["validation_errors_unreadable"]
        if decision.action == "approve" and (errors or candidate["validation_status"] != "passed_preliminary_checks"):
            raise HTTPException(status_code=422, detail={"message": "Candidate has not passed preliminary validation and cannot be approved yet.", "errors": errors, "validation_status": candidate["validation_status"]})
        action_at = datetime.now(timezone.utc)
        connection.execute(text("""
            UPDATE public.sk_ingestion_candidates
            SET review_status=:status, reviewed_by=:reviewer, reviewed_at=:now,
                reviewer_note=:note, updated_at=:now
            WHERE candidate_id=:id
        """), {"status": new_status, "reviewer": reviewer, "now": action_at, "note": decision.reviewer_note.strip(), "id": candidate_id})
        _insert_audit(connection, candidate_id, new_status, reviewer, decision.reviewer_note.strip(), {"previous_status": candidate["review_status"], "validation_status": candidate["validation_status"]})
    event_type = "candidate_review_decision"
    _insert_event(f"review:{candidate_id}:{new_status}:{action_at.isoformat()}", event_type, {
        "type": event_type, "created_at": action_at.isoformat(), "candidate_id": candidate_id,
        "review_status": new_status, "reviewed_by": reviewer, "message": f"A source candidate was marked {new_status}; this is not a live surveillance data update.", "is_synthetic": False,
    })
    return {"candidate_id": candidate_id, "review_status": new_status, "reviewed_by": reviewer,
            "message": "Decision recorded. Approval does not automatically promote a candidate into live surveillance."}


@router.post("/admin/pipeline/candidates/{candidate_id}/correct", summary="Correct extracted fields after checking the official PDF")
def correct_candidate(candidate_id: str, correction: CandidateCorrection, authorization: str | None = Header(default=None)):
    ensure_pipeline_schema()
    reviewer = _reviewer_from_header(authorization)
    if correction.reporting_start_date > correction.reporting_end_date:
        raise HTTPException(status_code=422, detail="Reporting start date must be on or before the end date")
    if (correction.reporting_end_date - correction.reporting_start_date).days > 14:
        raise HTTPException(status_code=422, detail="Weekly-report date range exceeds the 15-day sanity limit")
    with engine.begin() as connection:
        row = connection.execute(text("SELECT * FROM public.sk_ingestion_candidates WHERE candidate_id=:id FOR UPDATE"), {"id": candidate_id}).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if row["review_status"] != "pending_supervisor_review":
            raise HTTPException(status_code=409, detail="Only pending candidates can be corrected")
        candidate = {
            "source_url": row["source_url"], "report_year": correction.report_year, "report_week": correction.report_week,
            "state": correction.state.strip(), "district": correction.district.strip(), "disease": correction.disease.strip(),
            "reporting_start_date": correction.reporting_start_date, "reporting_end_date": correction.reporting_end_date,
            "cases": correction.cases, "deaths": correction.deaths,
        }
        from .ingestion_pipeline import validate_candidate
        errors = validate_candidate(candidate)
        status = "passed_preliminary_checks" if not errors else "needs_review"
        action_at = datetime.now(timezone.utc)
        connection.execute(text("""
            UPDATE public.sk_ingestion_candidates SET report_year=:year, report_week=:week, state=:state,
                district=:district, disease=:disease, reporting_start_date=:start_date, reporting_end_date=:end_date,
                cases=:cases, deaths=:deaths, validation_status=:validation_status,
                validation_errors=CAST(:errors AS JSONB), reviewer_note=:note, reviewed_by=:reviewer,
                updated_at=:now WHERE candidate_id=:id
        """), {"year": correction.report_year, "week": correction.report_week, "state": correction.state.strip(),
              "district": correction.district.strip(), "disease": correction.disease.strip(),
              "start_date": correction.reporting_start_date, "end_date": correction.reporting_end_date,
              "cases": correction.cases, "deaths": correction.deaths, "validation_status": status,
              "errors": json.dumps(errors), "note": correction.correction_note.strip(), "reviewer": reviewer,
              "now": action_at, "id": candidate_id})
        _insert_audit(connection, candidate_id, "corrected", reviewer, correction.correction_note.strip(), {
            "validation_status": status, "validation_errors": errors, "report_year": correction.report_year,
            "report_week": correction.report_week, "state": correction.state.strip(), "district": correction.district.strip(),
            "disease": correction.disease.strip(), "reporting_start_date": correction.reporting_start_date.isoformat(),
            "reporting_end_date": correction.reporting_end_date.isoformat(), "cases": correction.cases, "deaths": correction.deaths,
        })
    event_type = "candidate_corrected"
    _insert_event(f"corrected:{candidate_id}:{action_at.isoformat()}", event_type, {
        "type": event_type, "created_at": action_at.isoformat(), "candidate_id": candidate_id,
        "reviewed_by": reviewer, "validation_status": status, "is_synthetic": False,
        "message": "A reviewer corrected extracted fields. The candidate remains staged and requires a separate approval.",
    })
    return {"candidate_id": candidate_id, "validation_status": status, "validation_errors": errors,
            "reviewer": reviewer, "message": "Corrected values are still staged. Approve them separately after verifying the official PDF."}

@router.post(
    "/admin/pipeline/candidates/{candidate_id}/promote",
    summary="Explicitly promote an approved NCDC candidate with duplicate protection",
)
async def promote_candidate(
    candidate_id: str,
    promotion: CandidatePromotion = CandidatePromotion(),
    authorization: str | None = Header(default=None),
):
    ensure_pipeline_schema()
    reviewer = _reviewer_from_header(authorization)

    with engine.begin() as connection:

        row = connection.execute(text("""
            SELECT *
            FROM public.sk_ingestion_candidates
            WHERE candidate_id=:id
            FOR UPDATE
        """), {"id": candidate_id}).mappings().first()

        if not row:
            raise HTTPException(status_code=404, detail="Candidate not found")

        row = dict(row)

        if row.get("review_status") == "promoted" and row.get("promoted_record_id"):
            return {
                "candidate_id": candidate_id,
                "record_id": row["promoted_record_id"],
                "status": "already_promoted",
            }

        if row.get("review_status") != "approved":
            raise HTTPException(
                status_code=409,
                detail="A human reviewer must approve the candidate before promotion",
            )

        if row.get("validation_status") != "passed_preliminary_checks" or row.get("validation_errors"):
            raise HTTPException(
                status_code=422,
                detail="Candidate has not passed preliminary validation",
            )

        if row.get("cases") is None:
            raise HTTPException(
                status_code=422,
                detail="Case count is unknown; cannot promote this candidate",
            )

        if not is_allowed_source_url(row.get("source_url", ""), "NCDC"):
            raise HTTPException(
                status_code=422,
                detail="Source is not an allowlisted official NCDC HTTPS URL",
            )

        year = int(row["report_year"])
        week = int(row["report_week"])
        start_date = row.get("reporting_start_date")
        end_date = row.get("reporting_end_date")

        if not start_date or not end_date:
            raise HTTPException(
                status_code=422,
                detail="Source reporting dates have not been explicitly verified",
            )

        if start_date > end_date or (end_date - start_date).days > 14:
            raise HTTPException(
                status_code=422,
                detail="Source reporting date range is invalid",
            )

        # Serialize application-level promotions for the same outbreak identity.
        lock_key = (
            f"{year}|{week}|{str(row['state']).strip().casefold()}|"
            f"{str(row['district']).strip().casefold()}|"
            f"{str(row['disease']).strip().casefold()}"
        )

        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": lock_key},
        )

        # Recheck all three tables inside the promotion transaction.
        duplicates = _find_candidate_duplicates(connection, row)

        if duplicates:
            reason = str(promotion.override_reason or "").strip()

            if not promotion.duplicate_override or len(reason) < 8:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": (
                            "Potential duplicate records were found. "
                            "Review the matches before promotion. "
                            "A supervisor override with a written reason is required."
                        ),
                        "duplicate_count": len(duplicates),
                        "matches": duplicates,
                        "override_required": True,
                    },
                )

        record_id = f"AUTO-NCDC-{candidate_id[:40]}"
        source_name = "NCDC/IDSP weekly report (human-reviewed candidate)"

        insert = connection.execute(text("""
            INSERT INTO public.idsp_surveillance (
                record_id, year, week, reporting_start_date, reporting_end_date,
                state, district, disease, cases, deaths,
                outbreak_status, source, source_url
            ) VALUES (
                :record_id, :year, :week, :start_date, :end_date,
                :state, :district, :disease, :cases, :deaths,
                :outbreak_status, :source, :source_url
            )
            ON CONFLICT (record_id) DO NOTHING
        """), {
            "record_id": record_id,
            "year": year,
            "week": week,
            "start_date": start_date,
            "end_date": end_date,
            "state": row["state"],
            "district": row["district"],
            "disease": row["disease"],
            "cases": row["cases"],
            "deaths": row["deaths"],
            "outbreak_status": "Human-reviewed candidate; not an official declaration",
            "source": source_name,
            "source_url": row["source_url"],
        })

        if insert.rowcount == 0:
            existing = connection.execute(
                text("SELECT id FROM public.idsp_surveillance WHERE record_id=:id"),
                {"id": record_id},
            ).first()

            if not existing:
                raise HTTPException(
                    status_code=409,
                    detail="Promotion conflict; no live record was changed",
                )

        promotion_time = datetime.now(timezone.utc)

        connection.execute(text("""
            UPDATE public.sk_ingestion_candidates
            SET review_status='promoted',
                promoted_record_id=:record_id,
                updated_at=:now,
                reviewed_by=COALESCE(reviewed_by, :reviewer)
            WHERE candidate_id=:id
        """), {
            "record_id": record_id,
            "now": promotion_time,
            "reviewer": reviewer,
            "id": candidate_id,
        })

        audit_note = (
            f"Explicitly promoted after source verification. "
            f"Duplicate override: {reason}"
            if duplicates else
            "Explicitly promoted after source verification. No matching records found."
        )

        _insert_audit(
            connection,
            candidate_id,
            "promoted",
            reviewer,
            audit_note,
            {
                "record_id": record_id,
                "year": year,
                "week": week,
                "state": row["state"],
                "district": row["district"],
                "disease": row["disease"],
                "cases": row["cases"],
                "deaths": row["deaths"],
                "duplicate_override": bool(duplicates),
                "override_reason": reason if duplicates else None,
                "duplicate_matches": duplicates,
            },
        )

    # Transaction committed. Broadcast events only after successful promotion.
    _insert_event(f"promoted:{candidate_id}", "surveillance_record_promoted", {
        "type": "surveillance_record_promoted",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "record_id": record_id,
        "candidate_id": candidate_id,
        "source_url": row["source_url"],
        "state": row["state"],
        "district": row["district"],
        "disease": row["disease"],
        "year": year,
        "week": week,
        "cases": row["cases"],
        "deaths": row["deaths"],
        "reviewed_by": reviewer,
        "is_synthetic": False,
        "message": "A source-verified and explicitly approved candidate was promoted to structured surveillance.",
    })

    try:
        with SessionLocal() as db:
            anomalies = _latest_anomalies(db)
        _persist_anomaly_events(anomalies)
    except Exception:
        pass

    delivery = await emit_pending_events()

    return {
        "candidate_id": candidate_id,
        "record_id": record_id,
        "status": "promoted",
        "duplicate_override": bool(duplicates),
        "duplicate_count": len(duplicates),
        "event_delivery": delivery,
        "note": (
            "Candidate promoted after supervisor duplicate override."
            if duplicates else
            "Candidate promoted after source verification. No matching records were found."
        ),
    }

@router.get("/admin/pipeline/audit", summary="Immutable audit history for candidate corrections, decisions and promotions")
def pipeline_audit(candidate_id: str | None = None, limit: int = Query(default=100, ge=1, le=500)):
    ensure_pipeline_schema()
    where = "WHERE candidate_id=:candidate_id" if candidate_id else ""
    with engine.begin() as connection:
        rows = connection.execute(text(f"""
            SELECT audit_id, candidate_id, action, actor, action_at, note, details
            FROM public.sk_candidate_audit {where} ORDER BY action_at DESC LIMIT :limit
        """), {"limit": limit, **({"candidate_id": candidate_id} if candidate_id else {})}).mappings().all()
    return {"items": [dict(row) for row in rows], "count": len(rows)}


@router.get("/admin/pipeline/events", summary="Stored pipeline event and broadcast history")
def pipeline_events(limit: int = Query(default=50, ge=1, le=200), pending_only: bool = False):
    ensure_pipeline_schema()
    where = "WHERE broadcast_at IS NULL" if pending_only else ""
    with engine.begin() as connection:
        rows = connection.execute(text(f"""
          SELECT event_id, fingerprint, event_type, created_at, payload, broadcast_at
          FROM public.sk_pipeline_events {where} ORDER BY created_at DESC LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return {"items": [dict(r) for r in rows], "count": len(rows)}


class CandidateSourceRepair(BaseModel):
    source_url: str
    reviewer_note: str = Field(min_length=8, max_length=1500)


@router.post("/admin/pipeline/candidates/{candidate_id}/repair-source")
async def repair_candidate_source(
    candidate_id: str,
    repair: CandidateSourceRepair,
    authorization: str | None = Header(default=None),
):
    from .ingestion_pipeline import (
        _download_official_pdf,
        parse_candidate_pdf,
        parse_report_period,
    )
    import hashlib

    reviewer = _reviewer_from_header(authorization)
    ensure_pipeline_schema()

    url = repair.source_url.strip()

    if not is_allowed_source_url(url, "NCDC"):
        raise HTTPException(422, "Invalid official NCDC source URL")

    with engine.connect() as connection:
        row = connection.execute(text("""
            SELECT *
            FROM public.sk_ingestion_candidates
            WHERE candidate_id = :id
        """), {"id": candidate_id}).mappings().first()

    if not row:
        raise HTTPException(404, "Candidate not found")

    row = dict(row)

    if row["review_status"] != "pending_supervisor_review":
        raise HTTPException(409, "Only pending candidates can be repaired")

    record_id = row.get("source_record_id")

    if not record_id:
        match = re.search(
            r"[A-Z]{2}/[A-Z]{2,4}/[0-9]{4}/[0-9]+/[0-9]+",
            row.get("raw_excerpt") or "",
        )
        record_id = match.group(0) if match else None

    if not record_id:
        raise HTTPException(422, "Original outbreak identity unavailable")


    year, week = parse_report_period(url)

    if (year, week) != (row["report_year"], row["report_week"]):
        raise HTTPException(422, "Replacement report period does not match")

    try:
        content = await asyncio.to_thread(_download_official_pdf, url)
        sha = hashlib.sha256(content).hexdigest()

        candidates = await asyncio.to_thread(
            parse_candidate_pdf, content, url, "", sha
        )
    except Exception:
        import logging
        logging.getLogger("uvicorn.error").exception(
            "NCDC replacement PDF download or extraction failed"
        )
        raise HTTPException(422, "Replacement PDF download or extraction failed")

    matches = [
        c for c in candidates
        if str(c.get("source_record_id") or "").strip().upper()
        == str(record_id).strip().upper()
    ]

    if len(matches) != 1:
        raise HTTPException(422, "Replacement outbreak identity is not unique")

    candidate = matches[0]

    fields = (
        "state", "district", "disease", "cases", "deaths",
        "reporting_start_date", "reporting_end_date",
    )

    def normalized(value):
        return str(value).strip().casefold()

    mismatches = [
        field for field in fields
        if normalized(row.get(field)) != normalized(candidate.get(field))
    ]

    if mismatches:
        raise HTTPException(422, "Replacement outbreak fields do not match")

    page = candidate.get("source_page")

    if not page:
        raise HTTPException(422, "Replacement source page unavailable")

    with engine.begin() as connection:
        current = connection.execute(text("""
            SELECT *
            FROM public.sk_ingestion_candidates
            WHERE candidate_id = :id
            FOR UPDATE
        """), {"id": candidate_id}).mappings().first()

        if not current:
            raise HTTPException(404, "Candidate not found")

        if (
            current["review_status"] != "pending_supervisor_review"
            or current["updated_at"] != row["updated_at"]
            or current["source_url"] != row["source_url"]
            or current["source_sha256"] != row["source_sha256"]
        ):
            raise HTTPException(409, "Candidate changed during verification")

        if current["source_url"] == url and current["source_sha256"] == sha:
            return {
                "status": "already_repaired",
                "candidate_id": candidate_id,
            }

        connection.execute(text("""
            UPDATE public.sk_ingestion_candidates
            SET source_url = :url,
                source_sha256 = :sha,
                source_page = :page,
                source_record_id = :record_id,
                updated_at = NOW()
            WHERE candidate_id = :id
        """), {
            "url": url,
            "sha": sha,
            "page": page,
            "record_id": record_id,
            "id": candidate_id,
        })

        _insert_audit(
            connection,
            candidate_id,
            "source_repaired",
            reviewer,
            repair.reviewer_note,
            {
                "old_source_url": row["source_url"],
                "old_source_sha256": row["source_sha256"],
                "old_source_page": row.get("source_page"),
                "old_source_record_id": row.get("source_record_id"),
                "new_source_url": url,
                "new_source_sha256": sha,
                "new_source_page": page,
                "source_record_id": record_id,
                "verified_fields": list(fields),
            },
        )

    return {
        "status": "source_repaired",
        "candidate_id": candidate_id,
        "source_url": url,
        "source_sha256": sha,
        "source_page": page,
        "verified_fields": len(fields),
        "review_status": "pending_supervisor_review",
        "live_records_added": 0,
    }
