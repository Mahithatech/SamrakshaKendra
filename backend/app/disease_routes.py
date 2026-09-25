from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Disease


router = APIRouter(
    prefix="/diseases",
    tags=["Diseases"]
)


@router.get("/count")
def disease_count(
    db: Session = Depends(get_db)
):
    count = db.query(Disease).count()

    return {
        "count": count
    }


@router.get("")
def get_diseases(
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db)
):
    query = db.query(Disease)

    if search:
        query = query.filter(
            Disease.name.ilike(f"%{search}%")
        )

    if category:
        query = query.filter(
            Disease.category.ilike(f"%{category}%")
        )

    diseases = (
        query
        .order_by(Disease.name)
        .limit(limit)
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