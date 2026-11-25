
"""Public-data, anomaly, ICA, and WebSocket routes for Samraksha Kendra."""
from __future__ import annotations

import asyncio
from contextlib import suppress

import csv
import io
import uuid
from datetime import datetime, timezone
from typing import Any


from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from .anomaly_service import (
    detect_case_anomalies,
    get_anomaly_diagnostics,
)
from .database import get_db
from .ica_service import ICAInputError, run_ica_analysis
from .models import IDSPSurveillance
from .synthetic_ingestion import LOCATIONS, SyntheticSurveillance
from .websocket_manager import manager
from .auth_security import decode_access_token

from .anomaly_service import run_synthetic_anomaly_screening_fixture

router = APIRouter(tags=["Public Data and Advanced Analytics"])


def _filtered_query(
    db: Session,
    *,
    state: str | None = None,
    district: str | None = None,
    disease: str | None = None,
    year: int | None = None,
):
    query = db.query(IDSPSurveillance)

    if state and state.strip():
        query = query.filter(
            IDSPSurveillance.state.ilike(f"%{state.strip()}%")
        )

    if district and district.strip():
        query = query.filter(
            IDSPSurveillance.district.ilike(f"%{district.strip()}%")
        )

    if disease and disease.strip():
        query = query.filter(
            IDSPSurveillance.disease.ilike(f"%{disease.strip()}%")
        )

    if year is not None:
        query = query.filter(IDSPSurveillance.year == year)

    return query


def _serialise(row: IDSPSurveillance) -> dict[str, Any]:
    def iso(value: Any) -> Any:
        if value is not None and hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    return {
        "record_id": row.record_id,
        "year": row.year,
        "week": row.week,
        "reporting_start_date": iso(row.reporting_start_date),
        "reporting_end_date": iso(row.reporting_end_date),
        "state": row.state,
        "district": row.district,
        "disease": row.disease,
        "cases": int(row.cases or 0),
        "deaths": int(row.deaths or 0),
        "outbreak_status": row.outbreak_status,
        "source": row.source,
        "source_url": row.source_url,
    }
def _serialise_synthetic(row: SyntheticSurveillance) -> dict[str, Any]:
    return {
        "record_id": row.record_id,
        "year": row.year,
        "week": row.week,
        "reporting_start_date": row.reporting_start_date.isoformat(),
        "reporting_end_date": row.reporting_end_date.isoformat(),
        "state": row.state,
        "district": row.district,
        "disease": row.disease,
        "cases": int(row.cases or 0),
        "deaths": int(row.deaths or 0),
        "outbreak_status": row.outbreak_status,
        "source": "SYNTHETIC_GENERATOR",
        "source_url": None,
        "is_synthetic": True,
    }



def _synthetic_records_for_analysis(db: Session) -> list[dict[str, Any]]:
    """Load only explicitly labelled synthetic records for anomaly screening."""
    rows = (
        db.query(SyntheticSurveillance)
        .filter(SyntheticSurveillance.is_synthetic.is_(True))
        .all()
    )

    return [_serialise_synthetic(row) for row in rows]
def _records_for_analysis(db: Session) -> list[dict[str, Any]]:
    rows = db.query(IDSPSurveillance).all()

    return [
        {
            "record_id": row.record_id,
            "year": row.year,
            "week": row.week,
            "state": row.state,
            "district": row.district,
            "disease": row.disease,
            "cases": row.cases,
            "deaths": row.deaths,
            "source": row.source,
            "source_url": row.source_url,
        }
        for row in rows
    ]


@router.get(
    "/analytics/anomalies/demo-screening",
    summary="Validate anomaly screening on a clearly synthetic fixture",
)
def synthetic_anomaly_screening_demo():
    """Run a deterministic detector test; does not query or change the database."""
    return run_synthetic_anomaly_screening_fixture()
