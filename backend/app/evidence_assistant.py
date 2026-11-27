"""Evidence-grounded Q&A over Samraksha Kendra's structured IDSP dataset.

This is a deterministic retrieval/aggregation assistant, not an LLM-generated
medical adviser. It only answers from rows present in the installation and
returns source links and a coverage disclaimer.
"""
from __future__ import annotations

import re
import logging
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import IDSPSurveillance
from app.synthetic_ingestion import SyntheticSurveillance
from app.gemini_service import generate_gemini_answer
from app.config import GEMINI_SURVEILLANCE_EXPLANATIONS

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
def is_greeting(question: str) -> bool:
    q = normalize_question(question)

    greetings = {
        "hi",
        "hello",
        "hey",
        "hii",
        "hiii",
        "good morning",
        "good afternoon",
        "good evening",
        "how are you",
        "how are u",
        "how r u",
        "what's up",
        "whats up",
        "thanks",
        "thank you",
    }

    return q in greetings

    return q in greetings
def is_farewell(question: str) -> bool:
    q = normalize_question(question)

    farewells = {
        "bye",
        "goodbye",
        "good bye",
        "see you",
        "see you later",
        "take care",
    }

    return q in farewells

def classify_intent(question: str) -> str:
    q = normalize_question(question)

    # Educational questions should not trigger dataset summaries.
    educational = re.match(
        r"^(what is|what are|define|explain|meaning of)\b", q
    )
    statistical = re.search(
        r"\b(total|count|cases|deaths|records|dataset|reported|highest|lowest|weekly|trend|statistics|numbers|how many)\b",
        q
    )
    if educational and not statistical:
        return "general"

    comparison_terms = (
    "compare", "comparison", "difference", "differences", "diff",
    "versus", " vs ", "vs.",
)

    official_terms = ("official", "offical", "idsp")
    synthetic_terms = ("synthetic", "sythetic", "simulated")

    if (
        any(term in q for term in comparison_terms)
        and any(term in q for term in official_terms)
        and any(term in q for term in synthetic_terms)
    ):
        return "compare_sources"

    if (
        any(term in q for term in synthetic_terms)
        or "synthetic records" in q
        or "synthetic data" in q
    ):
        return "synthetic_summary"

    top_disease = (
        "top disease", "top diseases", "most reported disease",
        "most reported diseases", "highest cases by disease",
        "highest reported cases", "which disease has the highest reported cases",
        "leading disease", "most common disease",
        "ಅತ್ಯಧಿಕ ಪ್ರಕರಣಗಳ ರೋಗ",
        "सबसे अधिक रिपोर्ट की गई बीमारी",
    )

    top_state = (
        "top state", "top states", "highest cases by state",
        "most affected state", "state with most cases",
        "which state has the most affected cases",
        "which state has highest cases", "most affected cases",
        "అత్యధిక కేసులున్న రాష్ట్రం",
        "सबसे अधिक मामलों वाला राज्य",
    )

    trend = (
        "trend", "weekly", "reporting week", "recent weeks",
        "over time", "history", "week by week",
        "ధోరణి", "వారాల వారీ", "ಪ್ರವೃತ್ತಿ", "ವಾರವಾರು",
        "रुझान", "साप्ताहिक",
    )

    if any(term in q for term in top_disease):
        return "top_disease"

    if any(term in q for term in top_state):
        return "top_state"

    if any(term in q for term in trend):
        return "trend"

    surveillance_terms = (
        "summary", "summarize", "overall", "total", "cases",
        "deaths", "records", "dataset", "surveillance",
        "reported", "idsp", "disease data", "state data",
        "outbreak data", "how many", "case count",
        "సారాంశం", "మొత్తం", "కేసులు", "మరణాలు",
        "सारांश", "कुल", "मामले", "मौतें",
    )

    if any(term in q for term in surveillance_terms):
        return "summary"

    return "general"

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

    if is_greeting(question):
        greeting_answer = (
            "Hello! I'm the Samraksha Kendra Evidence Assistant. "
            "I can help explore the loaded IDSP surveillance data, "
            "compare reported cases by state or disease, and explain this project. "
            "What would you like to know?"
        )
        if normalize_question(question) == "hi":
            return {
                "status": "help",
                "mode": "help",
                "question": question,
                "language": language,
                "answer": s["help"],
                "items": [],
                "filters": {"state": None, "district": None, "disease": None},
                "sources": [],
                "disclaimer": "Help suggestions, not a surveillance finding or medical advice.",
                "note": "Static help response."
            }

        return {
            "status": "answered",
            "mode": "greeting",
            "question": question,
            "language": language,
            "answer": greeting_answer,
            "items": [],
            "filters": {"state": None, "district": None, "disease": None},
            "sources": [],
            "disclaimer": "This is a conversational greeting, not a surveillance finding or medical advice.",
            "note": "Static greeting response; no LLM inference was performed."
        }

    if is_farewell(question):
        return {
            "status": "answered",
            "mode": "farewell",
            "question": question,
            "language": language,
            "answer": "Goodbye! Thank you for using Samraksha Kendra. Stay safe!",
            "items": [],
            "filters": {"state": None, "district": None, "disease": None},
            "sources": [],
            "disclaimer": "This is a conversational response, not a surveillance finding or medical advice.",
            "note": "Static farewell response; no LLM inference was performed."
        }

    intent = classify_intent(question)

    if intent == "general":
        try:
            answer = generate_gemini_answer(
                question=question,
                language=language,
            )
        except Exception as exc:
            logging.getLogger("uvicorn.error").error(
                "Evidence Assistant failed: type=%s status=%s",
                type(exc).__name__,
                getattr(exc, "code", "unknown")
            )
            raise HTTPException(
                status_code=503,
                detail="The AI assistant is temporarily unavailable. Please try again shortly.",
            )

        return {
            "status": "answered",
            "mode": "gemini_general",
            "question": question,
            "language": language,
            "answer": answer,
            "items": [],
            "filters": {
                "state": None,
                "district": None,
                "disease": None,
            },
            "sources": [],
            "disclaimer": "General AI-generated information. Not medical advice or an official public-health finding.",
            "note": "General response generated using Gemini. No surveillance statistics were queried.",
        }


    all_states = [x[0] for x in db.query(IDSPSurveillance.state).distinct().all() if x[0]]
    all_districts = [x[0] for x in db.query(IDSPSurveillance.district).distinct().all() if x[0]]
    all_diseases = [x[0] for x in db.query(IDSPSurveillance.disease).distinct().all() if x[0]]

    state = match_label(question, all_states)
    district = match_label(question, all_districts)
    disease = match_label(question, all_diseases)
    intent = classify_intent(question)

    # Build a separate query for synthetic demonstration records.
    synthetic_query = db.query(SyntheticSurveillance).filter(
        SyntheticSurveillance.is_synthetic.is_(True)
    )

    if state:
        synthetic_query = synthetic_query.filter(
            SyntheticSurveillance.state.ilike(state)
        )
    if district:
        synthetic_query = synthetic_query.filter(
            SyntheticSurveillance.district.ilike(district)
        )
    if disease:
        synthetic_query = synthetic_query.filter(
            SyntheticSurveillance.disease.ilike(disease)
        )

    if intent in ("synthetic_summary", "compare_sources"):
        synthetic_stats = synthetic_query.with_entities(
            func.count(SyntheticSurveillance.id).label("records"),
            func.coalesce(func.sum(SyntheticSurveillance.cases), 0).label("cases"),
            func.coalesce(func.sum(SyntheticSurveillance.deaths), 0).label("deaths"),
            func.count(func.distinct(SyntheticSurveillance.state)).label("states"),
            func.count(func.distinct(SyntheticSurveillance.disease)).label("diseases"),
        ).one()

        synthetic_data = {
            "source": "Synthetic demonstration data",
            "records": int(synthetic_stats.records or 0),
            "cases": int(synthetic_stats.cases or 0),
            "deaths": int(synthetic_stats.deaths or 0),
            "states": int(synthetic_stats.states or 0),
            "diseases": int(synthetic_stats.diseases or 0),
            "is_synthetic": True,
        }

        if intent == "synthetic_summary":
            answer = (
                "Synthetic demonstration data summary:\n"
                f"- Records: {synthetic_data['records']}\n"
                f"- Reported cases: {synthetic_data['cases']}\n"
                f"- Reported deaths: {synthetic_data['deaths']}\n"
                f"- States/UTs represented: {synthetic_data['states']}\n"
                f"- Diseases represented: {synthetic_data['diseases']}\n\n"
                "These are simulated records generated for demonstration "
                "and testing. They are not official IDSP surveillance findings."
            )

            return {
                "status": "answered",
                "mode": "synthetic_summary",
                "question": question,
                "language": language,
                "answer": answer,
                "items": [synthetic_data],
                "filters": {
                    "state": state,
                    "district": district,
                    "disease": disease,
                },
                "sources": [],
                "disclaimer": (
                    "Synthetic demonstration data only. "
                    "Not official IDSP data or a real outbreak declaration."
                ),
                "note": "Queried only sk_synthetic_surveillance.",
            }

        official_query = db.query(IDSPSurveillance)

        if state:
            official_query = official_query.filter(
                IDSPSurveillance.state.ilike(state)
            )
        if district:
            official_query = official_query.filter(
                IDSPSurveillance.district.ilike(district)
            )
        if disease:
            official_query = official_query.filter(
                IDSPSurveillance.disease.ilike(disease)
            )

        official_stats = official_query.with_entities(
            func.count(IDSPSurveillance.id).label("records"),
            func.coalesce(func.sum(IDSPSurveillance.cases), 0).label("cases"),
            func.coalesce(func.sum(IDSPSurveillance.deaths), 0).label("deaths"),
        ).one()

        official_data = {
            "source": "Official IDSP dataset",
            "records": int(official_stats.records or 0),
            "cases": int(official_stats.cases or 0),
            "deaths": int(official_stats.deaths or 0),
            "is_synthetic": False,
        }

        answer = (
            "Official IDSP and synthetic demonstration data comparison:\n\n"
            "Official IDSP dataset:\n"
            f"- Records: {official_data['records']}\n"
            f"- Reported cases: {official_data['cases']}\n"
            f"- Reported deaths: {official_data['deaths']}\n\n"
            "Synthetic demonstration dataset:\n"
            f"- Records: {synthetic_data['records']}\n"
            f"- Reported cases: {synthetic_data['cases']}\n"
            f"- Reported deaths: {synthetic_data['deaths']}\n\n"
            "Important: These datasets are stored and calculated separately. "
            "Synthetic figures are simulated and must not be interpreted "
            "as real public-health statistics."
        )

        return {
            "status": "answered",
            "mode": "source_comparison",
            "question": question,
            "language": language,
            "answer": answer,
            "items": [official_data, synthetic_data],
            "filters": {
                "state": state,
                "district": district,
                "disease": disease,
            },
            "sources": [],
            "disclaimer": (
                "Official IDSP and synthetic demonstration data are "
                "separate. Synthetic figures are not real surveillance findings."
            ),
            "note": "Both datasets queried independently; no records were combined.",
        }

    q = db.query(IDSPSurveillance)

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

    database_answer = answer
    ai_note = "Deterministic database answer."

    if GEMINI_SURVEILLANCE_EXPLANATIONS and answer_status == "answered":
        verified_context = f"""
        Original database-calculated answer:
        {database_answer}

        Verified database aggregation results:
        {items}

        Matched filters:
        State: {state}
        District: {district}
        Disease: {disease}

        IMPORTANT:
        The database results are authoritative.
        Preserve every number exactly.
        Do not describe the data as synthetic unless the supplied
        evidence explicitly identifies it as synthetic.
        Do not add unsupported findings.
        """

        try:
            gemini_answer = generate_gemini_answer(
                question=question,
                context=verified_context,
                language=language,
            )

            if gemini_answer:
                answer = f"{database_answer}\n\nAdditional explanation:\n{gemini_answer}"
                ai_note = "Database statistics calculated by SQL; additional explanation generated using Gemini."

        except Exception:
            answer = database_answer
            ai_note = "Gemini temporarily unavailable; original database answer retained."

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
        "note": ai_note,
    }
