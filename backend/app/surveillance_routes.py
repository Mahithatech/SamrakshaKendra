from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import SurveillanceRecord


router = APIRouter(
    prefix="/surveillance",
    tags=["Surveillance"]
)


@router.get("/count")
def get_surveillance_count(
    db: Session = Depends(get_db)
):
    count = db.query(SurveillanceRecord).count()

    return {
        "count": count
    }


@router.get("")
def get_surveillance_records(
    db: Session = Depends(get_db)
):
    records = (
        db.query(SurveillanceRecord)
        .order_by(
            SurveillanceRecord.report_date.desc()
        )
        .all()
    )

    return [
        {
            "id": record.id,
            "hospital_id": record.hospital_id,
            "disease_id": record.disease_id,
            "report_date": record.report_date,
            "suspected_cases": record.suspected_cases,
            "confirmed_cases": record.confirmed_cases,
            "recovered_cases": record.recovered_cases,
            "deaths": record.deaths,
            "latitude": record.latitude,
            "longitude": record.longitude
        }
        for record in records
    ]