@router.get(
    "/analytics/anomalies/synthetic",
    summary="Screen synthetic surveillance records for simulated anomalies",
)
def synthetic_historical_anomalies(
    min_history: int = Query(default=4, ge=2, le=4),
    db: Session = Depends(get_db),
):
    records = _synthetic_records_for_analysis(db)

    anomalies = detect_case_anomalies(
        records,
        min_history=min_history,
    )

    diagnostics = get_anomaly_diagnostics(
        records,
        min_history=min_history,
    )

    for item in anomalies:
        item["is_synthetic"] = True
        item["source"] = "SYNTHETIC_GENERATOR"
        item["signal_type"] = "SIMULATED_ANOMALY"

    if diagnostics["valid_source_records"] == 0:
        status = "no_synthetic_records"
    elif diagnostics["evaluable_periods"] == 0:
        status = "insufficient_synthetic_history"
    elif anomalies:
        status = "synthetic_signals_detected"
    else:
        status = "no_synthetic_signals_detected"

    return {
        "method": "Trailing median + robust MAD",
        "status": status,
        "is_synthetic": True,
        "count": len(anomalies),
        "items": anomalies,
        "diagnostics": diagnostics,
        "caution": (
            "SIMULATED DATA ONLY. These results are not official surveillance "
            "findings, confirmed outbreaks, or public-health alerts. "
            "They must not be mixed with official anomaly events."
        ),
    }

@router.get(
    "/public/surveillance",
    summary="Browse public aggregate surveillance records",
)

def public_surveillance(
    state: str | None = None,
    district: str | None = None,
    disease: str | None = None,
    year: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    source: str = Query(default="official"),
    db: Session = Depends(get_db),
):
    if source not in {"official", "synthetic", "all"}:
        raise HTTPException(
            status_code=400,
            detail="source must be official, synthetic, or all",
        )

    records = []

    # Official records remain separate.
    if source in {"official", "all"}:
        query = _filtered_query(
            db,
            state=state,
            district=district,
            disease=disease,
            year=year,
        )

        official_rows = query.all()

        records.extend(
            {
                **_serialise(row),
                "is_synthetic": False,
            }
            for row in official_rows
        )

    # Synthetic records come from their own database table.
    if source in {"synthetic", "all"}:
        synthetic_query = db.query(SyntheticSurveillance)

        if state:
            synthetic_query = synthetic_query.filter(
                SyntheticSurveillance.state.ilike(f"%{state}%")
            )
        if district:
            synthetic_query = synthetic_query.filter(
                SyntheticSurveillance.district.ilike(f"%{district}%")
            )
        if disease:
            synthetic_query = synthetic_query.filter(
                SyntheticSurveillance.disease.ilike(f"%{disease}%")
            )
        if year is not None:
            synthetic_query = synthetic_query.filter(
                SyntheticSurveillance.year == year
            )

        synthetic_rows = synthetic_query.all()
        records.extend(_serialise_synthetic(row) for row in synthetic_rows)

    # Newest year/week first; keep state and disease alphabetical.
    records.sort(
        key=lambda item: (
            -int(item["year"] or 0),
            -int(item["week"] or 0),
            item["state"] or "",
            item["disease"] or "",
        )
    )

    total = len(records)
    start = (page - 1) * page_size
    page_items = records[start : start + page_size]

    return {
        "items": page_items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
        "source_filter": source,
        "data_note": (
            "Synthetic records are generated sample data and are not "
            "official outbreak reports."
            if source == "synthetic"
            else (
                "Official and synthetic records are shown together. "
                "Synthetic records are explicitly labelled."
                if source == "all"
                else
                "Official aggregate surveillance records only; source "
                "availability and completeness may vary."
            )
        ),
    }


