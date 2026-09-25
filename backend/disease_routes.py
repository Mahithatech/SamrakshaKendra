from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Disease


router = APIRouter(
    prefix="/diseases",
    tags=["Diseases"]
)


@router.get("/count")
def get_disease_count(
    db: Session = Depends(get_db)
):
    count = db.query(func.count(Disease.id)).scalar()

    return {
        "count": count
    }


@router.get("")
def get_diseases(
    db: Session = Depends(get_db)
):
    diseases = (
        db.query(Disease)
        .order_by(Disease.name)
        .all()
    )

    return [
        {
            "id": disease.id,
            "name": disease.name,
            "category": disease.category,
            "description": disease.description
        }
        for disease in diseases
    ]


@router.get("/{disease_id}")
def get_disease(
    disease_id: int,
    db: Session = Depends(get_db)
):
    disease = (
        db.query(Disease)
        .filter(Disease.id == disease_id)
        .first()
    )

    if not disease:
        return {
            "error": "Disease not found"
        }

    return {
        "id": disease.id,
        "name": disease.name,
        "category": disease.category,
        "description": disease.description
    }