"""Authenticated operations for the automated ingestion and validation pipeline.

In the current app, a global bearer-token middleware protects HTTP routes. These
endpoints still require a valid reviewer token; they never disable authentication.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import date, datetime, timezone
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

router = APIRouter(tags=["Automated Source Ingestion Pipeline"])


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


def _insert_audit(connection, candidate_id: str, action: str, actor: str, note: str, details: dict | None = None) -> datetime:
    now = datetime.now(timezone.utc)
    connection.execute(text("""
        INSERT INTO public.sk_candidate_audit (audit_id, candidate_id, action, actor, action_at, note, details)
        VALUES (:id, :candidate_id, :action, :actor, :now, :note, CAST(:details AS JSONB))
    """), {"id": __import__("uuid").uuid4().hex, "candidate_id": candidate_id, "action": action,
          "actor": actor, "now": now, "note": note[:1500], "details": json.dumps(details or {})})
    return now


@router.post("/internal/pipeline/run-scheduled", summary="Run the pipeline from a configured external scheduler")
async def run_pipeline_scheduled(x_pipeline_token: str | None = Header(default=None, alias="X-Pipeline-Token")):
    # This single route is exempted from global Bearer middleware only because it has a separate
    # long random shared-secret guard. No admin endpoints are exempted.
    configured = os.getenv("SK_PIPELINE_CRON_TOKEN", "")
    if not configured:
        raise HTTPException(status_code=503, detail="Scheduled runner secret is not configured on the API service")
    if not cron_token_matches(configured, x_pipeline_token):
        raise HTTPException(status_code=403, detail="Scheduled runner token rejected")
    result = await asyncio.to_thread(run_pipeline_cycle)
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
            ORDER BY created_at DESC LIMIT :limit
        """), {"limit": limit, **({"review_status": review_status} if review_status else {})}).mappings().all()
    return {"items": [dict(row) for row in rows], "count": len(rows),
            "note": "Candidate extraction may be incomplete or misaligned by PDF text extraction. Check the cited source PDF before approval."}


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
        if candidate["review_status"] == "promoted":
            raise HTTPException(status_code=409, detail="Promoted candidates cannot be reviewed again")
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


@router.post("/admin/pipeline/candidates/{candidate_id}/promote", summary="Explicitly promote an approved NCDC candidate")
async def promote_candidate(candidate_id: str, authorization: str | None = Header(default=None)):
    ensure_pipeline_schema()
    reviewer = _reviewer_from_header(authorization)
    with engine.begin() as connection:
        row = connection.execute(text("""
            SELECT * FROM public.sk_ingestion_candidates WHERE candidate_id=:id FOR UPDATE
        """), {"id": candidate_id}).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Candidate not found")
        row = dict(row)
        if row.get("review_status") == "promoted" and row.get("promoted_record_id"):
            return {"candidate_id": candidate_id, "record_id": row["promoted_record_id"], "status": "already_promoted"}
        if row.get("review_status") != "approved":
            raise HTTPException(status_code=409, detail="A human reviewer must approve the candidate before promotion")
        if row.get("validation_status") != "passed_preliminary_checks" or row.get("validation_errors"):
            raise HTTPException(status_code=422, detail="Candidate has not passed preliminary validation")
        if row.get("cases") is None:
            raise HTTPException(status_code=422, detail="Case count is unknown; cannot promote this candidate")
        if not is_allowed_source_url(row.get("source_url", ""), "NCDC"):
            raise HTTPException(status_code=422, detail="Source is not an allowlisted official NCDC HTTPS URL")
        year, week = int(row["report_year"]), int(row["report_week"])
        start_date, end_date = row.get("reporting_start_date"), row.get("reporting_end_date")
        if not start_date or not end_date:
            raise HTTPException(status_code=422, detail="Source reporting dates have not been explicitly verified; correct the candidate before promotion")
        if start_date > end_date or (end_date - start_date).days > 14:
            raise HTTPException(status_code=422, detail="Source reporting date range is invalid")
        record_id = f"AUTO-NCDC-{candidate_id[:40]}"
        source_name = "NCDC/IDSP weekly report (human-reviewed candidate)"
        insert = connection.execute(text("""
            INSERT INTO public.idsp_surveillance (
                record_id, year, week, reporting_start_date, reporting_end_date,
                state, district, disease, cases, deaths, outbreak_status, source, source_url
            ) VALUES (
                :record_id, :year, :week, :start_date, :end_date,
                :state, :district, :disease, :cases, :deaths, :outbreak_status, :source, :source_url
            ) ON CONFLICT (record_id) DO NOTHING
        """), {
            "record_id": record_id, "year": year, "week": week, "start_date": start_date, "end_date": end_date,
            "state": row["state"], "district": row["district"], "disease": row["disease"],
            "cases": row["cases"], "deaths": row["deaths"], "outbreak_status": "Human-reviewed candidate; not an official declaration",
            "source": source_name, "source_url": row["source_url"],
        })
        if insert.rowcount == 0:
            # An existing record_id is safe only if this candidate already has a promotion link.
            existing = connection.execute(text("SELECT id FROM public.idsp_surveillance WHERE record_id=:id"), {"id": record_id}).first()
            if not existing:
                raise HTTPException(status_code=409, detail="Promotion conflict; no live record was changed")
        promotion_time = datetime.now(timezone.utc)
        connection.execute(text("""
            UPDATE public.sk_ingestion_candidates SET review_status='promoted', promoted_record_id=:record_id,
                updated_at=:now, reviewed_by=COALESCE(reviewed_by, :reviewer)
            WHERE candidate_id=:id
        """), {"record_id": record_id, "now": promotion_time, "reviewer": reviewer, "id": candidate_id})
        _insert_audit(connection, candidate_id, "promoted", reviewer, "Explicitly promoted after source verification.", {"record_id": record_id, "year": year, "week": week, "state": row["state"], "district": row["district"], "disease": row["disease"], "cases": row["cases"], "deaths": row["deaths"]})
    # The promotion transaction is committed. Queue the event only after the live row exists.
    _insert_event(f"promoted:{candidate_id}", "surveillance_record_promoted", {
        "type": "surveillance_record_promoted", "created_at": datetime.now(timezone.utc).isoformat(),
        "record_id": record_id, "candidate_id": candidate_id, "source_url": row["source_url"],
        "state": row["state"], "district": row["district"], "disease": row["disease"],
        "year": year, "week": week, "cases": row["cases"], "deaths": row["deaths"],
        "reviewed_by": reviewer, "is_synthetic": False,
        "message": "A source-verified and explicitly approved candidate was promoted to structured surveillance.",
    })
    # A newly promoted row is now part of the eligible history. Run screening again and queue events.
    try:
        with SessionLocal() as db:
            anomalies = _latest_anomalies(db)
        _persist_anomaly_events(anomalies)
    except Exception:
        # Promotion has committed. This is a screening failure, not a reason to undo approved data.
        pass
    delivery = await emit_pending_events()
    return {"candidate_id": candidate_id, "record_id": record_id, "status": "promoted",
            "event_delivery": delivery,
            "note": "Human-reviewed candidate inserted into structured surveillance. Screening alerts still require public-health review."}


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