@router.get(
    "/public/surveillance/summary",
    summary="Summary statistics for public surveillance data",
)
def public_surveillance_summary(
    state: str | None = None,
    district: str | None = None,
    disease: str | None = None,
    year: int | None = None,
    db: Session = Depends(get_db),
):
    filtered = _filtered_query(
        db,
        state=state,
        district=district,
        disease=disease,
        year=year,
    )

    total_records = filtered.count()

    total_cases = (
        filtered.with_entities(
            func.coalesce(func.sum(IDSPSurveillance.cases), 0)
        ).scalar()
        or 0
    )

    total_deaths = (
        filtered.with_entities(
            func.coalesce(func.sum(IDSPSurveillance.deaths), 0)
        ).scalar()
        or 0
    )

    states_count = (
        filtered.with_entities(
            func.count(func.distinct(IDSPSurveillance.state))
        ).scalar()
        or 0
    )

    disease_count = (
        filtered.with_entities(
            func.count(func.distinct(IDSPSurveillance.disease))
        ).scalar()
        or 0
    )

    top_states_rows = (
        filtered.with_entities(
            IDSPSurveillance.state,
            func.coalesce(
                func.sum(IDSPSurveillance.cases), 0
            ).label("cases"),
        )
        .group_by(IDSPSurveillance.state)
        .order_by(func.sum(IDSPSurveillance.cases).desc())
        .limit(8)
        .all()
    )

    top_diseases_rows = (
        filtered.with_entities(
            IDSPSurveillance.disease,
            func.coalesce(
                func.sum(IDSPSurveillance.cases), 0
            ).label("cases"),
        )
        .group_by(IDSPSurveillance.disease)
        .order_by(func.sum(IDSPSurveillance.cases).desc())
        .limit(8)
        .all()
    )

    trend_rows = (
        filtered.with_entities(
            IDSPSurveillance.year,
            IDSPSurveillance.week,
            func.coalesce(
                func.sum(IDSPSurveillance.cases), 0
            ).label("cases"),
        )
        .group_by(
            IDSPSurveillance.year,
            IDSPSurveillance.week,
        )
        .order_by(
            IDSPSurveillance.year.desc(),
            IDSPSurveillance.week.desc(),
        )
        .limit(16)
        .all()
    )

    weekly_trend = [
        {
            "period": f"{row.year}-W{int(row.week):02d}",
            "year": row.year,
            "week": row.week,
            "cases": int(row.cases or 0),
        }
        for row in reversed(trend_rows)
    ]
        # Global dataset counts (independent of dashboard filters)
    idsp_total = db.query(IDSPSurveillance).count()

    approved_ncdc_count = (
        db.query(IDSPSurveillance)
        .filter(
            IDSPSurveillance.source.like(
                "NCDC/IDSP weekly %"
            )
        )
        .count()
    )

    official_idsp_count = idsp_total - approved_ncdc_count

    synthetic_count = (
        db.query(SyntheticSurveillance)
        .filter(SyntheticSurveillance.is_synthetic.is_(True))
        .count()
    )

    # Pending NCDC staging records; safely handle a missing staging table
    staging_table_exists = db.execute(
        text("SELECT to_regclass('public.ncdc_outbreak_staging')")
    ).scalar()

    pending_ncdc_count = 0

    if staging_table_exists:
        pending_ncdc_count = db.execute(
            text("""
                SELECT COUNT(*)
                FROM public.ncdc_outbreak_staging
                WHERE review_status = :status
            """),
            {"status": "pending_supervisor_review"},
        ).scalar() or 0

    total_live_records = (
        official_idsp_count
        + approved_ncdc_count
        + synthetic_count
    )

    return {
        "total_records": int(total_records),
        "official_idsp_records": int(official_idsp_count),
        "approved_ncdc_records": int(approved_ncdc_count),
        "synthetic_records": int(synthetic_count),
        "pending_ncdc_records": int(pending_ncdc_count),
        "total_live_records": int(total_live_records),
        "total_cases": int(total_cases),
        "total_deaths": int(total_deaths),
        "states_count": int(states_count),
        "diseases_count": int(disease_count),
        "weekly_trend": weekly_trend,
        "top_states": [
            {
                "name": row.state or "Unknown",
                "cases": int(row.cases or 0),
            }
            for row in top_states_rows
        ],
        "top_diseases": [
            {
                "name": row.disease or "Unknown",
                "cases": int(row.cases or 0),
            }
            for row in top_diseases_rows
        ],
        "data_note": (
            "Summary of records currently loaded into this installation; "
            "not a claim of exhaustive national coverage. Counts are sums "
            "of source rows and may not represent unique cases if rows overlap."
        ),
    }

