
import logging
import time

import httpx
from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY, GEMINI_MODEL



logger = logging.getLogger("uvicorn.error")


class EmptyGeminiResponse(RuntimeError):
    pass


SYSTEM_INSTRUCTION = """
You are the AI-powered Evidence Assistant for Samraksha Kendra.

Your responsibilities:
1. Answer general educational and technical questions helpfully.
2. Explain Samraksha Kendra using only supplied project context.
3. Explain public-health concepts in simple language.
4. For surveillance questions, use only the supplied verified database evidence.
5. Treat database calculations and numbers as authoritative.
6. Never modify, recalculate, estimate, or invent statistics.
7. Never invent disease counts, deaths, dates, locations, or official findings.
8. Never declare an outbreak or diagnose a person.
9. Clearly distinguish synthetic demonstration data from official IDSP data.
10. If evidence is insufficient, say so honestly.
11. Keep answers clear, friendly, and well structured.
12. Respond in the language requested by the user.

IMPORTANT:
When database evidence is supplied, explain it without changing any
numbers or factual findings. Do not add unsupported conclusions.
"""



def generate_gemini_answer(
    question: str,
    context: str = "",
    language: str = "en",
) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured.")


    prompt = f"""
User question:
{question}

Verified project or database context:
{context if context else "No database evidence was supplied."}

Response language: {language}

Answer the user's question. Do not invent facts or statistics.
"""

    # Bound the total number of attempts; do not retry invalid credentials or requests.
    for attempt in range(1, 3):
        client = None
        try:
            client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options=types.HttpOptions(
                    timeout=15000,
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    temperature=0.4,
                    max_output_tokens=1000,
                ),
            )

            answer = (response.text or "").strip()

            if not answer:
                raise EmptyGeminiResponse("Gemini returned an empty response.")

            return answer
        except Exception as exc:
            code = getattr(exc, "code", None)
            retryable = code in (408, 429, 500, 502, 503, 504) or isinstance(
                exc, (httpx.TransportError, TimeoutError, EmptyGeminiResponse)
            )
            logger.warning(
                "Gemini request failed: type=%s status=%s attempt=%s retryable=%s",
                type(exc).__name__, code if isinstance(code, int) else "unknown", attempt, retryable,
            )
            if not retryable or attempt == 2:
                raise
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    logger.warning("Gemini client cleanup failed")
        time.sleep(1.0)
