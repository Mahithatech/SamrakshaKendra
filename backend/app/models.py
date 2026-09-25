from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Hospital(Base):
    __tablename__ = "hospitals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    state: Mapped[str] = mapped_column(Text)
    district: Mapped[str] = mapped_column(Text)
    city: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text)
    address: Mapped[str] = mapped_column(Text)

    pincode: Mapped[str] = mapped_column(Text)
    phone: Mapped[str] = mapped_column(Text)

    email: Mapped[str] = mapped_column(String(255))
    website: Mapped[str] = mapped_column(Text)

    surveillance_records = relationship(
        "SurveillanceRecord",
        back_populates="hospital"
    )


class Disease(Base):
    __tablename__ = "diseases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String(150),
        unique=True,
        nullable=False
    )
    category: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)

    surveillance_records = relationship(
        "SurveillanceRecord",
        back_populates="disease"
    )


class SurveillanceRecord(Base):
    __tablename__ = "surveillance_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    hospital_id: Mapped[int] = mapped_column(
        ForeignKey("hospitals.id"),
        nullable=False
    )

    disease_id: Mapped[int] = mapped_column(
        ForeignKey("diseases.id"),
        nullable=False
    )

    report_date: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    suspected_cases: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    confirmed_cases: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    recovered_cases: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    deaths: Mapped[int] = mapped_column(
        Integer,
        default=0
    )

    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    hospital = relationship(
        "Hospital",
        back_populates="surveillance_records"
    )

    disease = relationship(
        "Disease",
        back_populates="surveillance_records"
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    disease_id: Mapped[int] = mapped_column(
        ForeignKey("diseases.id"),
        nullable=False
    )

    hospital_id: Mapped[int] = mapped_column(
        ForeignKey("hospitals.id"),
        nullable=False
    )

    alert_level: Mapped[str] = mapped_column(
        String(30),
        nullable=False
    )

    message: Mapped[str] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )


# ============================================================
# OFFICIAL IDSP DISTRICT-LEVEL SURVEILLANCE DATA
# ============================================================

class IDSPSurveillance(Base):
    __tablename__ = "idsp_surveillance"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True
    )

    record_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True
    )

    year: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    week: Mapped[int] = mapped_column(
        Integer,
        nullable=False
    )

    reporting_start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    reporting_end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False
    )

    state: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True
    )

    district: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True
    )

    disease: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
        index=True
    )

    cases: Mapped[int | None] = mapped_column(
        Integer
    )

    deaths: Mapped[int | None] = mapped_column(
        Integer
    )

    outbreak_status: Mapped[str | None] = mapped_column(
        String(100)
    )

    source: Mapped[str | None] = mapped_column(
        String(255)
    )

    source_url: Mapped[str | None] = mapped_column(
        Text
    )