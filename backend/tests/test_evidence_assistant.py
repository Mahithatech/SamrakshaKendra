import pytest
from pydantic import ValidationError

from app.evidence_assistant import (
    AssistantQuestion,
    classify_intent,
    match_label,
    normalize_question,
)


def test_normalize_question_collapses_whitespace_and_case():
    assert normalize_question("  CASES   in Karnataka ") == "cases in karnataka"


def test_label_matching_prefers_longest_phrase():
    assert match_label("What about Hepatitis A in Karnataka?", ["Hepatitis", "Hepatitis A", "Karnataka"]) == "Hepatitis A"


def test_label_matching_is_case_insensitive():
    assert match_label("dengue in karnataka", ["Dengue", "Karnataka"]) == "Karnataka"


def test_label_matching_rejects_partial_word():
    assert match_label("show goat records", ["Goa"]) is None


def test_classifies_top_disease_and_state_queries():
    assert classify_intent("Which diseases have the highest reported cases?") == "top_disease"
    assert classify_intent("Which state has the most affected cases?") == "top_state"


def test_classifies_weekly_trend_queries():
    assert classify_intent("Show weekly trend for Karnataka") == "trend"


def test_question_validation_rejects_too_long_input():
    with pytest.raises(ValidationError):
        AssistantQuestion(question="x" * 401)

from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.pool import StaticPool

from app.evidence_assistant import ask_evidence_assistant
from app.models import IDSPSurveillance


@pytest.fixture
def sample_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    IDSPSurveillance.__table__.create(engine)
    with OrmSession(engine) as session:
        session.add_all([
            IDSPSurveillance(record_id="KAR/2026/08/1", year=2026, week=8,
                reporting_start_date=date(2026, 2, 16), reporting_end_date=date(2026, 2, 22),
                state="Karnataka", district="Bengaluru Urban", disease="Dengue",
                cases=12, deaths=1, source="NCDC", source_url="https://ncdc.mohfw.gov.in/week.pdf"),
            IDSPSurveillance(record_id="KAR/2026/09/2", year=2026, week=9,
                reporting_start_date=date(2026, 2, 23), reporting_end_date=date(2026, 3, 1),
                state="Karnataka", district="Mysuru", disease="Chickenpox",
                cases=4, deaths=0, source="NCDC", source_url="https://ncdc.mohfw.gov.in/week.pdf"),
            IDSPSurveillance(record_id="KER/2026/09/3", year=2026, week=9,
                reporting_start_date=date(2026, 2, 23), reporting_end_date=date(2026, 3, 1),
                state="Kerala", district="Ernakulam", disease="Dengue",
                cases=9, deaths=0, source="NCDC", source_url="https://ncdc.mohfw.gov.in/week.pdf"),
        ])
        session.commit()
        yield session
    engine.dispose()


def test_state_filtered_summary_calculates_only_matching_rows(sample_db):
    result = ask_evidence_assistant(
        AssistantQuestion(question="total cases in Karnataka", language="en"),
        db=sample_db,
    )
    assert result["status"] == "answered"
    assert result["items"][0]["records"] == 2
    assert result["items"][0]["cases"] == 16
    assert result["items"][0]["deaths"] == 1
    assert result["filters"]["state"] == "Karnataka"


def test_top_disease_aggregates_records_and_returns_source_links(sample_db):
    result = ask_evidence_assistant(
        AssistantQuestion(question="Which diseases have the highest reported cases?", language="en"),
        db=sample_db,
    )
    assert result["status"] == "answered"
    assert result["items"][0]["label"] == "Dengue"
    assert result["items"][0]["cases"] == 21
    assert any(source.get("url", "").startswith("https://ncdc.mohfw.gov.in/") for source in result["sources"])


def test_weekly_trend_returns_ordered_aggregates(sample_db):
    result = ask_evidence_assistant(
        AssistantQuestion(question="Show weekly trend", language="en"),
        db=sample_db,
    )
    assert result["status"] == "answered"
    assert [row["week"] for row in result["items"]] == [8, 9]
    assert result["items"][0]["cases"] == 12
    assert result["items"][1]["cases"] == 13


def test_localized_summary_contains_coverage_disclaimer(sample_db):
    result = ask_evidence_assistant(
        AssistantQuestion(question="సారాంశం", language="te"),
        db=sample_db,
    )
    assert result["status"] == "answered"
    assert "లోడ్ చేసిన" in result["answer"]
    assert "రియల్-టైమ్" in result["disclaimer"]


def test_short_greeting_without_question_mark_returns_help(sample_db):
    result = ask_evidence_assistant(
        AssistantQuestion(question="hi", language="en"),
        db=sample_db,
    )
    assert result["status"] == "help"
    assert "total cases in Karnataka" in result["answer"]


def test_query_without_question_mark_is_supported(sample_db):
    result = ask_evidence_assistant(
        AssistantQuestion(question="top diseases", language="en"),
        db=sample_db,
    )
    assert result["status"] == "answered"
    assert result["items"]
