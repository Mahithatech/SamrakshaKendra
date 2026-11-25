
"""Synthetic surveillance data generator for Samraksha Kendra.

Synthetic records are kept separate from official IDSP/NCDC records.
They are clearly labelled and must never be interpreted as confirmed outbreaks.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import Base, direct_engine


GENERATOR_VERSION = "1.0"


# Representative districts covering all 28 Indian states and 8 UTs.
# This is a sample catalogue, not a complete district master list.
LOCATIONS = {
    # States
    "Andhra Pradesh": ["Guntur", "Krishna", "Visakhapatnam", "Tirupati"],
    "Arunachal Pradesh": ["Itanagar", "Tawang", "Papum Pare"],
    "Assam": ["Guwahati", "Dibrugarh", "Jorhat"],
    "Bihar": ["Patna", "Gaya", "Muzaffarpur"],
    "Chhattisgarh": ["Raipur", "Bilaspur", "Durg"],
    "Goa": ["North Goa", "South Goa"],
    "Gujarat": ["Ahmedabad", "Surat", "Vadodara"],
    "Haryana": ["Gurugram", "Faridabad", "Hisar"],
    "Himachal Pradesh": ["Shimla", "Kangra", "Mandi"],
    "Jharkhand": ["Ranchi", "Dhanbad", "Jamshedpur"],
    "Karnataka": ["Bengaluru Urban", "Mysuru", "Belagavi", "Dharwad"],
    "Kerala": ["Thiruvananthapuram", "Ernakulam", "Kozhikode"],
    "Madhya Pradesh": ["Bhopal", "Indore", "Jabalpur"],
    "Maharashtra": ["Mumbai", "Pune", "Nagpur", "Nashik"],
    "Manipur": ["Imphal West", "Imphal East", "Bishnupur"],
    "Meghalaya": ["East Khasi Hills", "West Garo Hills", "Ri Bhoi"],
    "Mizoram": ["Aizawl", "Lunglei", "Champhai"],
    "Nagaland": ["Kohima", "Dimapur", "Mokokchung"],
    "Odisha": ["Khordha", "Cuttack", "Ganjam"],
    "Punjab": ["Ludhiana", "Amritsar", "Jalandhar"],
    "Rajasthan": ["Jaipur", "Jodhpur", "Udaipur"],
    "Sikkim": ["Gangtok", "Namchi", "Mangan"],
    "Tamil Nadu": ["Chennai", "Coimbatore", "Madurai", "Salem"],
    "Telangana": ["Hyderabad", "Rangareddy", "Warangal", "Karimnagar"],
    "Tripura": ["West Tripura", "Gomati", "Dhalai"],
    "Uttar Pradesh": ["Lucknow", "Kanpur Nagar", "Varanasi", "Agra"],
    "Uttarakhand": ["Dehradun", "Haridwar", "Nainital"],
    "West Bengal": ["Kolkata", "Howrah", "Darjeeling", "Nadia"],

    # Union Territories
    "Andaman and Nicobar Islands": ["South Andaman", "North and Middle Andaman", "Nicobar"],
    "Chandigarh": ["Chandigarh"],
    "Dadra and Nagar Haveli and Daman and Diu": [
        "Dadra and Nagar Haveli", "Daman", "Diu"
    ],
    "Delhi": ["New Delhi", "North Delhi", "South Delhi"],
    "Jammu and Kashmir": ["Srinagar", "Jammu", "Anantnag"],
    "Ladakh": ["Leh", "Kargil"],
    "Lakshadweep": ["Lakshadweep"],
    "Puducherry": ["Puducherry", "Karaikal", "Mahe", "Yanam"],
}


DISEASES = [
    "Dengue",
    "Malaria",
    "Acute Diarrhoeal Disease",
    "Influenza-like Illness",
    "Chikungunya",
    "Typhoid",
]


class SyntheticSurveillance(Base):
    """Records produced by the local synthetic data generator."""

    __tablename__ = "sk_synthetic_surveillance"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_sk_synthetic_fingerprint"),
    )

    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(String(100), unique=True, nullable=False, index=True)
    year = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    reporting_start_date = Column(Date, nullable=False)
    reporting_end_date = Column(Date, nullable=False)
    state = Column(String(100), nullable=False, index=True)
    district = Column(String(100), nullable=False, index=True)
    disease = Column(String(150), nullable=False, index=True)
    cases = Column(Integer, nullable=False, default=0)
    deaths = Column(Integer, nullable=False, default=0)
    outbreak_status = Column(String(50), nullable=False)
    source = Column(String(100), nullable=False, default="SYNTHETIC_GENERATOR")
    source_url = Column(String(500), nullable=True)
    is_synthetic = Column(Boolean, nullable=False, default=True)
    generated_at = Column(DateTime(timezone=True), nullable=False)
    generator_version = Column(String(30), nullable=False)
    fingerprint = Column(String(64), nullable=False)


def ensure_synthetic_schema() -> None:
    """Create only the synthetic table; do not modify official tables."""
    if direct_engine is None:
        raise RuntimeError("DATABASE_DIRECT_URL is required for synthetic generation.")

    SyntheticSurveillance.__table__.create(
        bind=direct_engine,
        checkfirst=True,
    )


def validate_synthetic_record(record: dict) -> tuple[bool, str]:
    """Structural validation only; this does not establish a real outbreak."""

    required = (
        "record_id", "year", "week", "reporting_start_date",
        "reporting_end_date", "state", "district", "disease",
        "cases", "deaths", "outbreak_status",
    )

    if any(record.get(key) in (None, "") for key in required):
        return False, "Missing required field"

    if record["state"] not in LOCATIONS:
        return False, "Unknown synthetic state"

    if record["district"] not in LOCATIONS[record["state"]]:
        return False, "District does not belong to the configured state"

    if record["disease"] not in DISEASES:
        return False, "Unknown disease"

    if not isinstance(record["cases"], int) or record["cases"] < 0:
        return False, "Cases must be a non-negative integer"

    if not isinstance(record["deaths"], int) or not 0 <= record["deaths"] <= record["cases"]:
        return False, "Deaths must be between zero and cases"

    if not 1 <= record["week"] <= 53:
        return False, "Invalid epidemiological week"

    if record["reporting_end_date"] < record["reporting_start_date"]:
        return False, "Invalid reporting date range"

    return True, "Structurally valid synthetic record"


def _make_record(state: str, district: str, disease: str, period_start: date) -> dict:
    """Build a deterministic record for one location, disease and week."""

    period_end = period_start + timedelta(days=6)
    year, week, _ = period_start.isocalendar()

    identity = f"{GENERATOR_VERSION}|{year}|{week}|{state}|{district}|{disease}"
    fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    # Stable numbers for the same location, disease and reporting week.
    rng = random.Random(int(fingerprint[:16], 16))
    cases = rng.randint(5, 80)
    deaths = rng.randint(0, min(2, cases))

    return {
        "record_id": f"SYN-{fingerprint[:20].upper()}",
        "year": year,
        "week": week,
        "reporting_start_date": period_start,
        "reporting_end_date": period_end,
        "state": state,
        "district": district,
        "disease": disease,
        "cases": cases,
        "deaths": deaths,
        "outbreak_status": "SYNTHETIC_SIGNAL" if cases >= 60 else "SYNTHETIC_NORMAL",
        "source": "SYNTHETIC_GENERATOR",
        "source_url": None,
        "is_synthetic": True,
        "generated_at": datetime.now(timezone.utc),
        "generator_version": GENERATOR_VERSION,
        "fingerprint": fingerprint,
    }


def generate_synthetic_records(
    records_per_cycle: int = 12,
    period_start: date | None = None,
) -> dict:
    """Generate a bounded, repeatable batch of clearly labelled records."""

    if not 1 <= records_per_cycle <= 100:
        raise ValueError("records_per_cycle must be between 1 and 100")

    ensure_synthetic_schema()

    today = date.today()
    start = period_start or (today - timedelta(days=today.weekday()))
    if start > today or start.weekday() != 0:
        raise ValueError("period_start must be a Monday no later than today")

    # Select at least one location/disease combination for every State/UT.
    period_key = f"{start.isoformat()}|{GENERATOR_VERSION}"
    seed = int(hashlib.sha256(period_key.encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)

    selected = []

    for state, districts in LOCATIONS.items():
        district = rng.choice(districts)
        disease = rng.choice(DISEASES)
        selected.append((state, district, disease))

    # Add extra records if the requested batch is larger than 36.
    remaining = []
    for state, districts in LOCATIONS.items():
        for district in districts:
            for disease in DISEASES:
                candidate = (state, district, disease)
                if candidate not in selected:
                    remaining.append(candidate)

    rng.shuffle(remaining)
    selected.extend(remaining[:max(0, records_per_cycle - len(selected))])

    created = 0
    skipped = 0
    invalid = 0

    if direct_engine is None:
        raise RuntimeError("DATABASE_DIRECT_URL is required for synthetic generation.")
    with Session(direct_engine) as db:
        for state, district, disease in selected:
            record = _make_record(state, district, disease, start)
            valid, _reason = validate_synthetic_record(record)

            if not valid:
                invalid += 1
                continue

            exists = db.query(SyntheticSurveillance.id).filter_by(
                fingerprint=record["fingerprint"]
            ).first()

            if exists:
                skipped += 1
                continue

            try:
                db.add(SyntheticSurveillance(**record))
                db.commit()
                created += 1
            except IntegrityError:
                db.rollback()
                skipped += 1

    return {
        "status": "success",
        "source": "SYNTHETIC_GENERATOR",
        "is_synthetic": True,
        "created": created,
        "skipped_existing": skipped,
        "invalid": invalid,
        "period_start": start.isoformat(),
    }
