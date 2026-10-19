import asyncio
from contextlib import suppress
from datetime import datetime, timezone

import os
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Hospital, IDSPSurveillance

from app.disease_routes import router as disease_router
from app.idsp_routes import router as idsp_router
from app.advanced_routes import router as advanced_router
from app.evidence_assistant import router as evidence_assistant_router  # SK_EVIDENCE_ASSISTANT_V1
from app.source_routes import router as source_router, public_global_outbreaks
from app.india_reports_routes import public_india_outbreak_reports, router as india_reports_router
from app.report_review_queue import router as report_review_queue_router, sync_ncdc_report_queue
from app.staging_preview_routes import router as staging_preview_router
from app.auth_security import decode_access_token
from app.auth_routes import router as auth_router
app = FastAPI(
    title="Samraksha Kendra",
    description=(
        "Digital Disease Surveillance and "
        "Early Warning System"
    ),
    version="1.0.0"
)

# Authentication is enforced for every HTTP endpoint except login and API docs.
_PUBLIC_HTTP_PATHS = {"/", "/auth/login", "/docs", "/openapi.json", "/redoc", "/favicon.ico"}

@app.middleware("http")
async def require_bearer_token(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or path in _PUBLIC_HTTP_PATHS or path.startswith("/docs/"):
        response = await call_next(request)
    else:
        auth_header = request.headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")
        claims = decode_access_token(token.strip()) if scheme.lower() == "bearer" and token.strip() else None
        if not claims:
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required. Sign in to continue."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.on_event("startup")
async def _initialize_database_schema():
    # Create missing ORM tables; this does not delete existing tables or rows.
    Base.metadata.create_all(bind=engine)

    # Keep NCDC candidate staging separate from live surveillance records.
    ddl = """
    CREATE TABLE IF NOT EXISTS public.ncdc_outbreak_staging (
        record_id TEXT PRIMARY KEY,
        report_year INTEGER NOT NULL,
        report_week INTEGER NOT NULL CHECK (report_week BETWEEN 1 AND 53),
        state TEXT NOT NULL,
        district TEXT NOT NULL,
        disease TEXT NOT NULL,
        cases INTEGER NULL CHECK (cases IS NULL OR cases >= 0),
        deaths INTEGER NULL CHECK (deaths IS NULL OR deaths >= 0),
        outbreak_start_date DATE NULL,
        reporting_date DATE NULL,
        current_status TEXT NULL,
        comments_action_taken TEXT NULL,
        source_url TEXT NOT NULL,
        source_index_url TEXT NOT NULL,
        extracted_at_utc TIMESTAMPTZ NULL,
        source_validation_status TEXT NOT NULL,
        source_validation_note TEXT NULL,
        review_status TEXT NOT NULL DEFAULT 'pending_supervisor_review',
        imported_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """
    with engine.begin() as connection:
        connection.execute(text(ddl))

# Refresh official publication feeds on the server, even when nobody has the tab open.
# These are public notices/report links, not continuous case-count feeds.
async def _source_refresh_loop():
    while True:
        try:
            refresh_results = await asyncio.gather(
                asyncio.to_thread(public_global_outbreaks, limit=50, force_refresh=True),
                asyncio.to_thread(public_india_outbreak_reports, limit=100, force_refresh=True),
                return_exceptions=True,
            )
            # Persist newly discovered official NCDC PDFs for human review; never import PDF counts here.
            try:
                india_result = refresh_results[1] if len(refresh_results) > 1 else None
                if isinstance(india_result, dict):
                    await asyncio.to_thread(sync_ncdc_report_queue, india_result)
            except Exception:
                # Discovery-queue failures must not stop the core API or later refreshes.
                pass
        except Exception:
            # The source endpoints preserve last-known data and expose stale/unavailable status.
            pass
        await asyncio.sleep(15 * 60)

@app.on_event("startup")
async def _start_background_source_refresh():
    app.state.source_refresh_task = asyncio.create_task(_source_refresh_loop())

@app.on_event("shutdown")
async def _stop_background_source_refresh():
    task = getattr(app.state, "source_refresh_task", None)
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv(
            "SK_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if origin.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.get("/")
def root():

    return {
        "project": "Samraksha Kendra",
        "status": "running",
        "message": (
            "Digital Disease Surveillance and "
            "Early Warning System"
        )
    }


# ============================================================
# HOSPITAL COUNT
# ============================================================

@app.get("/hospitals/count")
def hospital_count(
    db: Session = Depends(get_db)
):

    count = db.query(Hospital).count()

    return {
        "count": count
    }


# ============================================================
# HOSPITAL SEARCH
# ============================================================

@app.get("/hospitals")
def get_hospitals(
    search: str | None = None,
    state: str | None = None,
    district: str | None = None,
    category: str | None = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):

    query = db.query(Hospital)

    if search:
        query = query.filter(
            Hospital.name.ilike(
                f"%{search}%"
            )
        )

    if state:
        query = query.filter(
            Hospital.state.ilike(
                f"%{state}%"
            )
        )

    if district:
        query = query.filter(
            Hospital.district.ilike(
                f"%{district}%"
            )
        )

    if category:
        query = query.filter(
            Hospital.category.ilike(
                f"%{category}%"
            )
        )

    hospitals = (
        query
        .limit(limit)
        .all()
    )

    return [
        {
            "id": hospital.id,
            "name": hospital.name,
            "state": hospital.state,
            "district": hospital.district,
            "city": hospital.city,
            "category": hospital.category,
            "address": hospital.address,
            "pincode": hospital.pincode,
            "phone": hospital.phone,
            "email": hospital.email,
            "website": hospital.website
        }
        for hospital in hospitals
    ]


# ============================================================
# ROUTERS
# ============================================================

app.include_router(auth_router)
app.include_router(disease_router)
app.include_router(idsp_router)
app.include_router(advanced_router)
app.include_router(evidence_assistant_router)  # SK_EVIDENCE_ASSISTANT_V1
app.include_router(source_router)
app.include_router(india_reports_router)
app.include_router(report_review_queue_router)
app.include_router(staging_preview_router)

@app.get("/system/source-status", tags=["System status"], summary="Database and live-publication source freshness")
def source_status(db: Session = Depends(get_db)):
    who = public_global_outbreaks(limit=50, force_refresh=False)
    india = public_india_outbreak_reports(limit=100, force_refresh=False)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "structured_surveillance_records": db.query(IDSPSurveillance).count(),
        "record_count_note": "This count includes structured surveillance rows only. WHO notices and NCDC report links are separate publication feeds and are not added to case totals.",
        "refresh_interval_minutes": 15,
        "sources": [
            {"name": "WHO Disease Outbreak News", "status": who.get("status"), "items_available": who.get("count", 0), "last_checked_at": who.get("last_checked_at"), "last_successful_fetch_at": who.get("last_successful_fetch_at"), "source_url": who.get("source_url"), "warning": who.get("warning")},
            {"name": "NCDC/IDSP weekly report catalogue", "status": india.get("status"), "items_available": india.get("count", 0), "last_checked_at": india.get("last_checked_at"), "last_successful_fetch_at": india.get("last_successful_fetch_at"), "source_url": india.get("source_url"), "warning": india.get("warning")},
        ],
    }

# SK_AUTOMATED_INGESTION_PIPELINE_BEGIN
# These admin routes are protected by the app's existing bearer-token middleware.
from contextlib import asynccontextmanager as _sk_asynccontextmanager
from app.pipeline_routes import router as pipeline_router
from app.ingestion_pipeline import start_pipeline_worker as _sk_start_pipeline_worker, stop_pipeline_worker as _sk_stop_pipeline_worker
app.include_router(pipeline_router)

# Wrap, rather than replace, the existing FastAPI lifespan so pre-existing startup/shutdown hooks stay active.
_sk_original_lifespan_context = app.router.lifespan_context
@_sk_asynccontextmanager
async def _sk_combined_lifespan(application):
    async with _sk_original_lifespan_context(application):
        await _sk_start_pipeline_worker()
        try:
            yield
        finally:
            await _sk_stop_pipeline_worker()
app.router.lifespan_context = _sk_combined_lifespan
# SK_AUTOMATED_INGESTION_PIPELINE_END