@router.get(
    "/public/surveillance/synthetic/state-coverage",
    summary="State-wise synthetic surveillance record counts",
)
def synthetic_state_coverage(
    db: Session = Depends(get_db),
):
    rows = (
        db.query(
            SyntheticSurveillance.state,
            func.count(SyntheticSurveillance.id).label("records"),
        )
        .filter(SyntheticSurveillance.is_synthetic.is_(True))
        .group_by(SyntheticSurveillance.state)
        .all()
    )

    record_counts = {
        state: int(count)
        for state, count in rows
    }

    coverage = [
        {
            "state": state,
            "records": record_counts.get(state, 0),
        }
        for state in LOCATIONS
    ]

    coverage.sort(
        key=lambda item: (-item["records"], item["state"])
    )

    return {
        "source": "SYNTHETIC_GENERATOR",
        "is_synthetic": True,
        "total_states_uts": len(LOCATIONS),
        "covered_states_uts": sum(
            1 for item in coverage if item["records"] > 0
        ),
        "total_records": sum(
            item["records"] for item in coverage
        ),
        "coverage": coverage,
        "data_note": (
            "Illustrative synthetic records only. "
            "These counts are not official disease surveillance reports."
        ),
    }
@router.get(
    "/public/surveillance/export.csv",
    summary="Download filtered public aggregate data as CSV",
)
def export_public_surveillance(
    state: str | None = None,
    district: str | None = None,
    disease: str | None = None,
    year: int | None = None,
    db: Session = Depends(get_db),
):
    rows = (
        _filtered_query(
            db,
            state=state,
            district=district,
            disease=disease,
            year=year,
        )
        .order_by(
            IDSPSurveillance.year.desc(),
            IDSPSurveillance.week.desc(),
        )
        .limit(10000)
        .all()
    )

    buffer = io.StringIO()
    columns = [
        "record_id",
        "year",
        "week",
        "reporting_start_date",
        "reporting_end_date",
        "state",
        "district",
        "disease",
        "cases",
        "deaths",
        "outbreak_status",
        "source",
        "source_url",
    ]

    writer = csv.DictWriter(
        buffer,
        fieldnames=columns,
        extrasaction="ignore",
    )
    writer.writeheader()

    for row in rows:
        writer.writerow(_serialise(row))

    buffer.seek(0)

    headers = {
        "Content-Disposition": (
            'attachment; filename="samraksha_surveillance.csv"'
        )
    }

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get(
    "/analytics/anomalies",
    summary="Screen historical records for unusually high case counts",
)
def historical_anomalies(
    min_history: int = Query(default=4, ge=2, le=4),
    db: Session = Depends(get_db),
):
    records = _records_for_analysis(db)

    anomalies = detect_case_anomalies(
        records,
        min_history=min_history,
    )

    diagnostics = get_anomaly_diagnostics(
        records,
        min_history=min_history,
    )

    if diagnostics["valid_source_records"] == 0:
        status = "no_valid_surveillance_records"
    elif diagnostics["evaluable_periods"] == 0:
        status = "insufficient_history"
    elif anomalies:
        status = "screening_results_available"
    else:
        status = "no_anomalies_flagged"

    return {
        "method": "Trailing median + robust MAD",
        "status": status,
        "count": len(anomalies),
        "items": anomalies,
        "diagnostics": diagnostics,
        "screening_settings": {
            "minimum_history": min_history,
            "maximum_lookback_periods": 8,
            "exploratory_mode": min_history < 4,
        },
        "caution": (
            "These are automated screening results, not official outbreak "
            "declarations. Results with fewer than four historical "
            "observations are exploratory and less reliable. "
            "A flagged observation requires public-health review. "
            "No flags do not establish that no outbreak exists."
        ),
    }




