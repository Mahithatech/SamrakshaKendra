
import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve backend/.env independently of the current working directory.
BACKEND_ENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(BACKEND_ENV, override=False)

_database_url = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:root@localhost:5432/samraksha_kendra",
)

if _database_url.startswith("postgres://"):
    _database_url = "postgresql+psycopg://" + _database_url[len("postgres://"):]
elif _database_url.startswith("postgresql://"):
    _database_url = "postgresql+psycopg://" + _database_url[len("postgresql://"):]

DATABASE_URL = _database_url
DATABASE_DIRECT_URL = os.getenv("DATABASE_DIRECT_URL", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
GEMINI_SURVEILLANCE_EXPLANATIONS = (
    os.getenv("GEMINI_SURVEILLANCE_EXPLANATIONS", "false").strip().lower()
    == "true"
)
