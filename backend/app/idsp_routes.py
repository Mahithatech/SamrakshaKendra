from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import IDSPSurveillance


router = APIRouter(
    prefix="/idsp",
    tags=["IDSP Surveillance"]
)


# ============================================================
# TOTAL IDSP RECORDS
# ============================================================

@router.get("/count")
def idsp_count(
    db: Session = Depends(get_db)
):
    count = db.query(IDSPSurveillance).count()

    return {
        "count": count
    }


# ============================================================
# TOTAL CASES
# ============================================================

@router.get("/cases")
def total_cases(
    db: Session = Depends(get_db)
):
    records = db.query(IDSPSurveillance).all()

    total = sum(
        record.cases or 0
        for record in records
    )

    return {
        "total_cases": total
    }


# ============================================================
# TOTAL DEATHS
# ============================================================

@router.get("/deaths")
def total_deaths(
    db: Session = Depends(get_db)
):
    records = db.query(IDSPSurveillance).all()

    total = sum(
        record.deaths or 0
        for record in records
    )

    return {
        "total_deaths": total
    }


# ============================================================
# DISEASE COUNT
# ============================================================

@router.get("/disease-count")
def disease_count(
    db: Session = Depends(get_db)
):
    diseases = (
        db.query(IDSPSurveillance.disease)
        .distinct()
        .all()
    )

    return {
        "count": len(diseases)
    }


# ============================================================
# LIST SURVEILLANCE RECORDS
# ============================================================

@router.get("/records")
def get_idsp_records(
    disease: str | None = None,
    state: str | None = None,
    district: str | None = None,
    week: int | None = None,
    year: int | None = None,
    limit: int = Query(
        default=100,
        ge=1,
        le=500
    ),
    db: Session = Depends(get_db)
):

    query = db.query(IDSPSurveillance)

    if disease:
        query = query.filter(
            IDSPSurveillance.disease.ilike(
                f"%{disease}%"
            )
        )

    if state:
        query = query.filter(
            IDSPSurveillance.state.ilike(
                f"%{state}%"
            )
        )

    if district:
        query = query.filter(
            IDSPSurveillance.district.ilike(
                f"%{district}%"
            )
        )

    if week:
        query = query.filter(
            IDSPSurveillance.week == week
        )

    if year:
        query = query.filter(
            IDSPSurveillance.year == year
        )

    records = (
        query
        .order_by(
            IDSPSurveillance.reporting_end_date.desc()
        )
        .limit(limit)
        .all()
    )

    return [
        {
            "record_id": record.record_id,
            "year": record.year,
            "week": record.week,
            "reporting_start_date":
                str(record.reporting_start_date),
            "reporting_end_date":
                str(record.reporting_end_date),
            "state": record.state,
            "district": record.district,
            "disease": record.disease,
            "cases": record.cases,
            "deaths": record.deaths,
            "outbreak_status":
                record.outbreak_status,
            "source": record.source,
            "source_url": record.source_url
        }
        for record in records
    ]


# ============================================================
# LATEST DISEASE ACTIVITY
# ============================================================

@router.get("/latest")
def latest_activity(
    db: Session = Depends(get_db)
):

    records = (
        db.query(IDSPSurveillance)
        .order_by(
            IDSPSurveillance.reporting_end_date.desc()
        )
        .limit(10)
        .all()
    )

    return [
        {
            "date": str(record.reporting_end_date),
            "disease": record.disease,
            "state": record.state,
            "district": record.district,
            "cases": record.cases,
            "deaths": record.deaths,
            "status": record.outbreak_status
        }
        for record in records
    ]


# ============================================================
# DISEASE SUMMARY
# ============================================================

@router.get("/summary")
def disease_summary(
    db: Session = Depends(get_db)
):

    records = db.query(IDSPSurveillance).all()

    summary = {}

    for record in records:

        disease = record.disease

        if disease not in summary:
            summary[disease] = {
                "disease": disease,
                "cases": 0,
                "deaths": 0,
                "records": 0
            }

        summary[disease]["cases"] += (
            record.cases or 0
        )

        summary[disease]["deaths"] += (
            record.deaths or 0
        )

        summary[disease]["records"] += 1

    return list(summary.values())


# ============================================================
# STATE SUMMARY
# ============================================================

@router.get("/state-summary")
def state_summary(
    db: Session = Depends(get_db)
):

    records = db.query(IDSPSurveillance).all()

    summary = {}

    for record in records:

        state = record.state

        if state not in summary:
            summary[state] = {
                "state": state,
                "cases": 0,
                "deaths": 0,
                "records": 0
            }

        summary[state]["cases"] += (
            record.cases or 0
        )

        summary[state]["deaths"] += (
            record.deaths or 0
        )

        summary[state]["records"] += 1

    return list(summary.values())
# ============================================================
# DISTRICT SUMMARY
# ============================================================

@router.get("/district-summary")
def district_summary(
    db: Session = Depends(get_db)
):

    records = db.query(IDSPSurveillance).all()

    summary = {}

    for record in records:

        district = record.district

        if district not in summary:
            summary[district] = {
                "district": district,
                "state": record.state,
                "cases": 0,
                "deaths": 0,
                "records": 0
            }

        summary[district]["cases"] += (
            record.cases or 0
        )

        summary[district]["deaths"] += (
            record.deaths or 0
        )

        summary[district]["records"] += 1

    return list(summary.values())