@router.post(
    "/analytics/anomalies/run",
    summary="Persist anomaly screening events and deliver pending alerts",
)
async def run_anomaly_screening(db: Session = Depends(get_db)):
    records = _records_for_analysis(db)
    anomalies = detect_case_anomalies(records)

    # Persist through the existing idempotent pipeline event store.
    from .ingestion_pipeline import _persist_anomaly_events, emit_pending_events

    events_created = _persist_anomaly_events(anomalies)
    delivery = await emit_pending_events(limit=100)

    return {
        "count": len(anomalies),
        "events_created": events_created,
        "pending_events_seen": delivery["pending_events_seen"],
        "events_delivered": delivery["events_delivered"],
        "delivered_messages": delivery["clients_delivered"],
        "items": anomalies,
        "caution": (
            "Automated screening only. Review findings before taking action. "
            "Delivery counts indicate connected clients, not confirmed receipt "
            "or acknowledgement by a public-health authority."
        ),
    }


@router.post(
    "/analytics/demo-anomaly",
    summary="Broadcast a synthetic anomaly for demonstration only",
)
async def generate_demo_anomaly():
    """Broadcast a demo event without writing it to PostgreSQL."""
    now = datetime.now(timezone.utc)

    event = {
        "event_id": str(uuid.uuid4()),
        "type": "demo_anomaly",
        "created_at": now.isoformat(),
        "severity": "HIGH",
        "state": "DEMO STATE",
        "district": "DEMO DISTRICT",
        "disease": "Synthetic demonstration signal",
        "year": now.year,
        "week": int(now.strftime("%V")),
        "cases": 185,
        "baseline_median": 20,
        "mad_score": None,
        "method": "Synthetic test event",
        "source": "synthetic_demo",
        "is_synthetic": True,
        "message": (
            "DEMO ONLY: artificial case spike generated to test live "
            "notifications. This is not a real outbreak or surveillance record."
        ),
    }

    delivered = await manager.broadcast(event)

    return {
        "message": (
            "Synthetic demo event broadcast. No surveillance/database "
            "rows were changed."
        ),
        "delivered_clients": delivered,
        "event": event,
    }


@router.get(
    "/analytics/ica",
    summary="Experimental ICA on weekly disease-count signals",
)
def ica_analysis(
    components: int = Query(default=2, ge=2, le=5),
    db: Session = Depends(get_db),
):
    try:
        result = run_ica_analysis(
            _records_for_analysis(db),
            n_components=components,
        )
    except ICAInputError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                "ICA could not be completed with current data: "
                f"{exc}"
            ),
        ) from exc

    return result


@router.websocket("/ws/alerts")
async def live_alerts(websocket: WebSocket):
    # Browser WebSocket APIs cannot set Authorization headers. Require the first
    # message to authenticate so bearer tokens do not appear in URLs or proxy logs.
    accepted_into_manager = False
    await websocket.accept()
    try:
        auth_message = await websocket.receive_json()
        token = auth_message.get("token") if isinstance(auth_message, dict) and auth_message.get("type") == "authenticate" else None
        if not token or not decode_access_token(str(token)):
            await websocket.close(code=1008, reason="Authentication required")
            return

        await manager.connect(websocket, already_accepted=True)
        accepted_into_manager = True
        await websocket.send_json(
            {
                "type": "connection_ready",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "message": "Authenticated connection to Samraksha Kendra live alert stream.",
            }
        )
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() in {"ping", "heartbeat"}:
                await websocket.send_json({"type": "pong", "created_at": datetime.now(timezone.utc).isoformat()})
    except WebSocketDisconnect:
        pass
    except Exception:
        if not accepted_into_manager:
            with suppress(Exception):
                await websocket.close(code=1008, reason="Invalid authentication message")
    finally:
        if accepted_into_manager:
            await manager.disconnect(websocket)
