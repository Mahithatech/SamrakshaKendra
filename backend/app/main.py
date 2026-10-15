from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Hospital

from app.disease_routes import router as disease_router
from app.idsp_routes import router as idsp_router
from app.advanced_routes import router as advanced_router
from app.source_routes import router as source_router
from app.india_reports_routes import router as india_reports_router
app = FastAPI(
    title="Samraksha Kendra",
    description=(
        "Digital Disease Surveillance and "
        "Early Warning System"
    ),
    version="1.0.0"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
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

app.include_router(disease_router)
app.include_router(idsp_router)
app.include_router(advanced_router)
app.include_router(source_router)
app.include_router(india_reports_router)