"""Evidence-grounded Q&A over Samraksha Kendra's structured IDSP dataset.

This is a deterministic retrieval/aggregation assistant, not an LLM-generated
medical adviser. It only answers from rows present in the installation and
returns source links and a coverage disclaimer.
"""
from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import IDSPSurveillance

router = APIRouter(prefix="/public/assistant", tags=["Evidence Assistant"])
Language = Literal["en", "te", "kn", "hi"]


class AssistantQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=400)
    language: Language = "en"


def normalize_question(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def match_label(question: str, labels: list[str]) -> str | None:
    """Match a known database label as a whole phrase, preferring longer names."""
    q = normalize_question(question)
    for label in sorted({str(x).strip() for x in labels if x and str(x).strip()}, key=len, reverse=True):
        pattern = r"(?<![\w])" + re.escape(label.casefold()) + r"(?![\w])"
        if re.search(pattern, q, flags=re.UNICODE):
            return label
    return None


def classify_intent(question: str) -> str:
    q = normalize_question(question)
    top_disease = (
        "top disease", "top diseases", "most reported disease", "most reported diseases",
        "highest cases by disease", "highest reported cases", "which disease has the highest reported cases", "leading disease", "most common disease",
        "అత్యధికంగా నివేదించిన వ్యాధి", "అత్యధిక కేసులున్న వ్యాధులు", "అత్యధికంగా నివేదించిన వ్యాధులు", "ಹೆಚ್ಚು ವರದಿಯಾದ ರೋಗ", "सबसे अधिक रिपोर्ट की गई बीमारी", "सबसे अधिक रिपोर्ट की गई बीमारियाँ", "सबसे अधिक रिपोर्ट की गई बीमारियां",
    )
    top_state = (
        "top state", "top states", "highest cases by state", "most affected state",
        "state with most cases", "which state has the most affected cases", "which state has highest cases", "most affected cases", "అత్యధిక కేసులున్న రాష్ట్రం", "అత్యధిక కేసులున్న రాష్ట్రాలు", "ಅತ್ಯಧಿಕ ಪ್ರಕರಣಗಳ ರಾಜ್ಯ", "ಅತ್ಯಧಿಕ ಪ್ರಕರಣಗಳ ರಾಜ್ಯಗಳು", "सबसे अधिक मामलों वाला राज्य", "सबसे अधिक मामलों वाले राज्य",
    )
    trend = (
        "trend", "weekly", "reporting week", "recent weeks", "over time", "history",
        "ధోరణి", "వారాల వారీ", "ಪ್ರವೃತ್ತಿ", "ವಾರವಾರು", "रुझान", "साप्ताहिक",
    )
    if any(term in q for term in top_disease):
        return "top_disease"
    if any(term in q for term in top_state):
        return "top_state"
    if any(term in q for term in trend):
        return "trend"
    return "summary"


_STRINGS = {
    "en": {
        "summary": "In the loaded structured surveillance dataset{scope}, {records} records contain {cases} reported cases and {deaths} reported deaths.",
        "top_disease": "Highest reported diseases in the available dataset: {items}.",
        "top_state": "States with the highest reported case totals in the available dataset: {items}.",
        "trend": "Latest available reporting weeks{scope}: {items}.",
        "empty": "No matching structured surveillance records were found for that query.",
        "help": "I can summarize the loaded dataset, compare reported cases by state or disease, and show recent reporting-week totals. Try “total cases in Karnataka”, “dengue in Kerala”, “top diseases”, or “weekly trend”.",
        "source": "Structured IDSP surveillance dataset",
        "cases": "cases", "deaths": "deaths", "week": "week",
        "scope_state": " for state {value}", "scope_district": " for district {value}", "scope_disease": " for disease {value}",
        "disclaimer": "Coverage note: figures represent only records loaded in this installation. They are not a real-time national case count, clinical advice, or an official outbreak declaration.",
        "invalid": "Please enter a question between 3 and 400 characters.",
    },
    "te": {
        "summary": "లోడ్ చేసిన నిర్మిత నిఘా డేటాసెట్{scope}లో {records} రికార్డుల్లో {cases} నివేదించిన కేసులు, {deaths} నివేదించిన మరణాలు ఉన్నాయి.",
        "top_disease": "అందుబాటులో ఉన్న డేటాలో అత్యధికంగా నివేదించిన వ్యాధులు: {items}.",
        "top_state": "అందుబాటులో ఉన్న డేటాలో అత్యధిక కేసులున్న రాష్ట్రాలు: {items}.",
        "trend": "తాజా అందుబాటులో ఉన్న నివేదిక వారాలు{scope}: {items}.",
        "empty": "ఈ ప్రశ్నకు సరిపడే నిర్మిత నిఘా రికార్డులు కనబడలేదు.",
        "help": "లోడ్ చేసిన డేటా సారాంశం, రాష్ట్రం లేదా వ్యాధి వారీ కేసులు, ఇటీవలి నివేదిక వారాల మొత్తాలు చూపగలను. ఉదాహరణలు: “total cases in Karnataka”, “dengue in Kerala”, “top diseases”, “weekly trend”.",
        "source": "నిర్మిత IDSP నిఘా డేటాసెట్", "cases": "కేసులు", "deaths": "మరణాలు", "week": "వారం",
        "scope_state": " రాష్ట్రం {value} కోసం", "scope_district": " జిల్లా {value} కోసం", "scope_disease": " వ్యాధి {value} కోసం",
        "disclaimer": "గమనిక: ఇవి ఈ వ్యవస్థలో లోడ్ చేసిన రికార్డుల సంఖ్యలు మాత్రమే. ఇవి దేశవ్యాప్త రియల్-టైమ్ కేసుల సంఖ్యలు, వైద్య సలహా లేదా అధికారిక వ్యాధి వ్యాప్తి ప్రకటన కావు.",
        "invalid": "దయచేసి 3 నుండి 400 అక్షరాల మధ్య ప్రశ్న ఇవ్వండి.",
    },
    "kn": {
        "summary": "ಲೋಡ್ ಮಾಡಿದ ರಚನಾತ್ಮಕ ಮೇಲ್ವಿಚಾರಣಾ ಡೇಟಾಸೆಟ್{scope}ನಲ್ಲಿ {records} ದಾಖಲೆಗಳಲ್ಲಿ {cases} ವರದಿಯಾದ ಪ್ರಕರಣಗಳು ಮತ್ತು {deaths} ವರದಿಯಾದ ಸಾವುಗಳಿವೆ.",
        "top_disease": "ಲಭ್ಯವಿರುವ ಡೇಟಾದಲ್ಲಿ ಹೆಚ್ಚು ವರದಿಯಾದ ರೋಗಗಳು: {items}.",
        "top_state": "ಲಭ್ಯವಿರುವ ಡೇಟಾದಲ್ಲಿ ಹೆಚ್ಚು ವರದಿಯಾದ ಪ್ರಕರಣಗಳಿರುವ ರಾಜ್ಯಗಳು: {items}.",
        "trend": "ಇತ್ತೀಚಿನ ಲಭ್ಯ ವರದಿ ವಾರಗಳು{scope}: {items}.",
        "empty": "ಈ ಪ್ರಶ್ನೆಗೆ ಹೊಂದುವ ರಚನಾತ್ಮಕ ಮೇಲ್ವಿಚಾರಣಾ ದಾಖಲೆಗಳು ಸಿಗಲಿಲ್ಲ.",
        "help": "ಲೋಡ್ ಮಾಡಿದ ಡೇಟಾದ ಸಾರಾಂಶ, ರಾಜ್ಯ ಅಥವಾ ರೋಗವಾರು ಪ್ರಕರಣಗಳು ಮತ್ತು ಇತ್ತೀಚಿನ ವರದಿ ವಾರಗಳ ಮೊತ್ತವನ್ನು ತೋರಿಸಬಲ್ಲೆ. ಉದಾಹರಣೆಗಳು: “total cases in Karnataka”, “dengue in Kerala”, “top diseases”, “weekly trend”.",
        "source": "ರಚನಾತ್ಮಕ IDSP ಮೇಲ್ವಿಚಾರಣಾ ಡೇಟಾಸೆಟ್", "cases": "ಪ್ರಕರಣಗಳು", "deaths": "ಸಾವುಗಳು", "week": "ವಾರ",
        "scope_state": " ರಾಜ್ಯ {value} ಗಾಗಿ", "scope_district": " ಜಿಲ್ಲೆ {value} ಗಾಗಿ", "scope_disease": " ರೋಗ {value} ಗಾಗಿ",
        "disclaimer": "ಗಮನಿಸಿ: ಈ ಸಂಖ್ಯೆಗಳು ಈ ವ್ಯವಸ್ಥೆಯಲ್ಲಿ ಲೋಡ್ ಮಾಡಿದ ದಾಖಲೆಗಳಿಗೆ ಮಾತ್ರ ಸಂಬಂಧಿಸಿದವು. ಇವು ರಾಷ್ಟ್ರವ್ಯಾಪಿ ನೈಜ-ಸಮಯದ ಪ್ರಕರಣಗಳ ಸಂಖ್ಯೆ, ವೈದ್ಯಕೀಯ ಸಲಹೆ ಅಥವಾ ಅಧಿಕೃತ ರೋಗ ಹರಡುವಿಕೆ ಘೋಷಣೆಗಳಲ್ಲ.",
        "invalid": "ದಯವಿಟ್ಟು 3 ರಿಂದ 400 ಅಕ್ಷರಗಳ ಪ್ರಶ್ನೆ ನಮೂದಿಸಿ.",
    },
    "hi": {
        "summary": "लोड किए गए संरचित निगरानी डेटासेट{scope} में {records} रिकॉर्ड हैं, जिनमें {cases} रिपोर्ट किए गए मामले और {deaths} रिपोर्ट की गई मौतें हैं।",
        "top_disease": "उपलब्ध डेटासेट में सबसे अधिक रिपोर्ट की गई बीमारियाँ: {items}।",
        "top_state": "उपलब्ध डेटासेट में सबसे अधिक रिपोर्ट किए गए मामलों वाले राज्य: {items}।",
        "trend": "नवीनतम उपलब्ध रिपोर्टिंग सप्ताह{scope}: {items}।",
        "empty": "इस प्रश्न से मेल खाने वाले संरचित निगरानी रिकॉर्ड नहीं मिले।",
        "help": "मैं उपलब्ध डेटासेट का सारांश, राज्य या बीमारी के अनुसार मामले और नवीनतम रिपोर्टिंग-सप्ताह के आँकड़े दिखा सकता हूँ। उदाहरण: “total cases in Karnataka”, “dengue in Kerala”, “top diseases”, “weekly trend”.",
        "source": "संरचित IDSP निगरानी डेटासेट", "cases": "मामले", "deaths": "मौतें", "week": "सप्ताह",
        "scope_state": " राज्य {value} के लिए", "scope_district": " ज़िला {value} के लिए", "scope_disease": " बीमारी {value} के लिए",
        "disclaimer": "ध्यान दें: ये आँकड़े केवल इस इंस्टॉलेशन में लोड किए गए रिकॉर्ड दर्शाते हैं। ये राष्ट्रीय रीयल-टाइम कुल, चिकित्सकीय सलाह या आधिकारिक प्रकोप घोषणा नहीं हैं।",
        "invalid": "कृपया 3 से 400 अक्षरों के बीच प्रश्न दर्ज करें।",
    },
}


def _safe_sources(rows: list[IDSPSurveillance], language: str) -> list[dict]:
    strings = _STRINGS.get(language, _STRINGS["en"])
    items = [{"title": strings["source"], "path": "/public/surveillance/summary"}]
    seen = set()
    for row in rows:
        url = (row.source_url or "").strip()
        parsed = urlparse(url)
        if parsed.scheme == "https" and parsed.netloc and url not in seen:
            seen.add(url)
            items.append({"title": row.source or strings["source"], "url": url})
        if len(items) >= 4:
            break
    return items


def _format_scope(strings: dict, state: str | None, district: str | None, disease: str | None) -> str:
    parts = []
    if state:
        parts.append(strings["scope_state"].format(value=state))
    if district:
        parts.append(strings["scope_district"].format(value=district))
    if disease:
        parts.append(strings["scope_disease"].format(value=disease))
    return "".join(parts)


@router.post("/query")
def ask_evidence_assistant(payload: AssistantQuestion, db: Session = Depends(get_db)):
    question = payload.question.strip()
    if not question or len(question) > 400:
        raise HTTPException(status_code=422, detail="Question must contain 1–400 non-whitespace characters.")

    language = payload.language if payload.language in _STRINGS else "en"
    s = _STRINGS[language]
    all_states = [x[0] for x in db.query(IDSPSurveillance.state).distinct().all() if x[0]]
    all_districts = [x[0] for x in db.query(IDSPSurveillance.district).distinct().all() if x[0]]
    all_diseases = [x[0] for x in db.query(IDSPSurveillance.disease).distinct().all() if x[0]]
    state = match_label(question, all_states)
    district = match_label(question, all_districts)
    disease = match_label(question, all_diseases)
    intent = classify_intent(question)

    q = db.query(IDSPSurveillance)
    if state:
        q = q.filter(IDSPSurveillance.state.ilike(state))
    if district:
        q = q.filter(IDSPSurveillance.district.ilike(district))
    if disease:
        q = q.filter(IDSPSurveillance.disease.ilike(disease))

    scope = _format_scope(s, state, district, disease)
    items: list[dict] = []
    evidence_rows: list[IDSPSurveillance] = []

    if intent == "top_disease":
        grouped = (
            q.with_entities(
                IDSPSurveillance.disease,
                func.coalesce(func.sum(IDSPSurveillance.cases), 0).label("cases"),
                func.coalesce(func.sum(IDSPSurveillance.deaths), 0).label("deaths"),
                func.count(IDSPSurveillance.id).label("records"),
            )
            .group_by(IDSPSurveillance.disease)
            .order_by(func.coalesce(func.sum(IDSPSurveillance.cases), 0).desc(), IDSPSurveillance.disease.asc())
            .limit(5).all()
        )
        items = [{"label": row.disease, "cases": int(row.cases or 0), "deaths": int(row.deaths or 0), "records": int(row.records or 0)} for row in grouped]
        listing = "; ".join(f"{x['label']}: {x['cases']} {s['cases']}, {x['deaths']} {s['deaths']}" for x in items)
        answer = s["top_disease"].format(items=listing) if listing else s["empty"]
        evidence_rows = q.order_by(IDSPSurveillance.year.desc(), IDSPSurveillance.week.desc()).limit(8).all()
    elif intent == "top_state":
        grouped = (
            q.with_entities(
                IDSPSurveillance.state,
                func.coalesce(func.sum(IDSPSurveillance.cases), 0).label("cases"),
                func.coalesce(func.sum(IDSPSurveillance.deaths), 0).label("deaths"),
                func.count(IDSPSurveillance.id).label("records"),
            )
            .group_by(IDSPSurveillance.state)
            .order_by(func.coalesce(func.sum(IDSPSurveillance.cases), 0).desc(), IDSPSurveillance.state.asc())
            .limit(5).all()
        )
        items = [{"label": row.state, "cases": int(row.cases or 0), "deaths": int(row.deaths or 0), "records": int(row.records or 0)} for row in grouped]
        listing = "; ".join(f"{x['label']}: {x['cases']} {s['cases']}, {x['deaths']} {s['deaths']}" for x in items)
        answer = s["top_state"].format(items=listing) if listing else s["empty"]
        evidence_rows = q.order_by(IDSPSurveillance.year.desc(), IDSPSurveillance.week.desc()).limit(8).all()
    elif intent == "trend":
        grouped = (
            q.with_entities(
                IDSPSurveillance.year,
                IDSPSurveillance.week,
                func.coalesce(func.sum(IDSPSurveillance.cases), 0).label("cases"),
                func.coalesce(func.sum(IDSPSurveillance.deaths), 0).label("deaths"),
                func.count(IDSPSurveillance.id).label("records"),
            )
            .group_by(IDSPSurveillance.year, IDSPSurveillance.week)
            .order_by(IDSPSurveillance.year.desc(), IDSPSurveillance.week.desc())
            .limit(8).all()
        )
        grouped = list(reversed(grouped))
        items = [{"label": f"{row.year} · {s['week']} {row.week}", "year": int(row.year), "week": int(row.week), "cases": int(row.cases or 0), "deaths": int(row.deaths or 0), "records": int(row.records or 0)} for row in grouped]
        listing = "; ".join(f"{x['label']}: {x['cases']} {s['cases']}, {x['deaths']} {s['deaths']}" for x in items)
        answer = s["trend"].format(scope=scope, items=listing) if listing else s["empty"]
        evidence_rows = q.order_by(IDSPSurveillance.year.desc(), IDSPSurveillance.week.desc()).limit(8).all()
    else:
        count = q.count()
        cases, deaths, states_count, diseases_count = q.with_entities(
            func.coalesce(func.sum(IDSPSurveillance.cases), 0),
            func.coalesce(func.sum(IDSPSurveillance.deaths), 0),
            func.count(func.distinct(IDSPSurveillance.state)),
            func.count(func.distinct(IDSPSurveillance.disease)),
        ).one()
        if count == 0:
            answer = s["empty"]
        else:
            answer = s["summary"].format(scope=scope, records=count, cases=int(cases or 0), deaths=int(deaths or 0))
        items = [{"records": count, "cases": int(cases or 0), "deaths": int(deaths or 0), "states": int(states_count or 0), "diseases": int(diseases_count or 0)}] if count else []
        evidence_rows = q.order_by(IDSPSurveillance.year.desc(), IDSPSurveillance.week.desc()).limit(8).all()

    answer_status = "answered" if items else "no_records"
    if not state and not district and not disease and intent == "summary" and not any(k in normalize_question(question) for k in (
        "summary", "summarize", "overall", "total", "cases", "deaths", "records", "dataset", "overview",
        "సారాంశం", "మొత్తం", "ఒಟ್ಟು", "सारांश", "कुल",
    )):
        answer = s["help"]
        answer_status = "help"

    return {
        "status": answer_status,
        "mode": "retrieval_and_aggregation",
        "question": question,
        "language": language,
        "answer": answer,
        "items": items,
        "filters": {"state": state, "district": district, "disease": disease},
        "sources": _safe_sources(evidence_rows, language),
        "disclaimer": s["disclaimer"],
        "note": "Answers are generated from stored structured IDSP rows and deterministic aggregation; no LLM inference or diagnosis is performed.",
    }
