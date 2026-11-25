from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL, DATABASE_DIRECT_URL


class Base(DeclarativeBase):
    pass


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)
direct_engine = (
    create_engine(
        DATABASE_DIRECT_URL,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    if DATABASE_DIRECT_URL
    else None
)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()