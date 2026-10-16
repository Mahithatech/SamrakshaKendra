import os
from dotenv import load_dotenv

load_dotenv()

_database_url = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:root@localhost:5432/samraksha_kendra",
)
if _database_url.startswith("postgres://"):
    _database_url = "postgresql+psycopg://" + _database_url[len("postgres://"):]
elif _database_url.startswith("postgresql://"):
    _database_url = "postgresql+psycopg://" + _database_url[len("postgresql://"):]
DATABASE_URL = _database_url